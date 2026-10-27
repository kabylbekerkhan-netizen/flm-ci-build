#import "FloatingOverlay.h"
#import "WaveformView.h"
#import "../core/RackChain.h"
#import "../core/AudioHook.h"
#import <QuartzCore/QuartzCore.h>

static UIColor* ColorBlackBg()    { return [UIColor colorWithRed:0x08/255.0 green:0x08/255.0 blue:0x08/255.0 alpha:0.96]; }
static UIColor* ColorPanelBg()    { return [UIColor colorWithRed:0x12/255.0 green:0x12/255.0 blue:0x14/255.0 alpha:1.0]; }
static UIColor* ColorOxblood()    { return [UIColor colorWithRed:0x6B/255.0 green:0x0F/255.0 blue:0x1A/255.0 alpha:1.0]; }
static UIColor* ColorOxbloodHi()  { return [UIColor colorWithRed:0x8A/255.0 green:0x12/255.0 blue:0x22/255.0 alpha:1.0]; }
static UIColor* ColorSafeModeRed(){ return [UIColor colorWithRed:0xE1/255.0 green:0x1D/255.0 blue:0x48/255.0 alpha:1.0]; }
static UIColor* ColorChrome()     { return [UIColor colorWithRed:0xD4/255.0 green:0xD4/255.0 blue:0xD8/255.0 alpha:1.0]; }
static UIColor* ColorChromeText() { return [UIColor colorWithRed:0xE4/255.0 green:0xE4/255.0 blue:0xE7/255.0 alpha:1.0]; }

static CGRect ExpandedHitBounds(CGRect bounds) {
    CGFloat dx = MIN(0.0, (bounds.size.width - 44.0) * 0.5);
    CGFloat dy = MIN(0.0, (bounds.size.height - 44.0) * 0.5);
    return CGRectInset(bounds, dx, dy);
}

@implementation FLMHitButton
- (BOOL)pointInside:(CGPoint)point withEvent:(UIEvent*)event {
    (void)event;
    return CGRectContainsPoint(ExpandedHitBounds(self.bounds), point);
}
@end

@implementation FLMHitSlider
- (BOOL)pointInside:(CGPoint)point withEvent:(UIEvent*)event {
    (void)event;
    return CGRectContainsPoint(ExpandedHitBounds(self.bounds), point);
}
@end

@implementation FLMFloatingOverlay {
    __weak UIWindow* _attachedWindow;
    FLMHitButton*    _floatingBtn;
    UIView*          _statusDot;
    UIView*          _mainPanel;
    FLMWaveformView* _waveformView;
    UILabel*         _diagLabel;

    FLMHitButton*    _modeBtn;
    FLMHitButton*    _snapBtn;
    FLMHitButton*    _bypassBtn;
    NSMutableArray<FLMHitButton*>* _tabButtons;

    UIView*          _mod1Container;
    UIView*          _mod2Container;
    UIView*          _stubContainer;
    UILabel*         _stubLabel;

    UILabel*         _valLabels[4];
    FLMHitSlider*    _sliders[4];

    UILabel*         _mod2ValLabels[4];
    FLMHitSlider*    _mod2Sliders[4];
}

+ (instancetype)shared {
    static FLMFloatingOverlay* sInstance = nil;
    static dispatch_once_t onceToken;
    dispatch_once(&onceToken, ^{
        sInstance = [[FLMFloatingOverlay alloc] init];
    });
    return sInstance;
}

- (UIWindow*)findKeyWindow {
    for (UIScene* scene in [UIApplication sharedApplication].connectedScenes) {
        if (scene.activationState == UISceneActivationStateForegroundActive &&
            [scene isKindOfClass:[UIWindowScene class]]) {
            UIWindowScene* ws = (UIWindowScene*)scene;
            for (UIWindow* w in ws.windows) {
                if (w.isKeyWindow) return w;
            }
            if (ws.windows.count > 0) return ws.windows.firstObject;
        }
    }
    return [UIApplication sharedApplication].windows.firstObject;
}

- (CGPoint)clampCenter:(CGPoint)center forSize:(CGSize)size inWindow:(UIWindow*)win {
    if (!win) return center;
    UIEdgeInsets safe = win.safeAreaInsets;
    CGRect b = win.bounds;
    CGFloat minX = safe.left + 8.0 + size.width * 0.5;
    CGFloat maxX = b.size.width - safe.right - 8.0 - size.width * 0.5;
    CGFloat minY = safe.top + 8.0 + size.height * 0.5;
    CGFloat maxY = b.size.height - safe.bottom - 8.0 - size.height * 0.5;
    return CGPointMake(MAX(minX, MIN(maxX, center.x)), MAX(minY, MIN(maxY, center.y)));
}

- (void)attachToActiveWindow {
    dispatch_async(dispatch_get_main_queue(), ^{
        UIWindow* win = [self findKeyWindow];
        if (!win) return;
        if (self->_floatingBtn && self->_floatingBtn.superview == win) {
            [win bringSubviewToFront:self->_floatingBtn];
            if (self->_mainPanel && !self->_mainPanel.hidden) {
                [win bringSubviewToFront:self->_mainPanel];
            }
            [self refreshDiagnosticsStatus];
            return;
        }
        self->_attachedWindow = win;
        [self buildFloatingButtonInWindow:win];
        [self buildMainPanelInWindow:win];
        [self refreshDiagnosticsStatus];
    });
}

- (void)buildFloatingButtonInWindow:(UIWindow*)win {
    if (_floatingBtn) [_floatingBtn removeFromSuperview];

    UIEdgeInsets safe = win.safeAreaInsets;
    CGFloat startX = MAX(safe.left + 12.0, 68.0);
    CGFloat startY = MAX(safe.top + 12.0, 56.0);

    _floatingBtn = [FLMHitButton buttonWithType:UIButtonTypeCustom];
    _floatingBtn.frame = CGRectMake(startX, startY, 44.0, 44.0);
    _floatingBtn.accessibilityIdentifier = @"floatingDSPButton";
    _floatingBtn.backgroundColor = [UIColor colorWithRed:0x08/255.0 green:0x08/255.0 blue:0x08/255.0 alpha:0.9];
    _floatingBtn.layer.cornerRadius = 22.0;
    _floatingBtn.layer.borderWidth = 1.2;
    _floatingBtn.layer.borderColor = ColorChrome().CGColor;
    [_floatingBtn setTitle:@"DSP" forState:UIControlStateNormal];
    [_floatingBtn setTitleColor:ColorChromeText() forState:UIControlStateNormal];
    _floatingBtn.titleLabel.font = [UIFont boldSystemFontOfSize:11.0];

    _statusDot = [[UIView alloc] initWithFrame:CGRectMake(31.0, 5.0, 8.0, 8.0)];
    _statusDot.backgroundColor = ColorOxbloodHi();
    _statusDot.layer.cornerRadius = 4.0;
    _statusDot.userInteractionEnabled = NO;
    [_floatingBtn addSubview:_statusDot];

    [_floatingBtn addTarget:self action:@selector(toggleMainPanel) forControlEvents:UIControlEventTouchUpInside];

    UIPanGestureRecognizer* pan = [[UIPanGestureRecognizer alloc] initWithTarget:self action:@selector(onDragFloatingButton:)];
    [_floatingBtn addGestureRecognizer:pan];

    [win addSubview:_floatingBtn];
}

- (void)buildMainPanelInWindow:(UIWindow*)win {
    if (_mainPanel) [_mainPanel removeFromSuperview];

    CGSize winSize = win.bounds.size;
    CGFloat pw = 520.0;
    CGFloat ph = 336.0;
    CGRect frame = CGRectMake((winSize.width - pw) * 0.5, (winSize.height - ph) * 0.5, pw, ph);

    _mainPanel = [[UIView alloc] initWithFrame:frame];
    _mainPanel.center = [self clampCenter:_mainPanel.center forSize:frame.size inWindow:win];
    _mainPanel.accessibilityIdentifier = @"mainDSPPanel";
    _mainPanel.backgroundColor = ColorBlackBg();
    _mainPanel.layer.cornerRadius = 14.0;
    _mainPanel.layer.borderWidth = 1.2;
    _mainPanel.layer.borderColor = [ColorChrome() colorWithAlphaComponent:0.45].CGColor;
    _mainPanel.hidden = YES;

    // Header Bar (height 60pt, draggable + long-press telemetry snapshot)
    UIView* header = [[UIView alloc] initWithFrame:CGRectMake(10, 8, pw - 20, 60)];
    header.accessibilityIdentifier = @"headerBar";
    header.backgroundColor = ColorPanelBg();
    header.layer.cornerRadius = 8.0;
    UIPanGestureRecognizer* headerPan = [[UIPanGestureRecognizer alloc] initWithTarget:self action:@selector(onDragPanel:)];
    [header addGestureRecognizer:headerPan];
    UILongPressGestureRecognizer* headerLongPress = [[UILongPressGestureRecognizer alloc] initWithTarget:self action:@selector(onHeaderLongPress:)];
    [header addGestureRecognizer:headerLongPress];
    [_mainPanel addSubview:header];

    // Title
    UILabel* titleLbl = [[UILabel alloc] initWithFrame:CGRectMake(8, 3, 132, 14)];
    titleLbl.text = @"FLM // DSP RACK";
    titleLbl.textColor = ColorChromeText();
    titleLbl.font = [UIFont boldSystemFontOfSize:10.5];
    [header addSubview:titleLbl];

    // Mode Toggle: MASTER OUT | MIC IN (visual 32pt, hit-area 44pt)
    _modeBtn = [FLMHitButton buttonWithType:UIButtonTypeCustom];
    _modeBtn.frame = CGRectMake(8, 20, 132, 32);
    _modeBtn.backgroundColor = ColorOxblood();
    _modeBtn.layer.cornerRadius = 6.0;
    _modeBtn.layer.borderWidth = 0.9;
    _modeBtn.layer.borderColor = ColorChrome().CGColor;
    _modeBtn.titleLabel.font = [UIFont boldSystemFontOfSize:9.5];
    [_modeBtn setTitle:@"MODE: MASTER OUT" forState:UIControlStateNormal];
    [_modeBtn setTitleColor:ColorChromeText() forState:UIControlStateNormal];
    [_modeBtn addTarget:self action:@selector(onToggleMode) forControlEvents:UIControlEventTouchUpInside];
    [header addSubview:_modeBtn];

    // Live Oscilloscope WaveformView (60 FPS)
    _waveformView = [[FLMWaveformView alloc] initWithFrame:CGRectMake(146, 4, 178, 36)];
    [header addSubview:_waveformView];

    // Live Diagnostics Status Line (HOOK: OFF/OK | cb=N | frames=N | SR=... | FMT:...)
    _diagLabel = [[UILabel alloc] initWithFrame:CGRectMake(146, 43, 346, 14)];
    _diagLabel.accessibilityIdentifier = @"diagStatusLabel";
    _diagLabel.text = @"HOOK: OFF | cb=0 | frames=0 | SR=44100 | FMT:WAIT";
    _diagLabel.textColor = ColorChrome();
    _diagLabel.font = [UIFont monospacedDigitSystemFontOfSize:8.5 weight:UIFontWeightSemibold];
    [header addSubview:_diagLabel];

    // Wi-Fi Telemetry SNAP button (visual 48x32pt, hit-area 48x44pt)
    _snapBtn = [FLMHitButton buttonWithType:UIButtonTypeCustom];
    _snapBtn.frame = CGRectMake(330, 8, 48, 32);
    _snapBtn.backgroundColor = [UIColor colorWithRed:0x1C/255.0 green:0x1C/255.0 blue:0x20/255.0 alpha:1.0];
    _snapBtn.layer.cornerRadius = 6.0;
    _snapBtn.layer.borderWidth = 0.8;
    _snapBtn.layer.borderColor = [ColorChrome() colorWithAlphaComponent:0.65].CGColor;
    _snapBtn.titleLabel.font = [UIFont boldSystemFontOfSize:9.5];
    [_snapBtn setTitle:@"SNAP" forState:UIControlStateNormal];
    [_snapBtn setTitleColor:ColorChromeText() forState:UIControlStateNormal];
    [_snapBtn addTarget:self action:@selector(onSnapTelemetry) forControlEvents:UIControlEventTouchUpInside];
    [header addSubview:_snapBtn];

    // Global BYPASS button (visual 56x32pt, hit-area 56x44pt)
    _bypassBtn = [FLMHitButton buttonWithType:UIButtonTypeCustom];
    _bypassBtn.frame = CGRectMake(384, 8, 56, 32);
    _bypassBtn.backgroundColor = ColorOxbloodHi();
    _bypassBtn.layer.cornerRadius = 6.0;
    _bypassBtn.layer.borderWidth = 0.9;
    _bypassBtn.layer.borderColor = ColorChrome().CGColor;
    _bypassBtn.titleLabel.font = [UIFont boldSystemFontOfSize:9.5];
    [_bypassBtn setTitle:@"ACTIVE" forState:UIControlStateNormal];
    [_bypassBtn setTitleColor:ColorChromeText() forState:UIControlStateNormal];
    [_bypassBtn addTarget:self action:@selector(onToggleBypass) forControlEvents:UIControlEventTouchUpInside];
    [header addSubview:_bypassBtn];

    // Close button (visual 46x32pt, hit-area 46x44pt)
    FLMHitButton* closeBtn = [FLMHitButton buttonWithType:UIButtonTypeCustom];
    closeBtn.frame = CGRectMake(446, 8, 46, 32);
    closeBtn.backgroundColor = [UIColor colorWithWhite:0.18 alpha:1.0];
    closeBtn.layer.cornerRadius = 6.0;
    closeBtn.layer.borderWidth = 0.8;
    closeBtn.layer.borderColor = [ColorChrome() colorWithAlphaComponent:0.45].CGColor;
    closeBtn.titleLabel.font = [UIFont boldSystemFontOfSize:9.5];
    [closeBtn setTitle:@"HIDE" forState:UIControlStateNormal];
    [closeBtn setTitleColor:ColorChrome() forState:UIControlStateNormal];
    [closeBtn addTarget:self action:@selector(toggleMainPanel) forControlEvents:UIControlEventTouchUpInside];
    [header addSubview:closeBtn];

    // 5-Tab Selector Bar (visual height 32pt, hit-area height 44pt)
    NSArray<NSString*>* tabNames = @[@"1. 808/CLIP", @"2. VOCAL TUNE", @"3. HALFTIME", @"4. LO-FI/SPACE", @"5. AUv3/REC"];
    _tabButtons = [NSMutableArray arrayWithCapacity:5];
    CGFloat tabW = (pw - 20.0 - 16.0) / 5.0;
    for (int i = 0; i < 5; ++i) {
        FLMHitButton* tb = [FLMHitButton buttonWithType:UIButtonTypeCustom];
        tb.frame = CGRectMake(10.0 + i * (tabW + 4.0), 74.0, tabW, 32.0);
        tb.tag = i;
        tb.layer.cornerRadius = 6.0;
        tb.layer.borderWidth = 0.9;
        tb.titleLabel.font = [UIFont boldSystemFontOfSize:9.5];
        [tb setTitle:tabNames[i] forState:UIControlStateNormal];
        [tb setTitleColor:ColorChromeText() forState:UIControlStateNormal];
        [tb addTarget:self action:@selector(onSelectTab:) forControlEvents:UIControlEventTouchUpInside];
        [_mainPanel addSubview:tb];
        [_tabButtons addObject:tb];
    }

    // Module 1 Container (808 Brutalizer & Hard Clipper)
    _mod1Container = [[UIView alloc] initWithFrame:CGRectMake(10, 112, pw - 20, ph - 122)];
    _mod1Container.accessibilityIdentifier = @"mod1Container";
    _mod1Container.backgroundColor = ColorPanelBg();
    _mod1Container.layer.cornerRadius = 10.0;
    _mod1Container.layer.borderWidth = 0.9;
    _mod1Container.layer.borderColor = [ColorOxbloodHi() colorWithAlphaComponent:0.65].CGColor;
    [_mainPanel addSubview:_mod1Container];

    [self buildMod1Controls];

    // Module 2 Container (Low-Latency Auto-Tune & Formant Shifter)
    _mod2Container = [[UIView alloc] initWithFrame:_mod1Container.frame];
    _mod2Container.accessibilityIdentifier = @"mod2Container";
    _mod2Container.backgroundColor = ColorPanelBg();
    _mod2Container.layer.cornerRadius = 10.0;
    _mod2Container.layer.borderWidth = 0.9;
    _mod2Container.layer.borderColor = [ColorOxbloodHi() colorWithAlphaComponent:0.65].CGColor;
    _mod2Container.hidden = YES;
    [_mainPanel addSubview:_mod2Container];

    [self buildMod2Controls];

    // Stub Container for Tabs 3..5
    _stubContainer = [[UIView alloc] initWithFrame:_mod1Container.frame];
    _stubContainer.backgroundColor = ColorPanelBg();
    _stubContainer.layer.cornerRadius = 10.0;
    _stubContainer.hidden = YES;

    _stubLabel = [[UILabel alloc] initWithFrame:_stubContainer.bounds];
    _stubLabel.textAlignment = NSTextAlignmentCenter;
    _stubLabel.textColor = ColorChrome();
    _stubLabel.font = [UIFont boldSystemFontOfSize:12.0];
    _stubLabel.numberOfLines = 2;
    [_stubContainer addSubview:_stubLabel];
    [_mainPanel addSubview:_stubContainer];

    [self updateTabSelection:0];
    [win addSubview:_mainPanel];
}

- (void)buildMod1Controls {
    NSArray<NSString*>* titles = @[
        @"SUB-OCTAVE MIX (-12 ST / 90Hz)",
        @"ASYMMETRIC DIODE DRIVE",
        @"HARD CLIPPER CEILING (dB)",
        @"LOW-END MONO MAKER (< 120Hz)"
    ];
    auto& mod1 = flm_dsp::RackChain::shared().brutalizer();
    float initVals[4] = {
        mod1.getSubMix(),
        mod1.getDrive(),
        mod1.getCeilingDb(),
        mod1.getMonoLow()
    };
    float minVals[4] = {0.0f, 0.0f, -12.0f, 0.0f};
    float maxVals[4] = {1.0f, 1.0f,   0.0f, 1.0f};

    CGFloat cw = _mod1Container.bounds.size.width;
    for (int i = 0; i < 4; ++i) {
        CGFloat y = 8.0 + i * 51.0;

        UILabel* nameLbl = [[UILabel alloc] initWithFrame:CGRectMake(14, y, 290, 15)];
        nameLbl.text = titles[i];
        nameLbl.textColor = ColorChromeText();
        nameLbl.font = [UIFont boldSystemFontOfSize:10.5];
        [_mod1Container addSubview:nameLbl];

        UILabel* valLbl = [[UILabel alloc] initWithFrame:CGRectMake(cw - 114, y, 100, 15)];
        valLbl.textAlignment = NSTextAlignmentRight;
        valLbl.textColor = ColorChrome();
        valLbl.font = [UIFont monospacedDigitSystemFontOfSize:11.0 weight:UIFontWeightBold];
        [_mod1Container addSubview:valLbl];
        _valLabels[i] = valLbl;

        FLMHitSlider* sld = [[FLMHitSlider alloc] initWithFrame:CGRectMake(14, y + 16, cw - 28, 32)];
        sld.tag = i;
        sld.minimumValue = minVals[i];
        sld.maximumValue = maxVals[i];
        sld.value = initVals[i];
        sld.minimumTrackTintColor = ColorOxbloodHi();
        sld.maximumTrackTintColor = [UIColor colorWithWhite:0.22 alpha:1.0];
        sld.thumbTintColor = ColorChromeText();
        [sld addTarget:self action:@selector(onSliderChanged:) forControlEvents:UIControlEventValueChanged];
        [_mod1Container addSubview:sld];
        _sliders[i] = sld;

        [self updateValueLabelForIndex:i value:initVals[i]];
    }
}

- (void)buildMod2Controls {
    NSArray<NSString*>* titles = @[
        @"RETUNE SPEED (0ms = HARD TUNE)",
        @"FORMANT SHIFT (THROAT -12..+12 ST)",
        @"KEY & SCALE QUANTIZER",
        @"VOCAL TUNE DRY / WET MIX"
    ];
    auto& mod2 = flm_dsp::RackChain::shared().vocalTune();
    float initVals[4] = {
        mod2.getRetuneSpeedMs(),
        mod2.getFormantSemitones(),
        static_cast<float>(mod2.getScalePreset()),
        mod2.getMix()
    };
    float minVals[4] = {  0.0f, -12.0f,  0.0f, 0.0f};
    float maxVals[4] = {150.0f,  12.0f, 24.0f, 1.0f};

    CGFloat cw = _mod2Container.bounds.size.width;
    for (int i = 0; i < 4; ++i) {
        CGFloat y = 8.0 + i * 51.0;

        UILabel* nameLbl = [[UILabel alloc] initWithFrame:CGRectMake(14, y, 270, 15)];
        nameLbl.text = titles[i];
        nameLbl.textColor = ColorChromeText();
        nameLbl.font = [UIFont boldSystemFontOfSize:10.5];
        [_mod2Container addSubview:nameLbl];

        UILabel* valLbl = [[UILabel alloc] initWithFrame:CGRectMake(cw - 134, y, 120, 15)];
        valLbl.textAlignment = NSTextAlignmentRight;
        valLbl.textColor = ColorChrome();
        valLbl.font = [UIFont monospacedDigitSystemFontOfSize:10.5 weight:UIFontWeightBold];
        [_mod2Container addSubview:valLbl];
        _mod2ValLabels[i] = valLbl;

        FLMHitSlider* sld = [[FLMHitSlider alloc] initWithFrame:CGRectMake(14, y + 16, cw - 28, 32)];
        sld.tag = i;
        sld.minimumValue = minVals[i];
        sld.maximumValue = maxVals[i];
        sld.value = initVals[i];
        sld.minimumTrackTintColor = ColorOxbloodHi();
        sld.maximumTrackTintColor = [UIColor colorWithWhite:0.22 alpha:1.0];
        sld.thumbTintColor = ColorChromeText();
        [sld addTarget:self action:@selector(onMod2SliderChanged:) forControlEvents:UIControlEventValueChanged];
        [_mod2Container addSubview:sld];
        _mod2Sliders[i] = sld;

        [self updateMod2ValueLabelForIndex:i value:initVals[i]];
    }
}

- (void)refreshDiagnosticsStatus {
    bool safe = flm_dsp::AudioHook::isSafeMode();
    bool hooked = flm_dsp::AudioHook::isHookInstalled();
    uint64_t cb = flm_dsp::AudioHook::callbackCount();
    uint32_t fr = flm_dsp::AudioHook::lastFrames();
    float sr = flm_dsp::AudioHook::currentSampleRate();
    auto fkind = flm_dsp::AudioHook::formatKind();

    const char* fmtStr = "WAIT";
    if (fkind == flm_dsp::AudioFormatKind::Float32Planar) fmtStr = "F32P";
    else if (fkind == flm_dsp::AudioFormatKind::Float32Inter) fmtStr = "F32I";
    else if (fkind == flm_dsp::AudioFormatKind::Unsupported) fmtStr = "UNSUPPORTED";

    if (safe) {
        if (_diagLabel) {
            _diagLabel.text = @"SAFE MODE // HOOK: OFF | crash-guard active (boot>=3)";
            _diagLabel.textColor = ColorSafeModeRed();
        }
        if (_floatingBtn) {
            [_floatingBtn setTitle:@"SAFE" forState:UIControlStateNormal];
            _floatingBtn.layer.borderColor = ColorSafeModeRed().CGColor;
        }
        if (_statusDot) _statusDot.backgroundColor = ColorSafeModeRed();
    } else if (_diagLabel) {
        _diagLabel.text = [NSString stringWithFormat:@"HOOK:%s | cb=%llu | frames=%u | SR=%.0f | FMT:%s",
                           hooked ? "OK" : "OFF",
                           (unsigned long long)cb,
                           (unsigned int)fr,
                           sr,
                           fmtStr];
        if (fkind == flm_dsp::AudioFormatKind::Unsupported) {
            _diagLabel.textColor = ColorSafeModeRed();
        } else {
            _diagLabel.textColor = hooked ? ColorChromeText() : ColorChrome();
        }
    }
    if (_mod2Container && !_mod2Container.hidden && _mod2Sliders[2]) {
        [self updateMod2ValueLabelForIndex:2 value:_mod2Sliders[2].value];
    }
}

- (void)updateValueLabelForIndex:(int)idx value:(float)val {
    if (idx == 2) {
        _valLabels[idx].text = [NSString stringWithFormat:@"%.1f dB", val];
    } else {
        _valLabels[idx].text = [NSString stringWithFormat:@"%.0f %%", val * 100.0f];
    }
}

- (void)onSliderChanged:(UISlider*)sender {
    int idx = (int)sender.tag;
    float v = sender.value;
    auto& mod1 = flm_dsp::RackChain::shared().brutalizer();
    switch (idx) {
        case 0: mod1.setSubMix(v);    break;
        case 1: mod1.setDrive(v);     break;
        case 2: mod1.setCeilingDb(v); break;
        case 3: mod1.setMonoLow(v);   break;
        default: break;
    }
    [self updateValueLabelForIndex:idx value:v];
}

- (void)updateMod2ValueLabelForIndex:(int)idx value:(float)val {
    if (idx == 0) {
        _mod2ValLabels[0].text = [NSString stringWithFormat:@"%.0f ms", val];
    } else if (idx == 1) {
        _mod2ValLabels[1].text = [NSString stringWithFormat:@"%+.1f ST", val];
    } else if (idx == 2) {
        int preset = (int)lroundf(val);
        auto& mod2 = flm_dsp::RackChain::shared().vocalTune();
        int det = mod2.getDetectedMidiNote();
        int cor = mod2.getCorrectedMidiNote();
        const char* scName = flm_dsp::Mod2_VocalTune::scalePresetName(preset);
        if (det >= 0 && cor >= 0) {
            _mod2ValLabels[2].text = [NSString stringWithFormat:@"%s [%s>%s]",
                                      scName,
                                      flm_dsp::Mod2_VocalTune::midiNoteName(det),
                                      flm_dsp::Mod2_VocalTune::midiNoteName(cor)];
        } else {
            _mod2ValLabels[2].text = [NSString stringWithUTF8String:scName];
        }
    } else if (idx == 3) {
        _mod2ValLabels[3].text = [NSString stringWithFormat:@"%.0f %%", val * 100.0f];
    }
}

- (void)onMod2SliderChanged:(UISlider*)sender {
    int idx = (int)sender.tag;
    float v = sender.value;
    auto& mod2 = flm_dsp::RackChain::shared().vocalTune();
    switch (idx) {
        case 0: mod2.setRetuneSpeedMs(v); break;
        case 1: mod2.setFormantSemitones(v); break;
        case 2: {
            int preset = (int)lroundf(v);
            sender.value = (float)preset;
            v = (float)preset;
            mod2.setScalePreset(preset);
            break;
        }
        case 3: mod2.setMix(v); break;
        default: break;
    }
    [self updateMod2ValueLabelForIndex:idx value:v];
}

- (void)onSelectTab:(UIButton*)sender {
    [self updateTabSelection:(int)sender.tag];
}

- (void)updateTabSelection:(int)selectedIdx {
    for (int i = 0; i < (int)_tabButtons.count; ++i) {
        UIButton* b = _tabButtons[i];
        if (i == selectedIdx) {
            b.backgroundColor = ColorOxbloodHi();
            b.layer.borderColor = ColorChromeText().CGColor;
        } else {
            b.backgroundColor = ColorPanelBg();
            b.layer.borderColor = [ColorChrome() colorWithAlphaComponent:0.3].CGColor;
        }
    }
    if (selectedIdx == 0) {
        _mod1Container.hidden = NO;
        _mod2Container.hidden = YES;
        _stubContainer.hidden = YES;
    } else if (selectedIdx == 1) {
        _mod1Container.hidden = YES;
        _mod2Container.hidden = NO;
        _stubContainer.hidden = YES;
    } else {
        _mod1Container.hidden = YES;
        _mod2Container.hidden = YES;
        _stubContainer.hidden = NO;
        _stubLabel.text = [NSString stringWithFormat:@"MODULE %d // PASS-THROUGH STUB\n(Scheduled for Stage %d)", selectedIdx + 1, selectedIdx + 1];
    }
}

- (void)onToggleMode {
    auto cur = flm_dsp::AudioHook::getMode();
    auto next = (cur == flm_dsp::HookMode::MasterOut) ? flm_dsp::HookMode::MicIn : flm_dsp::HookMode::MasterOut;
    flm_dsp::AudioHook::setMode(next);
    if (next == flm_dsp::HookMode::MasterOut) {
        [_modeBtn setTitle:@"MODE: MASTER OUT" forState:UIControlStateNormal];
        _modeBtn.backgroundColor = ColorOxblood();
    } else {
        [_modeBtn setTitle:@"MODE: MIC IN" forState:UIControlStateNormal];
        _modeBtn.backgroundColor = ColorOxbloodHi();
    }
    [self refreshDiagnosticsStatus];
}

- (void)onToggleBypass {
    bool bypassed = !flm_dsp::RackChain::shared().isMasterBypassed();
    flm_dsp::RackChain::shared().setMasterBypass(bypassed);
    if (bypassed) {
        [_bypassBtn setTitle:@"BYPASSED" forState:UIControlStateNormal];
        _bypassBtn.backgroundColor = [UIColor colorWithWhite:0.22 alpha:1.0];
        _statusDot.backgroundColor = [UIColor grayColor];
    } else {
        [_bypassBtn setTitle:@"ACTIVE" forState:UIControlStateNormal];
        _bypassBtn.backgroundColor = ColorOxbloodHi();
        _statusDot.backgroundColor = ColorOxbloodHi();
    }
}

- (void)toggleMainPanel {
    if (!_mainPanel) return;
    BOOL show = _mainPanel.hidden;
    _mainPanel.hidden = !show;
    if (show) {
        _mainPanel.center = [self clampCenter:_mainPanel.center forSize:_mainPanel.bounds.size inWindow:_attachedWindow];
        [_attachedWindow bringSubviewToFront:_mainPanel];
        [_attachedWindow bringSubviewToFront:_floatingBtn];
        [_waveformView startDisplayLink];
        [self refreshDiagnosticsStatus];
    } else {
        [_waveformView stopDisplayLink];
    }
}

- (void)showPanelAndSelectTab:(int)tabIndex {
    if (!_mainPanel) return;
    _mainPanel.hidden = NO;
    _mainPanel.center = [self clampCenter:_mainPanel.center forSize:_mainPanel.bounds.size inWindow:_attachedWindow];
    [_attachedWindow bringSubviewToFront:_mainPanel];
    [_attachedWindow bringSubviewToFront:_floatingBtn];
    [_waveformView startDisplayLink];
    [self updateTabSelection:tabIndex];
    [self refreshDiagnosticsStatus];
}

- (void)onHeaderLongPress:(UILongPressGestureRecognizer*)lp {
    if (lp.state == UIGestureRecognizerStateBegan) {
        [self onSnapTelemetry];
    }
}

- (CGRect)effectiveHitFrameForView:(UIView*)view {
    if ([view isKindOfClass:[UIControl class]]) {
        CGRect hb = ExpandedHitBounds(view.bounds);
        return [view convertRect:hb toView:view.superview];
    }
    return view.frame;
}

- (void)collectViewMetrics:(UIView*)view intoArray:(NSMutableArray*)arr inWindow:(UIWindow*)win {
    if (!view || view.hidden || view.alpha < 0.01) return;
    CGRect f = view.frame;
    CGRect hitFrame = [self effectiveHitFrameForView:view];
    CGRect screenRect = [view convertRect:view.bounds toView:win];

    BOOL touchTooSmall = NO;
    if ([view isKindOfClass:[UIControl class]]) {
        touchTooSmall = (hitFrame.size.width < 44.0 - 0.1 || hitFrame.size.height < 44.0 - 0.1);
    }

    BOOL overlapsSibling = NO;
    if (view.superview && [view isKindOfClass:[UIControl class]]) {
        for (UIView* sib in view.superview.subviews) {
            if (sib == view || sib.hidden || sib.alpha < 0.01) continue;
            if (![sib isKindOfClass:[UIControl class]]) continue;
            CGRect sibHit = [self effectiveHitFrameForView:sib];
            if (CGRectIntersectsRect(hitFrame, sibHit)) {
                overlapsSibling = YES;
                break;
            }
        }
    }

    BOOL isClipped = NO;
    if (view.superview && !CGRectContainsRect(view.superview.bounds, f)) {
        isClipped = YES;
    }
    NSString* labelText = @"";
    if ([view isKindOfClass:[UILabel class]]) {
        UILabel* lbl = (UILabel*)view;
        labelText = lbl.text ?: @"";
        CGSize fit = [lbl sizeThatFits:CGSizeMake(CGFLOAT_MAX, f.size.height)];
        if (fit.width > f.size.width + 2.0) isClipped = YES;
    } else if ([view isKindOfClass:[UIButton class]]) {
        UIButton* btn = (UIButton*)view;
        labelText = [btn titleForState:UIControlStateNormal] ?: @"";
    }

    [arr addObject:@{
        @"class": NSStringFromClass([view class]),
        @"id": view.accessibilityIdentifier ?: @"",
        @"text": labelText,
        @"frame": @[@(f.origin.x), @(f.origin.y), @(f.size.width), @(f.size.height)],
        @"hitFrame": @[@(hitFrame.origin.x), @(hitFrame.origin.y), @(hitFrame.size.width), @(hitFrame.size.height)],
        @"screenFrame": @[@(screenRect.origin.x), @(screenRect.origin.y), @(screenRect.size.width), @(screenRect.size.height)],
        @"isClipped": @(isClipped),
        @"touchTargetTooSmall": @(touchTooSmall),
        @"overlapsSibling": @(overlapsSibling)
    }];

    for (UIView* sub in view.subviews) {
        [self collectViewMetrics:sub intoArray:arr inWindow:win];
    }
}

- (void)onSnapTelemetry {
    UIWindow* win = _attachedWindow ?: [self findKeyWindow];
    if (!win) return;

    UIGraphicsImageRenderer* renderer = [[UIGraphicsImageRenderer alloc] initWithBounds:win.bounds];
    UIImage* image = [renderer imageWithActions:^(__unused UIGraphicsImageRendererContext* ctx) {
        [win drawViewHierarchyInRect:win.bounds afterScreenUpdates:YES];
    }];
    NSData* pngData = UIImagePNGRepresentation(image);
    if (!pngData) return;

    NSMutableArray* viewsDump = [NSMutableArray array];
    [self collectViewMetrics:_floatingBtn intoArray:viewsDump inWindow:win];
    [self collectViewMetrics:_mainPanel intoArray:viewsDump inWindow:win];

    UIEdgeInsets safe = win.safeAreaInsets;
    NSDictionary* payload = @{
        @"device": [[UIDevice currentDevice] name] ?: @"iOS",
        @"screen": @[@(win.bounds.size.width), @(win.bounds.size.height)],
        @"safeAreaInsets": @[@(safe.top), @(safe.left), @(safe.bottom), @(safe.right)],
        @"timestamp": @([[NSDate date] timeIntervalSince1970]),
        @"views": viewsDump,
        @"png_base64": [pngData base64EncodedStringWithOptions:0]
    };

    NSError* err = nil;
    NSData* jsonData = [NSJSONSerialization dataWithJSONObject:payload options:0 error:&err];
    if (!jsonData) return;

    NSString* docs = NSSearchPathForDirectoriesInDomains(NSDocumentDirectory, NSUserDomainMask, YES).firstObject;
    if (docs) {
        [pngData writeToFile:[docs stringByAppendingPathComponent:@"ui_snap_latest.png"] atomically:YES];
        [jsonData writeToFile:[docs stringByAppendingPathComponent:@"ui_snap_latest.json"] atomically:YES];
    }

    NSString* host = [[NSUserDefaults standardUserDefaults] stringForKey:@"FLM_TelemetryHost"];
    if (!host || host.length == 0) host = @"127.0.0.1";
    NSString* urlStr = [NSString stringWithFormat:@"http://%@:8765/snap", host];
    NSURL* url = [NSURL URLWithString:urlStr];
    if (!url) return;

    NSMutableURLRequest* req = [NSMutableURLRequest requestWithURL:url];
    req.HTTPMethod = @"POST";
    [req setValue:@"application/json" forHTTPHeaderField:@"Content-Type"];
    req.HTTPBody = jsonData;

    [_snapBtn setTitle:@"..." forState:UIControlStateNormal];
    NSURLSessionDataTask* task = [[NSURLSession sharedSession] dataTaskWithRequest:req
        completionHandler:^(__unused NSData* data, NSURLResponse* resp, NSError* netErr) {
            dispatch_async(dispatch_get_main_queue(), ^{
                NSHTTPURLResponse* httpResp = (NSHTTPURLResponse*)resp;
                BOOL ok = (!netErr && httpResp.statusCode == 200);
                [self->_snapBtn setTitle:(ok ? @"OK" : @"SAVED") forState:UIControlStateNormal];
                dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(1.2 * NSEC_PER_SEC)), dispatch_get_main_queue(), ^{
                    [self->_snapBtn setTitle:@"SNAP" forState:UIControlStateNormal];
                });
            });
        }];
    [task resume];
}

- (void)onDragFloatingButton:(UIPanGestureRecognizer*)pan {
    UIView* v = pan.view;
    if (!v || !v.superview) return;
    CGPoint delta = [pan translationInView:v.superview];
    CGPoint target = CGPointMake(v.center.x + delta.x, v.center.y + delta.y);
    v.center = [self clampCenter:target forSize:v.bounds.size inWindow:_attachedWindow];
    [pan setTranslation:CGPointZero inView:v.superview];
}

- (void)onDragPanel:(UIPanGestureRecognizer*)pan {
    if (!_mainPanel || !_mainPanel.superview) return;
    CGPoint delta = [pan translationInView:_mainPanel.superview];
    CGPoint target = CGPointMake(_mainPanel.center.x + delta.x, _mainPanel.center.y + delta.y);
    _mainPanel.center = [self clampCenter:target forSize:_mainPanel.bounds.size inWindow:_attachedWindow];
    [pan setTranslation:CGPointZero inView:_mainPanel.superview];
}

@end
