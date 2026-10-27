#import <UIKit/UIKit.h>
#import <os/log.h>
#import "AudioHook.h"
#import "../ui/FloatingOverlay.h"

static os_log_t sLogLifecycle;
static os_log_t sLogAudio;
static dispatch_source_t sDiagTimer;
static CFAbsoluteTime sBootTimestamp = 0.0;
static BOOL sBootCountResetDone = NO;
static NSString* sBootCountPath = nil;

static NSString* HotReloadDir(void) {
    NSString* docs = NSSearchPathForDirectoriesInDomains(NSDocumentDirectory, NSUserDomainMask, YES).firstObject;
    if (!docs) return nil;
    NSString* dir = [docs stringByAppendingPathComponent:@"PluginHotReload"];
    [[NSFileManager defaultManager] createDirectoryAtPath:dir withIntermediateDirectories:YES attributes:nil error:nil];
    return dir;
}

static void StartMainThreadDiagnosticsTimer(void) {
    sDiagTimer = dispatch_source_create(DISPATCH_SOURCE_TYPE_TIMER, 0, 0, dispatch_get_main_queue());
    dispatch_source_set_timer(sDiagTimer, dispatch_time(DISPATCH_TIME_NOW, NSEC_PER_SEC), NSEC_PER_SEC, 100 * NSEC_PER_MSEC);
    dispatch_source_set_event_handler(sDiagTimer, ^{
        [[FLMFloatingOverlay shared] refreshDiagnosticsStatus];

        bool safe = flm_dsp::AudioHook::isSafeMode();
        bool hooked = flm_dsp::AudioHook::isHookInstalled();
        uint64_t cb = flm_dsp::AudioHook::callbackCount();
        uint32_t frames = flm_dsp::AudioHook::lastFrames();
        float sr = flm_dsp::AudioHook::currentSampleRate();
        uint32_t flags = flm_dsp::AudioHook::formatFlags();
        uint32_t bits = flm_dsp::AudioHook::bitsPerChannel();
        uint32_t ch = flm_dsp::AudioHook::channelsPerFrame();
        bool inter = flm_dsp::AudioHook::isInterleaved();
        auto fkind = flm_dsp::AudioHook::formatKind();
        const char* fmtStr = (fkind == flm_dsp::AudioFormatKind::Float32Planar) ? "F32P" :
                             (fkind == flm_dsp::AudioFormatKind::Float32Inter)  ? "F32I" :
                             (fkind == flm_dsp::AudioFormatKind::Unsupported)   ? "UNSUPPORTED" : "WAIT";
        const char* modeStr = (flm_dsp::AudioHook::getMode() == flm_dsp::HookMode::MasterOut) ? "MASTER" : "MIC";

        // Reset boot_count to 0 ONLY when BOTH conditions hold: cb > 0 AND >= 60s elapsed without crash
        if (!safe && !sBootCountResetDone && cb > 0 && (CFAbsoluteTimeGetCurrent() - sBootTimestamp) >= 60.0) {
            if (sBootCountPath) {
                [@"0\n" writeToFile:sBootCountPath atomically:YES encoding:NSUTF8StringEncoding error:nil];
            }
            sBootCountResetDone = YES;
            os_log_info(sLogLifecycle, "Stability verified (>=60s elapsed and cb=%llu > 0): boot_count reset to 0.",
                        (unsigned long long)cb);
        }

        os_log_info(sLogAudio,
                    "status: safe=%d HOOK=%{public}s cb=%llu frames=%u SR=%.0f FMT=%{public}s (flags=0x%x bits=%u ch=%u interleaved=%d) mode=%{public}s",
                    safe ? 1 : 0, hooked ? "OK" : "OFF", (unsigned long long)cb, (unsigned int)frames, sr,
                    fmtStr, flags, bits, ch, inter ? 1 : 0, modeStr);
    });
    dispatch_resume(sDiagTimer);
}

__attribute__((constructor))
static void FLMCustomDSP_Init(void) {
    sLogLifecycle = os_log_create("FLM_CustomDSP", "lifecycle");
    sLogAudio     = os_log_create("FLM_CustomDSP", "audio");
    sBootTimestamp = CFAbsoluteTimeGetCurrent();

    // 1. Crash-Guard check in Documents/PluginHotReload/boot_count & safe_mode.flag
    NSString* hrDir = HotReloadDir();
    sBootCountPath = [hrDir stringByAppendingPathComponent:@"boot_count"];
    NSString* flagPath = [hrDir stringByAppendingPathComponent:@"safe_mode.flag"];

    BOOL flagExists = (flagPath && [[NSFileManager defaultManager] fileExistsAtPath:flagPath]);
    NSInteger bootCount = 0;
    if (sBootCountPath && [[NSFileManager defaultManager] fileExistsAtPath:sBootCountPath]) {
        NSString* content = [NSString stringWithContentsOfFile:sBootCountPath encoding:NSUTF8StringEncoding error:nil];
        bootCount = [content integerValue];
    }
    bootCount += 1;
    if (sBootCountPath) {
        [[NSString stringWithFormat:@"%ld\n", (long)bootCount] writeToFile:sBootCountPath atomically:YES encoding:NSUTF8StringEncoding error:nil];
    }

    if (bootCount >= 3 || flagExists) {
        flm_dsp::AudioHook::setSafeMode(true);
        os_log_error(sLogLifecycle, "SAFE MODE triggered (boot_count=%ld, flag=%d). Skipping CoreAudio hooks.",
                     (long)bootCount, flagExists ? 1 : 0);
    } else {
        flm_dsp::AudioHook::setSafeMode(false);
        flm_dsp::AudioHook::install();
        os_log_info(sLogLifecycle, "CoreAudio hooks installed (boot_count=%ld). Waiting for >=60s & cb>0 to reset crash-guard.",
                    (long)bootCount);
    }

    // 2. Attach Floating UI Overlay & start 1 Hz main-thread diagnostics timer
    NSNotificationCenter* nc = [NSNotificationCenter defaultCenter];
    [nc addObserverForName:UIApplicationDidBecomeActiveNotification
                    object:nil
                     queue:[NSOperationQueue mainQueue]
                usingBlock:^(__unused NSNotification* note) {
                    [[FLMFloatingOverlay shared] attachToActiveWindow];
                }];

    [nc addObserverForName:UIWindowDidBecomeKeyNotification
                    object:nil
                     queue:[NSOperationQueue mainQueue]
                usingBlock:^(__unused NSNotification* note) {
                    [[FLMFloatingOverlay shared] attachToActiveWindow];
                }];

    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(1.2 * NSEC_PER_SEC)), dispatch_get_main_queue(), ^{
        [[FLMFloatingOverlay shared] attachToActiveWindow];
        StartMainThreadDiagnosticsTimer();
    });
}
