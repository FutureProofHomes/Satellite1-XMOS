#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "doa/doa.h"

#define SAMPLE_RATE 16000
#define FRAME_COUNT 240
#define MIC_COUNT 4

static const float positions[MIC_COUNT][2] = {
    { 0.035f,  0.000f },
    { 0.000f,  0.035f },
    {-0.035f,  0.000f },
    { 0.000f, -0.035f },
};

static void synth_frame(float azimuth_deg, int32_t out[MIC_COUNT][FRAME_COUNT])
{
    const float pi = 3.14159265358979323846f;
    float az = azimuth_deg * pi / 180.0f;
    float ux = cosf(az);
    float uy = sinf(az);

    memset(out, 0, sizeof(int32_t) * MIC_COUNT * FRAME_COUNT);

    int base_idx = FRAME_COUNT / 4;
    for (int mic = 0; mic < MIC_COUNT; mic++) {
        float dx = positions[mic][0] - positions[0][0];
        float dy = positions[mic][1] - positions[0][1];
        float delay_s = (dx * ux + dy * uy) / 343.0f;
        float delay_samples = delay_s * (float) SAMPLE_RATE;
        int idx = base_idx + (int) lroundf(delay_samples);
        if (idx < 0) {
            idx = 0;
        }
        if (idx >= FRAME_COUNT) {
            idx = FRAME_COUNT - 1;
        }
        out[mic][idx] = 2000000;
    }
}

int main(void)
{
    doa_init(SAMPLE_RATE, MIC_COUNT);

    int32_t frame[MIC_COUNT][FRAME_COUNT];
    synth_frame(45.0f, frame);

    doa_result_t result;
    if (!doa_process_frame((const int32_t *) frame, MIC_COUNT, FRAME_COUNT, &result)) {
        printf("DoA failed\n");
        return 1;
    }

    printf("Expected ~45 deg, got %.2f deg, confidence %.2f\n", result.azimuth_deg, result.confidence);
    return 0;
}
