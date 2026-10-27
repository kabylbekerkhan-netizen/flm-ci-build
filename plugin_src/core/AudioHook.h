#pragma once
#include <atomic>
#include <cstdint>

namespace flm_dsp {

enum class HookMode : int {
    MasterOut = 0,
    MicIn     = 1
};

enum class AudioFormatKind : int {
    Unknown        = 0,
    Float32Planar  = 1,
    Float32Inter   = 2,
    Unsupported    = 3
};

class AudioHook {
public:
    static void install();

    static void setMode(HookMode mode);
    static HookMode getMode();

    static void setSafeMode(bool safe);
    static bool isSafeMode();

    static bool isHookInstalled();
    static bool isAudioActive();
    static uint64_t callbackCount();
    static uint32_t lastFrames();
    static float currentSampleRate();

    // AudioStreamBasicDescription telemetry (lock-free atomics)
    static AudioFormatKind formatKind();
    static uint32_t formatFlags();
    static uint32_t bitsPerChannel();
    static uint32_t channelsPerFrame();
    static bool isInterleaved();
};

} // namespace flm_dsp
