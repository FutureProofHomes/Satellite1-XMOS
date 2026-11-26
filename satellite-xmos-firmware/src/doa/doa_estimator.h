#pragma once

#include <stddef.h>
#include <stdint.h>

#define DOA_ESTIMATOR_MAX_LAG_SAMPLES (4)
#define DOA_ESTIMATOR_LAG_Q8_SCALE    (256)
#define DOA_ESTIMATOR_FLAG_VALID      (1u << 0)
#define DOA_ESTIMATOR_FLAG_FOUR_MIC   (1u << 1)
#define DOA_ESTIMATOR_FLAG_LOCKED     (1u << 2)
#define DOA_ESTIMATOR_FLAG_PLAYBACK   (1u << 3)

#define DOA_ESTIMATOR_CONTROL_PLAYBACK_ACTIVE (1u << 0)
#define DOA_ESTIMATOR_CONTROL_VOICE_LOCK      (1u << 1)
#define DOA_ESTIMATOR_CONTROL_FORCE_OMNI      (1u << 2)
#define DOA_ESTIMATOR_CONTROL_VOICE_ACTIVE    (1u << 3)
#define DOA_ESTIMATOR_CONTROL_MASK            (0x0fu)

#define DOA_ESTIMATOR_MODE_LOCKED          (1u << 0)
#define DOA_ESTIMATOR_MODE_PLAYBACK_FROZEN (1u << 1)
#define DOA_ESTIMATOR_MODE_FORCE_OMNI      (1u << 2)

typedef struct {
    /* Positive values mean mic1 best matches a later sample than mic0. */
    int16_t sample_delay;
    int16_t vertical_delay;
    int16_t sample_delay_q8;
    int16_t vertical_delay_q8;
    uint8_t angle_index;
    uint8_t confidence;
    uint8_t flags;
    uint32_t energy;
    uint32_t frame_counter;
    uint32_t mic_energy[4];
} doa_estimator_state_t;

typedef struct {
    int16_t steering_delay_q8;
    int16_t vertical_steering_delay_q8;
    uint32_t noise_floor_energy;
    uint8_t signal_active;
    uint8_t control_flags;
    uint8_t mode_flags;
    uint8_t active_mic_mask;
} doa_estimator_diagnostics_t;

void doa_estimator_process_frame(const int32_t *mic0,
                                 const int32_t *mic1,
                                 size_t frame_count);

void doa_estimator_process_frame_4(const int32_t *east,
                                   const int32_t *west,
                                   const int32_t *north,
                                   const int32_t *south,
                                   size_t frame_count);

void doa_estimator_get_state(doa_estimator_state_t *state);
/* Direction for display, before audio-only force-omni/hold policy. */
void doa_estimator_get_observation(doa_estimator_state_t *state);
void doa_estimator_get_diagnostics(doa_estimator_diagnostics_t *diagnostics);
void doa_estimator_set_control(uint8_t control_flags);
void doa_estimator_set_host_hints(uint8_t hint_flags);
void doa_estimator_set_mic_health(uint8_t active_mic_mask);
/* Enables speech-gated tracking for the post-AEC frontend. Legacy callers
 * retain their existing energy gate and playback-freeze behaviour. */
void doa_estimator_set_tracking_evidence(uint8_t speech_active, uint8_t echo_dominated);
void doa_estimator_reset(void);
