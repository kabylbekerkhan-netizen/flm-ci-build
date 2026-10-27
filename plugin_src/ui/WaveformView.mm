#import "WaveformView.h"
#import "../core/RackChain.h"
#import <QuartzCore/QuartzCore.h>
#include <cmath>
#include <algorithm>

@implementation FLMWaveformView {
    CADisplayLink* _displayLink;
    float _samples[256];
}

- (instancetype)initWithFrame:(CGRect)frame {
    if ((self = [super initWithFrame:frame])) {
        self.backgroundColor = [UIColor colorWithRed:0x08/255.0 green:0x08/255.0 blue:0x08/255.0 alpha:1.0];
        self.layer.cornerRadius = 6.0;
        self.layer.borderWidth = 1.0;
        self.layer.borderColor = [UIColor colorWithRed:0x6B/255.0 green:0x0F/255.0 blue:0x1A/255.0 alpha:0.85].CGColor;
        self.clipsToBounds = YES;
    }
    return self;
}

- (void)startDisplayLink {
    if (_displayLink) return;
    _displayLink = [CADisplayLink displayLinkWithTarget:self selector:@selector(onTick)];
    if (@available(iOS 15.0, *)) {
        _displayLink.preferredFrameRateRange = CAFrameRateRangeMake(30, 60, 60);
    } else {
        _displayLink.preferredFramesPerSecond = 60;
    }
    [_displayLink addToRunLoop:[NSRunLoop mainRunLoop] forMode:NSRunLoopCommonModes];
}

- (void)stopDisplayLink {
    [_displayLink invalidate];
    _displayLink = nil;
}

- (void)onTick {
    flm_dsp::RackChain::shared().copyScopeSamples(_samples, 256);
    [self setNeedsDisplay];
}

- (void)drawRect:(CGRect)rect {
    CGContextRef ctx = UIGraphicsGetCurrentContext();
    if (!ctx) return;

    const CGFloat w = rect.size.width;
    const CGFloat h = rect.size.height;
    const CGFloat midY = h * 0.5;

    // Background fill (#080808)
    CGContextSetRGBFillColor(ctx, 0x08/255.0, 0x08/255.0, 0x08/255.0, 1.0);
    CGContextFillRect(ctx, rect);

    // Center zero line
    CGContextSetRGBStrokeColor(ctx, 0xD4/255.0, 0xD4/255.0, 0xD8/255.0, 0.15);
    CGContextSetLineWidth(ctx, 1.0);
    CGContextMoveToPoint(ctx, 0, midY);
    CGContextAddLineToPoint(ctx, w, midY);
    CGContextStrokePath(ctx);

    // Draw Hard Clipper ceiling lines (#8A1222)
    float ceilDb = flm_dsp::RackChain::shared().brutalizer().getCeilingDb();
    float ceilLin = std::pow(10.0f, ceilDb / 20.0f);
    CGFloat ceilOffset = (CGFloat)std::clamp(ceilLin, 0.05f, 1.0f) * (h * 0.45);
    CGFloat dashLengths[2] = {4.0, 3.0};
    CGContextSaveGState(ctx);
    CGContextSetRGBStrokeColor(ctx, 0x8A/255.0, 0x12/255.0, 0x22/255.0, 0.75);
    CGContextSetLineDash(ctx, 0, dashLengths, 2);
    CGContextMoveToPoint(ctx, 0, midY - ceilOffset);
    CGContextAddLineToPoint(ctx, w, midY - ceilOffset);
    CGContextMoveToPoint(ctx, 0, midY + ceilOffset);
    CGContextAddLineToPoint(ctx, w, midY + ceilOffset);
    CGContextStrokePath(ctx);
    CGContextRestoreGState(ctx);

    // Oxblood filled waveform under glow + Chrome main waveform line
    CGMutablePathRef wavePath = CGPathCreateMutable();
    for (int i = 0; i < 256; ++i) {
        CGFloat x = (CGFloat)i / 255.0 * w;
        CGFloat s = (CGFloat)std::clamp(_samples[i], -1.0f, 1.0f);
        CGFloat y = midY - s * (h * 0.45);
        if (i == 0) {
            CGPathMoveToPoint(wavePath, NULL, x, y);
        } else {
            CGPathAddLineToPoint(wavePath, NULL, x, y);
        }
    }

    // Oxblood outer glow stroke (#8A1222)
    CGContextAddPath(ctx, wavePath);
    CGContextSetRGBStrokeColor(ctx, 0x8A/255.0, 0x12/255.0, 0x22/255.0, 0.85);
    CGContextSetLineWidth(ctx, 3.0);
    CGContextStrokePath(ctx);

    // Cold Chrome crisp inner stroke (#E4E4E7)
    CGContextAddPath(ctx, wavePath);
    CGContextSetRGBStrokeColor(ctx, 0xE4/255.0, 0xE4/255.0, 0xE7/255.0, 0.95);
    CGContextSetLineWidth(ctx, 1.25);
    CGContextStrokePath(ctx);

    CGPathRelease(wavePath);
}

- (void)dealloc {
    [self stopDisplayLink];
}

@end
