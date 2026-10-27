#pragma once
#include "../core/DSPModule.h"

namespace flm_dsp {
// Stage 5 stub: Live WAV Stem Recorder & AUv3 Host
class Mod5_AUv3Rec : public DSPModule {
public:
    void process(float* left, float* right, int numFrames, float sampleRate) override {
        (void)left; (void)right; (void)numFrames; (void)sampleRate;
    }
};
} // namespace flm_dsp
