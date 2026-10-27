#import <UIKit/UIKit.h>
#import "../ui/FloatingOverlay.h"
#import "../core/RackChain.h"
#include <cmath>

@interface FLMSimAppDelegate : UIResponder <UIApplicationDelegate>
@property (strong, nonatomic) UIWindow* window;
@end

@implementation FLMSimAppDelegate

- (BOOL)application:(UIApplication*)application didFinishLaunchingWithOptions:(NSDictionary*)launchOptions {
    (void)application; (void)launchOptions;

    CGRect bounds = [UIScreen mainScreen].bounds;
    self.window = [[UIWindow alloc] initWithFrame:bounds];
    UIViewController* rootVC = [[UIViewController alloc] init];
    rootVC.view.backgroundColor = [UIColor colorWithRed:0x12/255.0 green:0x13/255.0 blue:0x18/255.0 alpha:1.0];
    self.window.rootViewController = rootVC;
    [self.window makeKeyAndVisible];

    // Feed real Mod1_Brutalizer DSP test signal into RackChain scope buffer
    float L[512], R[512];
    auto& rack = flm_dsp::RackChain::shared();
    rack.brutalizer().setSubMix(0.45f);
    rack.brutalizer().setDrive(0.55f);
    rack.brutalizer().setCeilingDb(-2.0f);
    for (int b = 0; b < 4; ++b) {
        for (int i = 0; i < 512; ++i) {
            float t = (float)(b * 512 + i) / 44100.0f;
            float sig = 0.9f * std::sin(2.0f * 3.14159265f * 55.0f * t) + 0.35f * std::sin(2.0f * 3.14159265f * 110.0f * t);
            L[i] = sig;
            R[i] = sig;
        }
        rack.process(L, R, 512, 44100.0f);
    }

    [[FLMFloatingOverlay shared] attachToActiveWindow];

    // Cycle through tabs and save native UIKit renders + keep Tab 1 open for simctl screenshot
    NSString* outDir = [[[NSProcessInfo processInfo] environment] objectForKey:@"SIM_SCREENSHOT_DIR"];
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(0.6 * NSEC_PER_SEC)), dispatch_get_main_queue(), ^{
        for (int tab = 0; tab < 5; ++tab) {
            [[FLMFloatingOverlay shared] showPanelAndSelectTab:tab];
            [self.window layoutIfNeeded];
            if (outDir.length > 0) {
                UIGraphicsImageRenderer* r = [[UIGraphicsImageRenderer alloc] initWithBounds:self.window.bounds];
                UIImage* img = [r imageWithActions:^(__unused UIGraphicsImageRendererContext* ctx) {
                    [self.window drawViewHierarchyInRect:self.window.bounds afterScreenUpdates:YES];
                }];
                NSString* p = [outDir stringByAppendingPathComponent:[NSString stringWithFormat:@"native_tab_%d.png", tab + 1]];
                [UIImagePNGRepresentation(img) writeToFile:p atomically:YES];
            }
        }
        // Leave Tab 0 (808 Brutalizer & Hard Clipper) visible for `xcrun simctl io booted screenshot`
        [[FLMFloatingOverlay shared] showPanelAndSelectTab:0];
        [[FLMFloatingOverlay shared] onSnapTelemetry];
    });

    return YES;
}

@end

int main(int argc, char* argv[]) {
    @autoreleasepool {
        return UIApplicationMain(argc, argv, nil, NSStringFromClass([FLMSimAppDelegate class]));
    }
}
