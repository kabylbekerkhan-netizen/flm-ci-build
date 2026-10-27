#include "Mod2_VocalTune.h"
#include <algorithm>
#include <cmath>

#if defined(__APPLE__)
#include <Accelerate/Accelerate.h>
#endif

namespace flm_dsp {

namespace {
constexpr float kTwoPi = 6.28318530717958647692f;
constexpr float kGrainSize = 1024.0f;

// 12-note scale masks (1 = allowed degree relative to root)
constexpr int kMinorScaleMask[12] = {1, 0, 1, 1, 0, 1, 0, 1, 1, 0, 1, 0};
constexpr int kMajorScaleMask[12] = {1, 0, 1, 0, 1, 1, 0, 1, 0, 1, 0, 1};

const char* const kScaleNames[25] = {
    "C MIN",  "C# MIN", "D MIN",  "D# MIN", "E MIN",  "F MIN",
    "F# MIN", "G MIN",  "G# MIN", "A MIN",  "A# MIN", "B MIN",
    "C MAJ",  "C# MAJ", "D MAJ",  "D# MAJ", "E MAJ",  "F MAJ",
    "F# MAJ", "G MAJ",  "G# MAJ", "A MAJ",  "A# MAJ", "B MAJ",
    "CHROMATIC"
};

const char* const kNoteNames[12] = {
    "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"
};

inline float sanitizeSample(float x) {
    if (!std::isfinite(x)) return 0.0f;
    return std::clamp(x, -1.0f, 1.0f);
}

inline float readDelayCubic(const float* buf, int writePos, float delaySamples) {
    float readPos = static_cast<float>(writePos) - delaySamples;
    while (readPos < 0.0f) readPos += static_cast<float>(Mod2_VocalTune::kDelaySize);
    int idx1 = static_cast<int>(readPos) & Mod2_VocalTune::kDelayMask;
    int idx2 = (idx1 + 1) & Mod2_VocalTune::kDelayMask;
    float frac = readPos - std::floor(readPos);
    return buf[idx1] + frac * (buf[idx2] - buf[idx1]);
}
} // namespace

Mod2_VocalTune::Mod2_VocalTune() = default;

void Mod2_VocalTune::setRetuneSpeedMs(float ms) {
    retuneSpeedMs_.store(std::clamp(ms, 0.0f, 200.0f), std::memory_order_relaxed);
}

void Mod2_VocalTune::setFormantSemitones(float st) {
    formantSemitones_.store(std::clamp(st, -12.0f, 12.0f), std::memory_order_relaxed);
}

void Mod2_VocalTune::setScalePreset(int preset) {
    scalePreset_.store(std::clamp(preset, 0, 24), std::memory_order_relaxed);
}

void Mod2_VocalTune::setMix(float mix01) {
    mix_.store(std::clamp(mix01, 0.0f, 1.0f), std::memory_order_relaxed);
}

const char* Mod2_VocalTune::scalePresetName(int preset) {
    int idx = std::clamp(preset, 0, 24);
    return kScaleNames[idx];
}

const char* Mod2_VocalTune::midiNoteName(int midiNote) {
    if (midiNote < 0 || midiNote > 127) return "--";
    return kNoteNames[midiNote % 12];
}

float Mod2_VocalTune::quantizeMidiNote(float fracMidi, int scalePreset) {
    if (scalePreset >= 24) {
        return std::round(fracMidi);
    }
    int root = scalePreset % 12;
    const int* mask = (scalePreset < 12) ? kMinorScaleMask : kMajorScaleMask;

    int baseMidi = static_cast<int>(std::round(fracMidi));
    float bestNote = static_cast<float>(baseMidi);
    float bestDist = 999.0f;

    for (int offset = -6; offset <= 6; ++offset) {
        int cand = baseMidi + offset;
        int deg = ((cand - root) % 12 + 12) % 12;
        if (mask[deg]) {
            float dist = std::fabs(static_cast<float>(cand) - fracMidi);
            if (dist < bestDist) {
                bestDist = dist;
                bestNote = static_cast<float>(cand);
            }
        }
    }
    return bestNote;
}

float Mod2_VocalTune::detectPitchHz(float sampleRate) const {
    constexpr int W = 512;
    float frame[kAnalysisSize];
    for (int i = 0; i < kAnalysisSize; ++i) {
        frame[i] = analysisRing_[(analysisWritePos_ + i) & kAnalysisMask];
    }

    float energy = 0.0f;
#if defined(__APPLE__)
    vDSP_dotpr(frame, 1, frame, 1, &energy, W);
#else
    for (int i = 0; i < W; ++i) energy += frame[i] * frame[i];
#endif
    float rms = std::sqrt(energy / static_cast<float>(W));
    if (rms < 0.005f) {
        return 0.0f;
    }

    int tauMin = std::max(24, static_cast<int>(sampleRate / 800.0f));
    int tauMax = std::min(W - 2, static_cast<int>(sampleRate / 75.0f));
    if (tauMin >= tauMax) return 0.0f;

    float diff[W]{};
    float cmndf[W]{};
    cmndf[0] = 1.0f;
    float runningSum = 0.0f;

    for (int tau = 1; tau <= tauMax; ++tau) {
        float d = 0.0f;
#if defined(__APPLE__)
        vDSP_distancesq(frame, 1, frame + tau, 1, &d, W);
#else
        for (int j = 0; j < W; ++j) {
            float delta = frame[j] - frame[j + tau];
            d += delta * delta;
        }
#endif
        diff[tau] = d;
        runningSum += d;
        cmndf[tau] = (runningSum > 1e-9f) ? (d * static_cast<float>(tau) / runningSum) : 1.0f;
    }

    constexpr float kYinThreshold = 0.18f;
    int bestTau = -1;
    for (int tau = tauMin; tau < tauMax; ++tau) {
        if (cmndf[tau] < kYinThreshold) {
            while (tau + 1 < tauMax && cmndf[tau + 1] < cmndf[tau]) {
                ++tau;
            }
            bestTau = tau;
            break;
        }
    }

    if (bestTau < 0) {
        float minVal = 1.0f;
        for (int tau = tauMin; tau < tauMax; ++tau) {
            if (cmndf[tau] < minVal) {
                minVal = cmndf[tau];
                bestTau = tau;
            }
        }
        if (minVal > 0.35f) return 0.0f;
    }

    float refinedTau = static_cast<float>(bestTau);
    if (bestTau > tauMin && bestTau < tauMax - 1) {
        float y0 = cmndf[bestTau - 1];
        float y1 = cmndf[bestTau];
        float y2 = cmndf[bestTau + 1];
        float denom = 2.0f * (2.0f * y1 - y2 - y0);
        if (std::fabs(denom) > 1e-6f) {
            refinedTau += (y2 - y0) / denom;
        }
    }

    return (refinedTau > 1.0f) ? (sampleRate / refinedTau) : 0.0f;
}

void Mod2_VocalTune::process(float* left, float* right, int numFrames, float sampleRate) {
    if (!left || !right || numFrames <= 0) return;

    const float wetMix = mix_.load(std::memory_order_relaxed);
    if (wetMix <= 0.001f) {
        return; // Zero-cost bypass when mix is 0%
    }

    const float sr = (sampleRate > 8000.0f) ? sampleRate : 48000.0f;
    const float retuneMs = retuneSpeedMs_.load(std::memory_order_relaxed);
    const float formantSt = formantSemitones_.load(std::memory_order_relaxed);
    const int   preset = scalePreset_.load(std::memory_order_relaxed);

    const float tauSec = std::max(0.0008f, retuneMs * 0.001f);
    const float glideAlpha = 1.0f - std::exp(-1.0f / (tauSec * sr));

    const float formantRatio = std::pow(2.0f, formantSt / 12.0f);
    const float svfCutoffHz = std::clamp(1100.0f * formantRatio, 250.0f, 4200.0f);
    const float svfF = std::clamp(2.0f * std::sin(3.14159265f * svfCutoffHz / sr), 0.02f, 0.75f);
    const float svfQ = 0.65f;
    const float formantAmt = std::clamp( std::fabs(formantSt) / 12.0f, 0.0f, 1.0f );

    for (int i = 0; i < numFrames; ++i) {
        const float inL = left[i];
        const float inR = right[i];
        const float mono = 0.5f * (inL + inR);

        analysisRing_[analysisWritePos_] = mono;
        analysisWritePos_ = (analysisWritePos_ + 1) & kAnalysisMask;

        if (++hopCounter_ >= kHopSize) {
            hopCounter_ = 0;
            float f0 = detectPitchHz(sr);
            if (f0 >= 75.0f && f0 <= 800.0f) {
                float fracMidi = 69.0f + 12.0f * std::log2(f0 / 440.0f);
                float snappedMidi = quantizeMidiNote(fracMidi, preset);
                detectedNote_.store(static_cast<int>(std::round(fracMidi)), std::memory_order_relaxed);
                correctedNote_.store(static_cast<int>(std::round(snappedMidi)), std::memory_order_relaxed);
                float diffSt = std::clamp(snappedMidi - fracMidi, -12.0f, 12.0f);
                targetRatio_ = std::pow(2.0f, diffSt / 12.0f);
            } else {
                detectedNote_.store(-1, std::memory_order_relaxed);
                correctedNote_.store(-1, std::memory_order_relaxed);
                targetRatio_ = 1.0f;
            }
        }

        smoothRatio_ += glideAlpha * (targetRatio_ - smoothRatio_);

        delayL_[writePos_] = inL;
        delayR_[writePos_] = inR;

        // Dual-grain Hann window overlap-add pitch shifter
        const float rateDelta = (1.0f - smoothRatio_) / kGrainSize;
        grainPhase_ += rateDelta;
        if (grainPhase_ >= 1.0f) grainPhase_ -= std::floor(grainPhase_);
        if (grainPhase_ < 0.0f)  grainPhase_ += 1.0f - std::floor(grainPhase_);

        const float phA = grainPhase_;
        const float phB = (phA + 0.5f >= 1.0f) ? (phA - 0.5f) : (phA + 0.5f);

        const float winA = 0.5f * (1.0f - std::cos(kTwoPi * phA));
        const float winB = 0.5f * (1.0f - std::cos(kTwoPi * phB));

        const float dA = phA * kGrainSize + 2.0f;
        const float dB = phB * kGrainSize + 2.0f;

        float pitchedL = winA * readDelayCubic(delayL_, writePos_, dA) +
                         winB * readDelayCubic(delayL_, writePos_, dB);
        float pitchedR = winA * readDelayCubic(delayR_, writePos_, dA) +
                         winB * readDelayCubic(delayR_, writePos_, dB);

        // Secondary formant grain + vocal-tract SVF resonator when Formant != 0 ST
        if (formantAmt > 0.01f) {
            const float formRate = (1.0f - (smoothRatio_ * formantRatio)) / (kGrainSize * 0.5f);
            formantPhase_ += formRate;
            if (formantPhase_ >= 1.0f) formantPhase_ -= std::floor(formantPhase_);
            if (formantPhase_ < 0.0f)  formantPhase_ += 1.0f - std::floor(formantPhase_);

            const float fPhA = formantPhase_;
            const float fPhB = (fPhA + 0.5f >= 1.0f) ? (fPhA - 0.5f) : (fPhA + 0.5f);
            const float fWinA = 0.5f * (1.0f - std::cos(kTwoPi * fPhA));
            const float fWinB = 0.5f * (1.0f - std::cos(kTwoPi * fPhB));
            const float fdA = fPhA * (kGrainSize * 0.5f) + 2.0f;
            const float fdB = fPhB * (kGrainSize * 0.5f) + 2.0f;

            float formGrainL = fWinA * readDelayCubic(delayL_, writePos_, fdA) +
                               fWinB * readDelayCubic(delayL_, writePos_, fdB);
            float formGrainR = fWinA * readDelayCubic(delayR_, writePos_, fdA) +
                               fWinB * readDelayCubic(delayR_, writePos_, fdB);

            // 2-pole SVF vocal tract filter
            svfLowL_ += svfF * svfBandL_;
            float highL = formGrainL - svfLowL_ - svfQ * svfBandL_;
            svfBandL_ += svfF * highL;

            svfLowR_ += svfF * svfBandR_;
            float highR = formGrainR - svfLowR_ - svfQ * svfBandR_;
            svfBandR_ += svfF * highR;

            float tractL = (formantSt < 0.0f) ? (0.65f * svfLowL_ + 0.55f * svfBandL_)
                                              : (0.65f * svfBandL_ + 0.45f * highL);
            float tractR = (formantSt < 0.0f) ? (0.65f * svfLowR_ + 0.55f * svfBandR_)
                                              : (0.65f * svfBandR_ + 0.45f * highR);

            pitchedL = (1.0f - 0.65f * formantAmt) * pitchedL + (0.65f * formantAmt) * (formGrainL * 0.5f + tractL * 0.8f);
            pitchedR = (1.0f - 0.65f * formantAmt) * pitchedR + (0.65f * formantAmt) * (formGrainR * 0.5f + tractR * 0.8f);
        }

        writePos_ = (writePos_ + 1) & kDelayMask;

        const float outL = inL + wetMix * (pitchedL - inL);
        const float outR = inR + wetMix * (pitchedR - inR);

        left[i]  = sanitizeSample(outL);
        right[i] = sanitizeSample(outR);
    }
}

} // namespace flm_dsp
