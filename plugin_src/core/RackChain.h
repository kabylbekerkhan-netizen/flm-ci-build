#pragma once
#include "DSPModule.h"
#include "../modules/Mod1_Brutalizer.h"
#include "../modules/Mod2_VocalTune.h"
#include "../modules/Mod3_TimeGlitch.h"
#include "../modules/Mod4_LoFiSpace.h"
#include "../modules/Mod5_AUv3Rec.h"
#include <atomic>
#include <cstdint>

namespace flm_dsp {

class RackChain {
public:
    static constexpr int kNumModules = 5;
    static constexpr int kScopeSize = 512;

    static RackChain& shared();

    RackChain();

    void process(float* left, float* right, int numFrames, float sampleRate);

    void setMasterBypass(bool bypass) { masterBypass_.store(bypass, std::memory_order_relaxed); }
    bool isMasterBypassed() const     { return masterBypass_.load(std::memory_order_relaxed); }

    Mod1_Brutalizer& brutalizer() { return mod1_; }
    Mod2_VocalTune&  vocalTune()  { return mod2_; }
    Mod3_TimeGlitch& timeGlitch() { return mod3_; }
    Mod4_LoFiSpace&  lofiSpace()  { return mod4_; }
    Mod5_AUv3Rec&    auv3Rec()    { return mod5_; }

    DSPModule* moduleAt(int index) {
        return (index >= 0 && index < kNumModules) ? modules_[index] : nullptr;
    }

    // Lock-free snapshot of recent audio waveform for UI oscilloscope
    void copyScopeSamples(float* dst, int count) const;

private:
    std::atomic<bool> masterBypass_{false};

    Mod1_Brutalizer mod1_;
    Mod2_VocalTune  mod2_;
    Mod3_TimeGlitch mod3_;
    Mod4_LoFiSpace  mod4_;
    Mod5_AUv3Rec    mod5_;
    DSPModule* modules_[kNumModules];

    float scopeRing_[kScopeSize]{};
    std::atomic<uint32_t> scopeWriteIdx_{0};
};

} // namespace flm_dsp
