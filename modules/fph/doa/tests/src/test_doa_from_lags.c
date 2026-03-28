#include "gcc_phat.h"

#include <math.h>
#include <stdio.h>

static float deg_to_rad(float deg)
{
    return deg * (3.14159265358979323846f / 180.0f);
}

static float rad_to_deg(float rad)
{
    return rad * (180.0f / 3.14159265358979323846f);
}

static float wrap_deg(float deg)
{
    while (deg > 180.0f) {
        deg -= 360.0f;
    }
    while (deg < -180.0f) {
        deg += 360.0f;
    }

    return deg;
}

static float angle_error_deg(float expected_deg, float actual_deg)
{
    return fabsf(wrap_deg(actual_deg - expected_deg));
}

static void synthesize_lags_from_angle(float angle_deg,
                                       int *lag10,
                                       int *lag20,
                                       int *lag30)
{
    const float r = DOA4_ARRAY_RADIUS_M;
    const float fs_over_c = DOA4_SAMPLE_RATE_HZ / DOA4_SPEED_OF_SOUND;
    const float ux = cosf(deg_to_rad(angle_deg));
    const float uy = sinf(deg_to_rad(angle_deg));

    const float a1x = -r;
    const float a1y = r;
    const float a2x = -2 * r;
    const float a2y = 0.0f;
    const float a3x = -r;
    const float a3y = -r;

    *lag10 = (int) lroundf(fs_over_c * ((a1x * ux) + (a1y * uy)));
    *lag20 = (int) lroundf(fs_over_c * ((a2x * ux) + (a2y * uy)));
    *lag30 = (int) lroundf(fs_over_c * ((a3x * ux) + (a3y * uy)));
}

static int run_angle_case(float expected_deg, float tol_deg)
{
    int lag10;
    int lag20;
    int lag30;
    float estimate_rad;
    float estimate_deg;
    float err_deg;

    synthesize_lags_from_angle(expected_deg, &lag10, &lag20, &lag30);

    estimate_rad = doa4_estimate_from_lags(lag10, lag20, lag30);
    estimate_deg = rad_to_deg(estimate_rad);
    err_deg = angle_error_deg(expected_deg, estimate_deg);

    if (err_deg > tol_deg) {
        fprintf(stderr,
                "FAIL angle %.1f deg -> lags (%d,%d,%d) estimate %.2f deg err %.2f deg\n",
                expected_deg,
                lag10,
                lag20,
                lag30,
                estimate_deg,
                err_deg);
        return 1;
    }

    return 0;
}

static int run_channel_order_guard_case(void)
{
    int lag10;
    int lag20;
    int lag30;
    float estimate_deg;
    float err_deg;

    synthesize_lags_from_angle(45.0f, &lag10, &lag20, &lag30);

    /* Swap lag10 and lag30 to emulate channel-order mismatch. */
    estimate_deg = rad_to_deg(doa4_estimate_from_lags(lag30, lag20, lag10));
    err_deg = angle_error_deg(45.0f, estimate_deg);

    if (err_deg < 20.0f) {
        fprintf(stderr,
                "FAIL channel-order guard expected mismatch, got estimate %.2f deg (err %.2f)\n",
                estimate_deg,
                err_deg);
        return 1;
    }

    return 0;
}

int main(void)
{
    const float tol_deg = 15.0f;
    const float cases[] = {0.0f, 45.0f, 90.0f, 135.0f, 180.0f, -45.0f, -90.0f, -135.0f};
    int failed = 0;
    unsigned i;

    for (i = 0; i < (sizeof(cases) / sizeof(cases[0])); i++) {
        failed += run_angle_case(cases[i], tol_deg);
    }

    failed += run_channel_order_guard_case();

    if (failed != 0) {
        fprintf(stderr, "doa_from_lags_test: %d case(s) failed\n", failed);
        return 1;
    }

    printf("doa_from_lags_test: all cases passed\n");
    return 0;
}
