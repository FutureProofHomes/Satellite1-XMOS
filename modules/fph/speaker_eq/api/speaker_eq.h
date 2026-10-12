#ifndef FPH_SPEAKER_EQ_H_
#define FPH_SPEAKER_EQ_H_

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "xmath/types.h"

#ifdef __cplusplus
extern "C" {
#endif

#define SPEAKER_EQ_CHANNEL_COUNT 2
#define SPEAKER_EQ_PEAK_COUNT 5
#define SPEAKER_EQ_SECTION_COUNT 8
#define SPEAKER_EQ_PASS_SECTION_COUNT 2
#define SPEAKER_EQ_STATE_WORDS (SPEAKER_EQ_SECTION_COUNT * 8)

typedef enum {
    SPEAKER_EQ_STATUS_OK = 0,
    SPEAKER_EQ_STATUS_INVALID_ARGUMENT,
    SPEAKER_EQ_STATUS_INVALID_SAMPLE_RATE,
    SPEAKER_EQ_STATUS_INVALID_CHANNEL_MODE,
    SPEAKER_EQ_STATUS_INVALID_PASS_MODE,
    SPEAKER_EQ_STATUS_OUT_OF_RANGE,
    SPEAKER_EQ_STATUS_UNSTABLE_FILTER,
    SPEAKER_EQ_STATUS_INSUFFICIENT_HEADROOM,
} speaker_eq_status_t;

typedef enum {
    SPEAKER_EQ_MODE_STEREO_LINKED = 0,
    SPEAKER_EQ_MODE_MONO,
} speaker_eq_channel_mode_t;

typedef enum {
    SPEAKER_EQ_PASS_BYPASS = 0,
    SPEAKER_EQ_PASS_BUTTERWORTH_12,
    SPEAKER_EQ_PASS_BUTTERWORTH_24,
    SPEAKER_EQ_PASS_LINKWITZ_RILEY_12,
    SPEAKER_EQ_PASS_LINKWITZ_RILEY_24,
} speaker_eq_pass_mode_t;

typedef enum {
    SPEAKER_EQ_PASS_HIGH = 0,
    SPEAKER_EQ_PASS_LOW,
} speaker_eq_pass_kind_t;

typedef struct {
    bool enabled;
    float frequency_hz;
    float q;
    float gain_db;
} speaker_eq_parametric_t;

typedef speaker_eq_parametric_t speaker_eq_high_shelf_t;

typedef struct {
    speaker_eq_channel_mode_t channel_mode;
    bool bypass;
    float pregain_db;
    float clip_level_dbfs;
    speaker_eq_pass_mode_t hpf_mode;
    float hpf_frequency_hz;
    speaker_eq_parametric_t peak[SPEAKER_EQ_PEAK_COUNT];
    speaker_eq_high_shelf_t high_shelf;
} speaker_eq_config_t;

typedef struct {
    float minimum_frequency_hz;
    float maximum_frequency_hz;
    float minimum_q;
    float maximum_q;
    float minimum_peak_gain_db;
    float maximum_peak_gain_db;
    float minimum_shelf_gain_db;
    float maximum_shelf_gain_db;
    float minimum_pregain_db;
    float maximum_pregain_db;
    float minimum_clip_level_dbfs;
    float headroom_margin_db;
    bool enforce_headroom;
} speaker_eq_limits_t;

typedef struct {
    speaker_eq_channel_mode_t channel_mode;
    bool bypass;
    int32_t pregain_q27;
    int32_t clip_threshold;
    q2_30 coeffs[SPEAKER_EQ_SECTION_COUNT * 5] __attribute__((aligned(8)));
    left_shift_t shifts[SPEAKER_EQ_SECTION_COUNT];
    float recommended_pregain_db;
} speaker_eq_program_t;

typedef struct {
    speaker_eq_program_t program;
    int32_t state[SPEAKER_EQ_CHANNEL_COUNT][SPEAKER_EQ_STATE_WORDS]
        __attribute__((aligned(8)));
} speaker_eq_t;

speaker_eq_status_t speaker_eq_design_pass_filter(
    q2_30 coeffs[SPEAKER_EQ_PASS_SECTION_COUNT * 5],
    left_shift_t shifts[SPEAKER_EQ_PASS_SECTION_COUNT],
    speaker_eq_pass_kind_t kind,
    speaker_eq_pass_mode_t mode,
    float frequency_hz,
    uint32_t sample_rate_hz);

speaker_eq_status_t speaker_eq_design_program(
    speaker_eq_program_t *program,
    const speaker_eq_config_t *config,
    const speaker_eq_limits_t *limits,
    uint32_t sample_rate_hz);

speaker_eq_status_t speaker_eq_init(
    speaker_eq_t *eq,
    const speaker_eq_program_t *initial_program);

speaker_eq_status_t speaker_eq_apply_program(
    speaker_eq_t *eq,
    const speaker_eq_program_t *program);

void speaker_eq_reset(speaker_eq_t *eq);

void speaker_eq_process_frame(
    speaker_eq_t *eq,
    int32_t *channels[SPEAKER_EQ_CHANNEL_COUNT],
    size_t frame_length);

#ifdef __cplusplus
}
#endif

#endif
