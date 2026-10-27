#include "RackChain.h"
#include <algorithm>
#include <cstring>

namespace flm_dsp {

RackChain& RackChain::shared() {
    static RackChain instance;
    return instance;
}

RackChain::RackChain() {
    modules_[0] = &mod1_;
    modules_[1] = &mod2_;
    modules_[2] = &mod3_;
    modules_[3] = &mod4_;
    modules_[4] = &mod5_;
}

void RackChain::process(float* left, float* right, int numFrames, float sampleRate) {
    if (!left || !right || numFrames <= 0) return;

    if (!masterBypass_.load(std::memory_order_relaxed)) {
        for (int m = 0; m < kNumModules; ++m) {
            if (modules_[m]->isEnabled()) {
                modules_[m]->process(left, right, numFrames, sampleRate);
            }
        }
    }

    // Push mono sum into lock-free ring buffer for 60 FPS UI oscilloscope
    uint32_t w = scopeWriteIdx_.load(std::memory_order_relaxed);
    for (int i = 0; i < numFrames; ++i) {
        scopeRing_[w & (kScopeSize - 1)] = 0.5f * (left[i] + right[i]);
        ++w;
    }
    scopeWriteIdx_.store(w, std::memory_order_release);
}

void RackChain::copyScopeSamples(float* dst, int count) const {
    if (!dst || count <= 0) return;
    int n = std::min(count, kScopeSize);
    uint32_t w = scopeWriteIdx_.load(std::memory_order_acquire);
    uint32_t start = w - static_cast<uint32_t>(n);
    for (int i = 0; i < n; ++i) {
        dst[i] = scopeRing_[(start + i) & (kScopeSize - 1)];
    }
}

} // namespace flm_dsp
