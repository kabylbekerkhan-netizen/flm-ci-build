#pragma once
#include "../core/DSPModule.h"

namespace flm_dsp {
// Stage 4 stub: Wow/Flutter Tape, Bitcrusher, Dark Shimmer Freeze
class Mod4_LoFiSpace : public DSPModule {
public:
    void process(float* left, float* right, int numFrames, float sampleRate) override {
        (void)left; (void)right; (void)numFrames; (void)sampleRate;
    }
};
} // namespace flm_dsp
