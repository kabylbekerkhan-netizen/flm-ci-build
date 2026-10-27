#pragma once
#include <atomic>

namespace flm_dsp {

class DSPModule {
public:
    virtual ~DSPModule() = default;
    virtual void process(float* left, float* right, int numFrames, float sampleRate) = 0;
    virtual void reset() {}

    void setEnabled(bool on) { enabled_.store(on, std::memory_order_relaxed); }
    bool isEnabled() const { return enabled_.load(std::memory_order_relaxed); }

protected:
    std::atomic<bool> enabled_{true};
};

} // namespace flm_dsp
