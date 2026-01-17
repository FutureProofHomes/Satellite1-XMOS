// Copyright 2026 FutureProofHomes
// Simple DoA estimator using normalized cross-correlation for TDOA.

#include "doa/doa.h"

#include <math.h>
#include <string.h>

#define DOA_DEFAULT_ALPHA 0.2f
#define DOA_SPEED_OF_SOUND 343.0f
#define DOA_PI 3.14159265358979323846f

typedef struct {
    float x;
    float y;
} doa_mic_pos_t;

static uint32_t doa_sample_rate_hz;
static size_t doa_mic_count;
static int doa_max_lag;
static float doa_alpha = DOA_DEFAULT_ALPHA;
static bool doa_has_result;
static doa_result_t doa_latest;

static float doa_smooth_x;
static float doa_smooth_y;
static bool doa_has_smooth;
static float doa_delay_offsets_samples[4];

static float doa_window[512];
static size_t doa_window_len;

static const doa_mic_pos_t doa_default_positions[4] = {
    { 0.035f,  0.000f },
    { 0.000f,  0.035f },
    {-0.035f,  0.000f },
    { 0.000f, -0.035f },
};

static void doa_update_window(size_t frame_count)
{
    if (doa_window_len == frame_count) {
        return;
    }
    doa_window_len = frame_count;
    if (frame_count < 2 || frame_count > (sizeof(doa_window) / sizeof(doa_window[0]))) {
        return;
    }
    const float denom = (float)(frame_count - 1);
    for (size_t i = 0; i < frame_count; i++) {
        doa_window[i] = 0.5f - 0.5f * cosf(2.0f * DOA_PI * (float)i / denom);
    }
}

static float doa_energy_windowed(const int32_t *samples, size_t frame_count)
{
    float energy = 0.0f;
    for (size_t i = 0; i < frame_count; i++) {
        float v = (float) samples[i] * doa_window[i];
        energy += v * v;
    }
    return energy;
}

static float doa_corr_lag(const int32_t *a, const int32_t *b, size_t frame_count, int lag)
{
    float sum = 0.0f;
    if (lag >= 0) {
        size_t max = frame_count - (size_t) lag;
        for (size_t i = 0; i < max; i++) {
            float va = (float) a[i] * doa_window[i];
            float vb = (float) b[i + (size_t) lag] * doa_window[i + (size_t) lag];
            sum += va * vb;
        }
    } else {
        size_t shift = (size_t)(-lag);
        size_t max = frame_count - shift;
        for (size_t i = 0; i < max; i++) {
            float va = (float) a[i + shift] * doa_window[i + shift];
            float vb = (float) b[i] * doa_window[i];
            sum += va * vb;
        }
    }
    return sum;
}

static int doa_best_lag(const int32_t *a, const int32_t *b, size_t frame_count, float *out_conf)
{
    float energy_a = doa_energy_windowed(a, frame_count);
    float energy_b = doa_energy_windowed(b, frame_count);
    float denom = sqrtf(energy_a * energy_b) + 1e-9f;

    int best_lag = 0;
    float best_corr = 0.0f;
    for (int lag = -doa_max_lag; lag <= doa_max_lag; lag++) {
        float corr = doa_corr_lag(a, b, frame_count, lag);
        float norm = corr / denom;
        if (fabsf(norm) > fabsf(best_corr)) {
            best_corr = norm;
            best_lag = lag;
        }
    }

    if (out_conf != NULL) {
        float conf = fabsf(best_corr);
        if (conf > 1.0f) {
            conf = 1.0f;
        }
        *out_conf = conf;
    }
    return best_lag;
}

void doa_init(uint32_t sample_rate_hz, size_t mic_count)
{
    doa_sample_rate_hz = sample_rate_hz;
    doa_mic_count = mic_count;
    doa_has_result = false;
    doa_has_smooth = false;
    memset(doa_delay_offsets_samples, 0, sizeof(doa_delay_offsets_samples));

    float max_distance_m = 0.07f;
    float max_delay_s = max_distance_m / DOA_SPEED_OF_SOUND;
    doa_max_lag = (int) ceilf(max_delay_s * (float) doa_sample_rate_hz) + 1;
    if (doa_max_lag < 1) {
        doa_max_lag = 1;
    }
    if (doa_max_lag > 12) {
        doa_max_lag = 12;
    }
}

void doa_set_delay_offsets_samples(const float *offsets, size_t count)
{
    if (offsets == NULL) {
        return;
    }
    size_t copy_count = count;
    if (copy_count > 4) {
        copy_count = 4;
    }
    for (size_t i = 0; i < copy_count; i++) {
        doa_delay_offsets_samples[i] = offsets[i];
    }
}

bool doa_process_frame(const int32_t *mic_samples,
                       size_t mic_count,
                       size_t frame_count,
                       doa_result_t *out)
{
    if (mic_samples == NULL || mic_count < 4 || frame_count == 0) {
        return false;
    }
    if (doa_mic_count != 0 && mic_count != doa_mic_count) {
        return false;
    }

    doa_update_window(frame_count);
    if (doa_window_len != frame_count) {
        return false;
    }

    const int32_t *mic0 = mic_samples + (0 * frame_count);
    const int32_t *mic1 = mic_samples + (1 * frame_count);
    const int32_t *mic2 = mic_samples + (2 * frame_count);
    const int32_t *mic3 = mic_samples + (3 * frame_count);

    float confs[3];
    int lag1 = doa_best_lag(mic0, mic1, frame_count, &confs[0]);
    int lag2 = doa_best_lag(mic0, mic2, frame_count, &confs[1]);
    int lag3 = doa_best_lag(mic0, mic3, frame_count, &confs[2]);

    float tau1 = (float) lag1 / (float) doa_sample_rate_hz;
    float tau2 = (float) lag2 / (float) doa_sample_rate_hz;
    float tau3 = (float) lag3 / (float) doa_sample_rate_hz;

    tau1 -= (doa_delay_offsets_samples[1] - doa_delay_offsets_samples[0]) / (float) doa_sample_rate_hz;
    tau2 -= (doa_delay_offsets_samples[2] - doa_delay_offsets_samples[0]) / (float) doa_sample_rate_hz;
    tau3 -= (doa_delay_offsets_samples[3] - doa_delay_offsets_samples[0]) / (float) doa_sample_rate_hz;

    float a11 = 0.0f;
    float a12 = 0.0f;
    float a22 = 0.0f;
    float b1 = 0.0f;
    float b2 = 0.0f;

    const doa_mic_pos_t *p0 = &doa_default_positions[0];
    const doa_mic_pos_t *p1 = &doa_default_positions[1];
    const doa_mic_pos_t *p2 = &doa_default_positions[2];
    const doa_mic_pos_t *p3 = &doa_default_positions[3];

    const doa_mic_pos_t *pos[3] = {p1, p2, p3};
    const float taus[3] = {tau1, tau2, tau3};

    for (int i = 0; i < 3; i++) {
        float dx = pos[i]->x - p0->x;
        float dy = pos[i]->y - p0->y;
        float bi = DOA_SPEED_OF_SOUND * taus[i];
        a11 += dx * dx;
        a12 += dx * dy;
        a22 += dy * dy;
        b1 += dx * bi;
        b2 += dy * bi;
    }

    float det = (a11 * a22) - (a12 * a12);
    if (fabsf(det) < 1e-9f) {
        return false;
    }

    float ux = (a22 * b1 - a12 * b2) / det;
    float uy = (-a12 * b1 + a11 * b2) / det;

    float norm = sqrtf(ux * ux + uy * uy) + 1e-9f;
    ux /= norm;
    uy /= norm;

    if (!doa_has_smooth) {
        doa_smooth_x = ux;
        doa_smooth_y = uy;
        doa_has_smooth = true;
    } else {
        doa_smooth_x = (1.0f - doa_alpha) * doa_smooth_x + doa_alpha * ux;
        doa_smooth_y = (1.0f - doa_alpha) * doa_smooth_y + doa_alpha * uy;
        float sn = sqrtf(doa_smooth_x * doa_smooth_x + doa_smooth_y * doa_smooth_y) + 1e-9f;
        doa_smooth_x /= sn;
        doa_smooth_y /= sn;
    }

    float az = atan2f(doa_smooth_y, doa_smooth_x) * (180.0f / DOA_PI);
    if (az < 0.0f) {
        az += 360.0f;
    }

    float conf = (confs[0] + confs[1] + confs[2]) / 3.0f;
    if (conf > 1.0f) {
        conf = 1.0f;
    } else if (conf < 0.0f) {
        conf = 0.0f;
    }

    doa_latest.azimuth_deg = az;
    doa_latest.confidence = conf;
    doa_has_result = true;

    if (out != NULL) {
        *out = doa_latest;
    }

    return true;
}

bool doa_get_latest(doa_result_t *out)
{
    if (!doa_has_result || out == NULL) {
        return false;
    }
    *out = doa_latest;
    return true;
}
