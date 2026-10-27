#pragma once
#include "../core/DSPModule.h"

namespace flm_dsp {
// Stage 2 stub: Low-latency Auto-Tune & Formant Shifter
class Mod2_VocalTune : public DSPModule {
public:
    void process(float* left, float* right, int numFrames, float sampleRate) override {
        (void)left; (void)right; (void)numFrames; (void)sampleRate;
    }
};
} // namespace flm_dsp
