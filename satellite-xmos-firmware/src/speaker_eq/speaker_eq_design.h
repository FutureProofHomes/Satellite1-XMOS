#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "speaker_eq/speaker_eq_cmds.h"

typedef struct {
    uint8_t type;
    uint8_t flags;
    float freq_hz;
    float gain_db;
    float q;
} speaker_eq_filter_t;

typedef struct {
    float preamp_db;
    float limiter_db;
    float attack_ms;
    float release_ms;
    uint8_t filter_count;
    speaker_eq_filter_t filters[SPEAKER_EQ_MAX_FILTERS];
} speaker_eq_slot_params_t;

/*
 * A designed profile, in processing order. Coefficients are lib_audio_dsp
 * biquads: b0, b1, b2 at Q(30 - lsh), then -a1, -a2 at Q30.
 */
typedef struct {
    int32_t coeffs[SPEAKER_EQ_MAX_SECTIONS][5];
    int8_t lsh[SPEAKER_EQ_MAX_SECTIONS];
    uint16_t section_id[SPEAKER_EQ_MAX_SECTIONS];   /* type << 5 | filter index * 2 + stage */
    int32_t pre_gain;           /* Q_GAIN, applied before the sections */
    int32_t post_gain;          /* Q_GAIN, applied after the sections */
    int32_t limiter_threshold;  /* Q_SIG */
    int32_t attack_alpha;       /* Q31 */
    int32_t release_alpha;      /* Q31 */
    uint8_t num_sections;
    uint8_t active;             /* 0: bit-exact bypass */
    uint8_t reason;             /* speaker_eq_bypass_reason_t when !active */
    uint8_t limiter_required;
} speaker_eq_bank_t;

typedef struct {
    float max_gain_db;          /* net response maximum */
    float peak_gain_db;         /* worst gain at any section boundary */
    uint8_t sections;
} speaker_eq_analysis_t;

/* Decodes and range-checks a SET_SLOT payload. */
bool speaker_eq_decode_slot(const uint8_t *payload,
                            uint8_t *slot,
                            speaker_eq_slot_params_t *params);

void speaker_eq_encode_slot(uint8_t slot,
                            const speaker_eq_slot_params_t *params,
                            uint8_t *payload);

void speaker_eq_bank_set_bypass(speaker_eq_bank_t *bank, uint8_t reason);

/*
 * Designs a profile. Returns false, leaving bank untouched, when the worst
 * section-boundary gain exceeds SPEAKER_EQ_HEADROOM_CAP_DB.
 */
bool speaker_eq_design(const speaker_eq_slot_params_t *params,
                       float fs,
                       speaker_eq_bank_t *bank,
                       speaker_eq_analysis_t *analysis);
