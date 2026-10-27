#pragma once
#include "../core/DSPModule.h"
#include <atomic>
#include <cstdint>

namespace flm_dsp {

class Mod2_VocalTune final : public DSPModule {
public:
    static constexpr int kDelaySize = 4096;
    static constexpr int kDelayMask = kDelaySize - 1;
    static constexpr int kAnalysisSize = 1024;
    static constexpr int kAnalysisMask = kAnalysisSize - 1;
    static constexpr int kHopSize = 128;

    Mod2_VocalTune();
    ~Mod2_VocalTune() override = default;

    const char* name() const override { return "2. VOCAL TUNE"; }
    void process(float* left, float* right, int numFrames, float sampleRate) override;

    // Parameters (Thread-safe atomic setters/getters for UI)
    void  setRetuneSpeedMs(float ms);
    float getRetuneSpeedMs() const { return retuneSpeedMs_.load(std::memory_order_relaxed); }

    void  setFormantSemitones(float st);
    float getFormantSemitones() const { return formantSemitones_.load(std::memory_order_relaxed); }

    // 0..11: C..B Minor, 12..23: C..B Major, 24: Chromatic
    void  setScalePreset(int preset);
    int   getScalePreset() const { return scalePreset_.load(std::memory_order_relaxed); }

    void  setMix(float mix01);
    float getMix() const { return mix_.load(std::memory_order_relaxed); }

    int   getDetectedMidiNote() const { return detectedNote_.load(std::memory_order_relaxed); }
    int   getCorrectedMidiNote() const { return correctedNote_.load(std::memory_order_relaxed); }

    static const char* scalePresetName(int preset);
    static const char* midiNoteName(int midiNote);

private:
    float detectPitchHz(float sampleRate) const;
    static float quantizeMidiNote(float fracMidi, int scalePreset);

    std::atomic<float> retuneSpeedMs_{12.0f};     // 0 .. 200 ms (0 = Hard Tune)
    std::atomic<float> formantSemitones_{0.0f};   // -12 .. +12 ST
    std::atomic<int>   scalePreset_{0};           // 0 = C Minor
    std::atomic<float> mix_{0.0f};                // 0.0 .. 1.0 Dry/Wet

    std::atomic<int>   detectedNote_{-1};
    std::atomic<int>   correctedNote_{-1};

    // Real-time DSP state (owned exclusively by audio render thread)
    float delayL_[kDelaySize]{};
    float delayR_[kDelaySize]{};
    int   writePos_{0};

    float analysisRing_[kAnalysisSize]{};
    int   analysisWritePos_{0};
    int   hopCounter_{0};

    float targetRatio_{1.0f};
    float smoothRatio_{1.0f};
    float grainPhase_{0.0f};
    float formantPhase_{0.0f};

    // State-variable formant filter states (L/R)
    float svfLowL_{0.0f}, svfBandL_{0.0f};
    float svfLowR_{0.0f}, svfBandR_{0.0f};
};

} // namespace flm_dsp
