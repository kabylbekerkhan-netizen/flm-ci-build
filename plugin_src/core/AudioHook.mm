#import "AudioHook.h"
#import "RackChain.h"
#import "../vendor/fishhook.h"
#import <AudioToolbox/AudioToolbox.h>
#include <atomic>
#include <algorithm>
#include <cmath>
#include <cstring>

namespace flm_dsp {

static constexpr int kMaxFrames = 4096;
static float sScratchL[kMaxFrames];
static float sScratchR[kMaxFrames];

static std::atomic<int>      sHookMode{static_cast<int>(HookMode::MasterOut)};
static std::atomic<bool>     sSafeMode{false};
static std::atomic<bool>     sHookInstalled{false};
static std::atomic<bool>     sAudioActive{false};
static std::atomic<uint64_t> sCallbackCount{0};
static std::atomic<uint32_t> sLastFrames{0};
static std::atomic<float>    sSampleRate{44100.0f};

// ASBD format diagnostics (updated ONLY outside the real-time render callback)
static std::atomic<int>      sFormatKind{static_cast<int>(AudioFormatKind::Unknown)};
static std::atomic<uint32_t> sFormatFlags{0};
static std::atomic<uint32_t> sBitsPerChannel{0};
static std::atomic<uint32_t> sChannelsPerFrame{0};
static std::atomic<bool>     sIsInterleaved{false};

static AURenderCallback sOrigRenderProc = nullptr;

using FnAudioUnitSetProperty  = OSStatus (*)(AudioUnit, AudioUnitPropertyID, AudioUnitScope, AudioUnitElement, const void*, UInt32);
using FnAudioUnitInitialize   = OSStatus (*)(AudioUnit);
using FnAudioOutputUnitStart  = OSStatus (*)(AudioUnit);
using FnAudioUnitRender       = OSStatus (*)(AudioUnit, AudioUnitRenderActionFlags*, const AudioTimeStamp*, UInt32, UInt32, AudioBufferList*);

static FnAudioUnitSetProperty sOrigSetProperty = nullptr;
static FnAudioUnitInitialize  sOrigUnitInit    = nullptr;
static FnAudioOutputUnitStart sOrigUnitStart   = nullptr;
static FnAudioUnitRender      sOrigUnitRender  = nullptr;

static inline float sanitizeAndClampSample(float x) {
    if (!std::isfinite(x)) return 0.0f;
    return std::clamp(x, -1.0f, 1.0f);
}

static void recordASBD(const AudioStreamBasicDescription& asbd) {
    if (asbd.mSampleRate > 8000.0) {
        sSampleRate.store(static_cast<float>(asbd.mSampleRate), std::memory_order_relaxed);
    }
    sFormatFlags.store(asbd.mFormatFlags, std::memory_order_relaxed);
    sBitsPerChannel.store(asbd.mBitsPerChannel, std::memory_order_relaxed);
    sChannelsPerFrame.store(asbd.mChannelsPerFrame, std::memory_order_relaxed);

    const bool isLinearPCM = (asbd.mFormatID == kAudioFormatLinearPCM);
    const bool isFloat = (asbd.mFormatFlags & kAudioFormatFlagIsFloat) != 0;
    const bool isNonInterleaved = (asbd.mFormatFlags & kAudioFormatFlagIsNonInterleaved) != 0;
    sIsInterleaved.store(!isNonInterleaved, std::memory_order_relaxed);

    if (isLinearPCM && isFloat && asbd.mBitsPerChannel == 32) {
        sFormatKind.store(
            static_cast<int>(isNonInterleaved ? AudioFormatKind::Float32Planar : AudioFormatKind::Float32Inter),
            std::memory_order_release
        );
    } else {
        sFormatKind.store(static_cast<int>(AudioFormatKind::Unsupported), std::memory_order_release);
    }
}

// Called ONLY from non-realtime lifecycle hooks (AudioUnitInitialize / AudioOutputUnitStart)
static void queryUnitASBD(AudioUnit unit) {
    if (!unit) return;
    AudioStreamBasicDescription asbd{};
    UInt32 sz = sizeof(asbd);
    if (AudioUnitGetProperty(unit, kAudioUnitProperty_StreamFormat, kAudioUnitScope_Input, 0, &asbd, &sz) == noErr &&
        sz >= sizeof(asbd) && asbd.mSampleRate > 0) {
        recordASBD(asbd);
        return;
    }
    sz = sizeof(asbd);
    if (AudioUnitGetProperty(unit, kAudioUnitProperty_StreamFormat, kAudioUnitScope_Output, 1, &asbd, &sz) == noErr &&
        sz >= sizeof(asbd) && asbd.mSampleRate > 0) {
        recordASBD(asbd);
    }
}

// Strictly real-time safe: ONLY checks atomic sFormatKind flag, no AudioUnitGetProperty, no locks/allocs.
static void processAudioBufferList(AudioBufferList* ioData, UInt32 inNumberFrames) {
    if (!ioData || ioData->mNumberBuffers == 0 || inNumberFrames == 0) return;

    sAudioActive.store(true, std::memory_order_relaxed);
    sLastFrames.store(static_cast<uint32_t>(inNumberFrames), std::memory_order_relaxed);
    sCallbackCount.fetch_add(1, std::memory_order_relaxed);

    const auto kind = static_cast<AudioFormatKind>(sFormatKind.load(std::memory_order_acquire));
    if (kind != AudioFormatKind::Float32Planar && kind != AudioFormatKind::Float32Inter) {
        // Strict passthrough on Unsupported / Unknown format
        return;
    }

    const int frames = std::min(static_cast<int>(inNumberFrames), kMaxFrames);
    const float sr = sSampleRate.load(std::memory_order_relaxed);

    // Case 1: Float32 Non-Interleaved (Planar)
    if (kind == AudioFormatKind::Float32Planar && ioData->mNumberBuffers >= 2 &&
        ioData->mBuffers[0].mData && ioData->mBuffers[1].mData &&
        ioData->mBuffers[0].mDataByteSize >= inNumberFrames * sizeof(float)) {
        float* L = static_cast<float*>(ioData->mBuffers[0].mData);
        float* R = static_cast<float*>(ioData->mBuffers[1].mData);
        for (int i = 0; i < frames; ++i) {
            L[i] = sanitizeAndClampSample(L[i]);
            R[i] = sanitizeAndClampSample(R[i]);
        }
        RackChain::shared().process(L, R, frames, sr);
        for (int i = 0; i < frames; ++i) {
            L[i] = sanitizeAndClampSample(L[i]);
            R[i] = sanitizeAndClampSample(R[i]);
        }
        return;
    }

    // Case 2: Float32 Interleaved (or mono Float32 single buffer)
    AudioBuffer& buf0 = ioData->mBuffers[0];
    if (!buf0.mData) return;
    const UInt32 ch = std::max<UInt32>(1, buf0.mNumberChannels);
    if (buf0.mDataByteSize < inNumberFrames * ch * sizeof(float)) {
        sFormatKind.store(static_cast<int>(AudioFormatKind::Unsupported), std::memory_order_relaxed);
        return;
    }

    float* data = static_cast<float*>(buf0.mData);
    if (ch >= 2) {
        for (int i = 0; i < frames; ++i) {
            sScratchL[i] = sanitizeAndClampSample(data[i * ch]);
            sScratchR[i] = sanitizeAndClampSample(data[i * ch + 1]);
        }
        RackChain::shared().process(sScratchL, sScratchR, frames, sr);
        for (int i = 0; i < frames; ++i) {
            data[i * ch]     = sanitizeAndClampSample(sScratchL[i]);
            data[i * ch + 1] = sanitizeAndClampSample(sScratchR[i]);
        }
    } else {
        for (int i = 0; i < frames; ++i) {
            float v = sanitizeAndClampSample(data[i]);
            sScratchL[i] = v;
            sScratchR[i] = v;
        }
        RackChain::shared().process(sScratchL, sScratchR, frames, sr);
        for (int i = 0; i < frames; ++i) {
            data[i] = sanitizeAndClampSample(0.5f * (sScratchL[i] + sScratchR[i]));
        }
    }
}

static OSStatus CustomMasterRenderCallback(void*                       inRefCon,
                                           AudioUnitRenderActionFlags* ioActionFlags,
                                           const AudioTimeStamp*       inTimeStamp,
                                           UInt32                      inBusNumber,
                                           UInt32                      inNumberFrames,
                                           AudioBufferList*            ioData) {
    if (!sOrigRenderProc) return noErr;
    OSStatus status = sOrigRenderProc(inRefCon, ioActionFlags, inTimeStamp, inBusNumber, inNumberFrames, ioData);
    if (status == noErr && ioData != nullptr && !sSafeMode.load(std::memory_order_relaxed)) {
        if (sHookMode.load(std::memory_order_relaxed) == static_cast<int>(HookMode::MasterOut)) {
            processAudioBufferList(ioData, inNumberFrames);
        }
    }
    return status;
}

static OSStatus Hooked_AudioUnitSetProperty(AudioUnit            inUnit,
                                            AudioUnitPropertyID  inID,
                                            AudioUnitScope       inScope,
                                            AudioUnitElement     inElement,
                                            const void*          inData,
                                            UInt32               inDataSize) {
    if (inID == kAudioUnitProperty_StreamFormat && inData && inDataSize >= sizeof(AudioStreamBasicDescription)) {
        recordASBD(*static_cast<const AudioStreamBasicDescription*>(inData));
    }

    if (inID == kAudioUnitProperty_SetRenderCallback &&
        (inScope == kAudioUnitScope_Input || inScope == kAudioUnitScope_Global) &&
        inElement == 0 && inData && inDataSize >= sizeof(AURenderCallbackStruct)) {
        const auto* cb = static_cast<const AURenderCallbackStruct*>(inData);
        const AURenderCallback customCb = reinterpret_cast<AURenderCallback>(&CustomMasterRenderCallback);
        if (cb->inputProc && cb->inputProc != customCb) {
            sOrigRenderProc = cb->inputProc;
            sHookInstalled.store(true, std::memory_order_relaxed);
            queryUnitASBD(inUnit);

            AURenderCallbackStruct hookedCb;
            hookedCb.inputProc       = customCb;
            hookedCb.inputProcRefCon = cb->inputProcRefCon;
            return sOrigSetProperty(inUnit, inID, inScope, inElement, &hookedCb, sizeof(hookedCb));
        }
    }

    return sOrigSetProperty(inUnit, inID, inScope, inElement, inData, inDataSize);
}

static OSStatus Hooked_AudioUnitInitialize(AudioUnit inUnit) {
    OSStatus status = sOrigUnitInit(inUnit);
    if (status == noErr) {
        queryUnitASBD(inUnit);
    }
    return status;
}

static OSStatus Hooked_AudioOutputUnitStart(AudioUnit unit) {
    queryUnitASBD(unit);
    sAudioActive.store(true, std::memory_order_relaxed);
    return sOrigUnitStart(unit);
}

static OSStatus Hooked_AudioUnitRender(AudioUnit                   inUnit,
                                       AudioUnitRenderActionFlags* ioActionFlags,
                                       const AudioTimeStamp*       inTimeStamp,
                                       UInt32                      inOutputBusNumber,
                                       UInt32                      inNumberFrames,
                                       AudioBufferList*            ioData) {
    OSStatus status = sOrigUnitRender(inUnit, ioActionFlags, inTimeStamp, inOutputBusNumber, inNumberFrames, ioData);
    if (status == noErr && inOutputBusNumber == 1 && ioData != nullptr && !sSafeMode.load(std::memory_order_relaxed)) {
        sHookInstalled.store(true, std::memory_order_relaxed);
        if (sHookMode.load(std::memory_order_relaxed) == static_cast<int>(HookMode::MicIn)) {
            processAudioBufferList(ioData, inNumberFrames);
        }
    }
    return status;
}

void AudioHook::install() {
    if (sSafeMode.load(std::memory_order_relaxed)) return;
    struct rebinding bindings[] = {
        {"AudioUnitSetProperty", reinterpret_cast<void*>(Hooked_AudioUnitSetProperty), reinterpret_cast<void**>(&sOrigSetProperty)},
        {"AudioUnitInitialize",  reinterpret_cast<void*>(Hooked_AudioUnitInitialize),  reinterpret_cast<void**>(&sOrigUnitInit)},
        {"AudioOutputUnitStart", reinterpret_cast<void*>(Hooked_AudioOutputUnitStart), reinterpret_cast<void**>(&sOrigUnitStart)},
        {"AudioUnitRender",      reinterpret_cast<void*>(Hooked_AudioUnitRender),      reinterpret_cast<void**>(&sOrigUnitRender)},
    };
    if (rebind_symbols(bindings, sizeof(bindings) / sizeof(bindings[0])) == 0) {
        sHookInstalled.store(true, std::memory_order_relaxed);
    }
}

void AudioHook::setMode(HookMode mode)        { sHookMode.store(static_cast<int>(mode), std::memory_order_relaxed); }
HookMode AudioHook::getMode()                 { return static_cast<HookMode>(sHookMode.load(std::memory_order_relaxed)); }
void AudioHook::setSafeMode(bool safe)        { sSafeMode.store(safe, std::memory_order_relaxed); }
bool AudioHook::isSafeMode()                  { return sSafeMode.load(std::memory_order_relaxed); }
bool AudioHook::isHookInstalled()             { return sHookInstalled.load(std::memory_order_relaxed); }
bool AudioHook::isAudioActive()               { return sAudioActive.load(std::memory_order_relaxed); }
uint64_t AudioHook::callbackCount()           { return sCallbackCount.load(std::memory_order_relaxed); }
uint32_t AudioHook::lastFrames()              { return sLastFrames.load(std::memory_order_relaxed); }
float AudioHook::currentSampleRate()          { return sSampleRate.load(std::memory_order_relaxed); }
AudioFormatKind AudioHook::formatKind()       { return static_cast<AudioFormatKind>(sFormatKind.load(std::memory_order_relaxed)); }
uint32_t AudioHook::formatFlags()             { return sFormatFlags.load(std::memory_order_relaxed); }
uint32_t AudioHook::bitsPerChannel()          { return sBitsPerChannel.load(std::memory_order_relaxed); }
uint32_t AudioHook::channelsPerFrame()        { return sBitsPerChannel.load(std::memory_order_relaxed) ? sChannelsPerFrame.load(std::memory_order_relaxed) : 0; }
bool AudioHook::isInterleaved()               { return sIsInterleaved.load(std::memory_order_relaxed); }

} // namespace flm_dsp
