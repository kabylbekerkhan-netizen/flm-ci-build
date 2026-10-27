#pragma once
#include "../core/DSPModule.h"

namespace flm_dsp {
// Stage 3 stub: Halftime (1/2x), Reverse, Tape Stop, Stutter
class Mod3_TimeGlitch : public DSPModule {
public:
    void process(float* left, float* right, int numFrames, float sampleRate) override {
        (void)left; (void)right; (void)numFrames; (void)sampleRate;
    }
};
} // namespace flm_dsp
