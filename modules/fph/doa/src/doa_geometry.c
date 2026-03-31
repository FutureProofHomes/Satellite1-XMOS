#include "gcc_phat.h"

#include <math.h>

float doa4_estimate_from_lags(
        int lag10,
        int lag20,
        int lag30)
{
    const float r = DOA4_ARRAY_RADIUS_M;
    const float fs = DOA4_SAMPLE_RATE_HZ;
    const float c = DOA4_SPEED_OF_SOUND;

    /* Project mic indexing convention: mic0=N, mic1=E, mic2=S, mic3=W */
    const float a1x = r;
    const float a1y = -r;
    const float a2x = 0.0f;
    const float a2y = -2 * r;
    const float a3x = -r;
    const float a3y = -r;

    const float b1 = c * ((float) lag10 / fs);
    const float b2 = c * ((float) lag20 / fs);
    const float b3 = c * ((float) lag30 / fs);

    const float ata00 = a1x * a1x + a2x * a2x + a3x * a3x;
    const float ata01 = a1x * a1y + a2x * a2y + a3x * a3y;
    const float ata11 = a1y * a1y + a2y * a2y + a3y * a3y;

    const float atb0 = a1x * b1 + a2x * b2 + a3x * b3;
    const float atb1 = a1y * b1 + a2y * b2 + a3y * b3;

    const float det = ata00 * ata11 - ata01 * ata01;
    if (fabsf(det) < 1e-12f) {
        return 0.0f;
    }

    const float inv00 = ata11 / det;
    const float inv01 = -ata01 / det;
    const float inv11 = ata00 / det;

    float ux = inv00 * atb0 + inv01 * atb1;
    float uy = inv01 * atb0 + inv11 * atb1;

    {
        const float n = sqrtf(ux * ux + uy * uy);
        if (n > 1e-12f) {
            ux /= n;
            uy /= n;
        }
    }

    return atan2f(uy, ux);
}
