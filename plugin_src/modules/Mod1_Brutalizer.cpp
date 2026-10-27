#include "Mod1_Brutalizer.h"
#include <cmath>
#include <algorithm>

namespace flm_dsp {

static constexpr float kPi = 3.14159265358979323846f;

Mod1_Brutalizer::Mod1_Brutalizer() {
    reset();
}

void Mod1_Brutalizer::reset() {
    trackerLp_ = 0.0f;
    prevTracker_ = 0.0f;
    envFollow_ = 0.0f;
    flipFlop_ = 1;
    subLp1_ = 0.0f;
    subLp2_ = 0.0f;
    lowL_ = 0.0f;
    lowR_ = 0.0f;
    dcInL_ = dcOutL_ = 0.0f;
    dcInR_ = dcOutR_ = 0.0f;
}

static inline float asymmetricDiode(float x, float driveGain) {
    float v = x * driveGain;
    // Asymmetric silicon/germanium transfer curve (even + odd harmonics)
    float out;
    if (v >= 0.0f) {
        out = std::tanh(v * 1.35f);
    } else {
        float nv = -v;
        out = -(nv / (1.0f + 0.85f * nv + 0.25f * nv * nv));
    }
    return out;
}

void Mod1_Brutalizer::process(float* left, float* right, int numFrames, float sampleRate) {
    if (!isEnabled() || !left || !right || numFrames <= 0) return;

    const float sr = (sampleRate > 8000.0f) ? sampleRate : 44100.0f;
    const float subMix = std::clamp(subMix_.load(std::memory_order_relaxed), 0.0f, 1.0f);
    const float driveNorm = std::clamp(drive_.load(std::memory_order_relaxed), 0.0f, 1.0f);
    const float ceilingDb = std::clamp(ceilingDb_.load(std::memory_order_relaxed), -12.0f, 0.0f);
    const float monoAmt = std::clamp(monoLow_.load(std::memory_order_relaxed), 0.0f, 1.0f);

    // Filter coefficients
    const float alphaTrack = 1.0f - std::exp(-2.0f * kPi * 160.0f / sr); // Pre-filter for clean zero-crossings
    const float alphaSub90 = 1.0f - std::exp(-2.0f * kPi * 90.0f / sr);  // 90 Hz LPF for sub-octave fundamental
    const float alpha120   = 1.0f - std::exp(-2.0f * kPi * 120.0f / sr); // 120 Hz crossover for Mono Maker
    const float envAtk     = 1.0f - std::exp(-1.0f / (0.003f * sr));
    const float envRel     = 1.0f - std::exp(-1.0f / (0.045f * sr));

    const float driveGain  = 1.0f + driveNorm * 7.5f;
    const float makeup     = 1.0f / (1.0f + driveNorm * 0.45f);
    const float ceilingLin = std::pow(10.0f, ceilingDb / 20.0f);

    for (int i = 0; i < numFrames; ++i) {
        float inL = left[i];
        float inR = right[i];
        float monoIn = 0.5f * (inL + inR);

        // 1. Sub-Octave Generator (-12 semitones via zero-crossing flip-flop + 90Hz 2-pole LPF)
        trackerLp_ += alphaTrack * (monoIn - trackerLp_);
        if (prevTracker_ <= 0.0f && trackerLp_ > 0.0f) {
            flipFlop_ = -flipFlop_;
        }
        prevTracker_ = trackerLp_;

        float absIn = std::fabs(trackerLp_);
        float envCoeff = (absIn > envFollow_) ? envAtk : envRel;
        envFollow_ += envCoeff * (absIn - envFollow_);

        float rawSub = static_cast<float>(flipFlop_) * envFollow_ * 1.4f;
        subLp1_ += alphaSub90 * (rawSub - subLp1_);
        subLp2_ += alphaSub90 * (subLp1_ - subLp2_);

        float sigL = inL + subLp2_ * subMix;
        float sigR = inR + subLp2_ * subMix;

        // 2. Low-End Mono Maker (crossover < 120Hz summed to mono, highs stay stereo)
        lowL_ += alpha120 * (sigL - lowL_);
        lowR_ += alpha120 * (sigR - lowR_);
        float highL = sigL - lowL_;
        float highR = sigR - lowR_;
        float lowMono = 0.5f * (lowL_ + lowR_);
        sigL = highL + (lowL_ * (1.0f - monoAmt) + lowMono * monoAmt);
        sigR = highR + (lowR_ * (1.0f - monoAmt) + lowMono * monoAmt);

        // 3. Asymmetric Diode Drive + DC blocker
        if (driveNorm > 0.001f) {
            float satL = asymmetricDiode(sigL, driveGain) * makeup;
            float satR = asymmetricDiode(sigR, driveGain) * makeup;

            // High-pass DC blocker (~15 Hz)
            float dcL = satL - dcInL_ + 0.9975f * dcOutL_;
            dcInL_ = satL;
            dcOutL_ = dcL;

            float dcR = satR - dcInR_ + 0.9975f * dcOutR_;
            dcInR_ = satR;
            dcOutR_ = dcR;

            sigL = sigL * (1.0f - driveNorm) + dcL * driveNorm;
            sigR = sigR * (1.0f - driveNorm) + dcR * driveNorm;
        }

        // 4. Hard Clipper (Ceiling -12..0 dB) with NaN/Inf sanitization & +-1.0 safety limiter
        if (!std::isfinite(sigL)) sigL = 0.0f;
        if (!std::isfinite(sigR)) sigR = 0.0f;
        sigL = std::clamp(sigL, -ceilingLin, ceilingLin);
        sigR = std::clamp(sigR, -ceilingLin, ceilingLin);

        left[i]  = std::clamp(sigL, -1.0f, 1.0f);
        right[i] = std::clamp(sigR, -1.0f, 1.0f);
    }
}

} // namespace flm_dsp
