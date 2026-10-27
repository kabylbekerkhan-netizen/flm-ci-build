#pragma once
#import <UIKit/UIKit.h>

@interface FLMHitButton : UIButton
@end

@interface FLMHitSlider : UISlider
@end

@interface FLMFloatingOverlay : NSObject
+ (instancetype)shared;
- (void)attachToActiveWindow;
- (void)showPanelAndSelectTab:(int)tabIndex;
- (void)refreshDiagnosticsStatus;
- (void)onSnapTelemetry;
@end
