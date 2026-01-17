// Copyright 2026 FutureProofHomes
// Stub DoA module (Path B). Implementation to be added.

#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef struct {
    float azimuth_deg;
    float confidence;
} doa_result_t;

void doa_init(uint32_t sample_rate_hz, size_t mic_count);

// Returns true if a new result is available.
bool doa_process_frame(const int32_t *mic_samples,
                       size_t mic_count,
                       size_t frame_count,
                       doa_result_t *out);

void doa_set_delay_offsets_samples(const float *offsets, size_t count);

// Returns true if a result has been computed.
bool doa_get_latest(doa_result_t *out);
