#pragma once
#include "../core/DSPModule.h"
#include <atomic>

namespace flm_dsp {

class Mod1_Brutalizer : public DSPModule {
public:
    Mod1_Brutalizer();

    void process(float* left, float* right, int numFrames, float sampleRate) override;
    void reset() override;

    // Lock-free UI parameter setters/getters
    void setSubMix(float norm01)      { subMix_.store(norm01, std::memory_order_relaxed); }
    void setDrive(float norm01)       { drive_.store(norm01, std::memory_order_relaxed); }
    void setCeilingDb(float db)       { ceilingDb_.store(db, std::memory_order_relaxed); }
    void setMonoLow(float norm01)     { monoLow_.store(norm01, std::memory_order_relaxed); }

    float getSubMix() const           { return subMix_.load(std::memory_order_relaxed); }
    float getDrive() const            { return drive_.load(std::memory_order_relaxed); }
    float getCeilingDb() const        { return ceilingDb_.load(std::memory_order_relaxed); }
    float getMonoLow() const          { return monoLow_.load(std::memory_order_relaxed); }

private:
    std::atomic<float> subMix_{0.35f};     // 0.0 .. 1.0 (0..100%)
    std::atomic<float> drive_{0.40f};      // 0.0 .. 1.0 (0..100%)
    std::atomic<float> ceilingDb_{-0.5f};  // -12.0 .. 0.0 dB
    std::atomic<float> monoLow_{1.0f};     // 0.0 .. 1.0 (Mono < 120Hz amount)

    // Sub-octave state (zero-crossing divider + 90Hz 2-pole LPF)
    float trackerLp_{0.0f};
    float prevTracker_{0.0f};
    float envFollow_{0.0f};
    int   flipFlop_{1};
    float subLp1_{0.0f};
    float subLp2_{0.0f};

    // 120Hz Stereo Crossover state
    float lowL_{0.0f};
    float lowR_{0.0f};

    // DC Blocker state after asymmetric diode saturator
    float dcInL_{0.0f}, dcOutL_{0.0f};
    float dcInR_{0.0f}, dcOutR_{0.0f};
};

} // namespace flm_dsp
