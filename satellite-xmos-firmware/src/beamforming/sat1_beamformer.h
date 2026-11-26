#pragma once

#include <stddef.h>
#include <stdint.h>

#include "doa/doa_estimator.h"

#define SAT1_BEAMFORMER_MIC_COUNT (4)
#define SAT1_BEAMFORMER_HISTORY_SAMPLES \
    (DOA_ESTIMATOR_MAX_LAG_SAMPLES + 3)

#define SAT1_MIC_HEALTH_DEAD     (1u << 0)
#define SAT1_MIC_HEALTH_NOISY    (1u << 1)
#define SAT1_MIC_HEALTH_CLIPPING (1u << 2)

typedef struct {
    int32_t history[SAT1_BEAMFORMER_MIC_COUNT]
                   [SAT1_BEAMFORMER_HISTORY_SAMPLES];
    int16_t current_delay_q8[SAT1_BEAMFORMER_MIC_COUNT];
    uint32_t mic_level_ema[SAT1_BEAMFORMER_MIC_COUNT];
    uint16_t mic_gain_q15[SAT1_BEAMFORMER_MIC_COUNT];
    uint8_t mic_health_flags[SAT1_BEAMFORMER_MIC_COUNT];
    uint8_t mic_fault_streak[SAT1_BEAMFORMER_MIC_COUNT];
    uint8_t mic_recovery_streak[SAT1_BEAMFORMER_MIC_COUNT];
    uint16_t calibration_frames;
    uint8_t active_mic_mask;
    uint8_t invalid_direction_frames;
    uint8_t has_direction;
    uint8_t initialized;
} sat1_beamformer_t;

typedef struct {
    int16_t current_delay_q8[SAT1_BEAMFORMER_MIC_COUNT];
    uint32_t mic_level[SAT1_BEAMFORMER_MIC_COUNT];
    uint16_t mic_gain_q15[SAT1_BEAMFORMER_MIC_COUNT];
    uint8_t mic_health_flags[SAT1_BEAMFORMER_MIC_COUNT];
    uint8_t active_mic_mask;
} sat1_beamformer_diagnostics_t;

/*
 * Four-microphone fractional-delay delay-and-sum beamformer.
 *
 * Microphone order is East, West, North, South. The DoA estimator supplies
 * the East/West and North/South pair delays in Q8 samples. A fixed center
 * delay keeps total latency constant while steering changes.
 */
void sat1_beamformer_process_frame(
    sat1_beamformer_t *beamformer,
    int32_t *output,
    const int32_t *microphones[SAT1_BEAMFORMER_MIC_COUNT],
    size_t frame_count,
    const doa_estimator_state_t *direction);

void sat1_beamformer_reset(sat1_beamformer_t *beamformer);
void sat1_beamformer_get_diagnostics(
    sat1_beamformer_diagnostics_t *diagnostics);

/* Split raw-level health calibration from processing echo-cancelled microphones. */
void sat1_beamformer_analyze_frame(sat1_beamformer_t *beamformer,
                                  const int32_t *microphones[4], size_t frame_count);
void sat1_beamformer_process_calibrated_frame(sat1_beamformer_t *beamformer,
    int32_t *output, const int32_t *microphones[4], size_t frame_count,
    const doa_estimator_state_t *direction);

/* Import raw-microphone calibration when postprocessing runs on another tile.
 * Steering/history remain owned by the processing instance. */
void sat1_beamformer_set_calibration(sat1_beamformer_t *beamformer,
    const sat1_beamformer_diagnostics_t *calibration);

/* The blocking reference is the first healthy aligned mic minus the beam.
 * A perfectly aligned/calibrated target cancels from this reference. */
void sat1_beamformer_process_calibrated_frame_with_reference(
    sat1_beamformer_t *beamformer, int32_t *output, int32_t *noise_reference,
    const int32_t *microphones[4], size_t frame_count,
    const doa_estimator_state_t *direction);
