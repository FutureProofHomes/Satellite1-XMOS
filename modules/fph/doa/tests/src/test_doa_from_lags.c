#include "gcc_phat.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

static float deg_to_rad(float deg)
{
    return deg * (3.14159265358979323846f / 180.0f);
}

static float rad_to_deg(float rad)
{
    return rad * (180.0f / 3.14159265358979323846f);
}

static float compass_deg_to_math_deg(float compass_deg)
{
    return 90.0f - compass_deg;
}

static float math_rad_to_compass_deg(float math_rad)
{
    return 90.0f - rad_to_deg(math_rad);
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
    const float math_deg = compass_deg_to_math_deg(angle_deg);
    const float ux = cosf(deg_to_rad(math_deg));
    const float uy = sinf(deg_to_rad(math_deg));

    const float a1x = r;
    const float a1y = -r;
    const float a2x = 0.0f;
    const float a2y = -2 * r;
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
    estimate_deg = math_rad_to_compass_deg(estimate_rad);
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
    estimate_deg = math_rad_to_compass_deg(doa4_estimate_from_lags(lag30, lag20, lag10));
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

static int estimate_lag_bruteforce(const int *a,
                                   const int *b,
                                   int n,
                                   int max_lag)
{
    int best_lag = 0;
    long long best_score = -1;
    int lag;

    for (lag = -max_lag; lag <= max_lag; ++lag) {
        long long score = 0;
        int i;
        for (i = 0; i < n; ++i) {
            int j = i - lag;
            if (j < 0 || j >= n) {
                continue;
            }
            score += ((long long) a[i]) * ((long long) b[j]);
        }
        if (score > best_score) {
            best_score = score;
            best_lag = lag;
        }
    }

    return best_lag;
}

static int run_lag_estimation_replica_case(float expected_deg, float tol_deg)
{
    enum { FRAME_SAMPLES = 240 };
    int lag10_expected;
    int lag20_expected;
    int lag30_expected;
    int mic0[FRAME_SAMPLES] = {0};
    int mic1[FRAME_SAMPLES] = {0};
    int mic2[FRAME_SAMPLES] = {0};
    int mic3[FRAME_SAMPLES] = {0};
    int pulse_starts[] = {40, 120, 200};
    const int pulse_count = (int) (sizeof(pulse_starts) / sizeof(pulse_starts[0]));
    const int amp = 100000;
    int p;
    int lag10;
    int lag20;
    int lag30;
    float estimate_deg;
    float err_deg;

    synthesize_lags_from_angle(expected_deg, &lag10_expected, &lag20_expected, &lag30_expected);

    for (p = 0; p < pulse_count; ++p) {
        int idx0 = pulse_starts[p];
        int idx1 = idx0 + lag10_expected;
        int idx2 = idx0 + lag20_expected;
        int idx3 = idx0 + lag30_expected;

        if (idx0 >= 0 && idx0 < FRAME_SAMPLES) {
            mic0[idx0] = amp;
        }
        if (idx1 >= 0 && idx1 < FRAME_SAMPLES) {
            mic1[idx1] = amp;
        }
        if (idx2 >= 0 && idx2 < FRAME_SAMPLES) {
            mic2[idx2] = amp;
        }
        if (idx3 >= 0 && idx3 < FRAME_SAMPLES) {
            mic3[idx3] = amp;
        }
    }

    lag10 = estimate_lag_bruteforce(mic1, mic0, FRAME_SAMPLES, DOA4_MAX_LAG_SAMPLES);
    lag20 = estimate_lag_bruteforce(mic2, mic0, FRAME_SAMPLES, DOA4_MAX_LAG_SAMPLES);
    lag30 = estimate_lag_bruteforce(mic3, mic0, FRAME_SAMPLES, DOA4_MAX_LAG_SAMPLES);

    if (lag10 != lag10_expected || lag20 != lag20_expected || lag30 != lag30_expected) {
        fprintf(stderr,
                "FAIL lag replica %.1f deg expected (%d,%d,%d) got (%d,%d,%d)\n",
                expected_deg,
                lag10_expected,
                lag20_expected,
                lag30_expected,
                lag10,
                lag20,
                lag30);
        return 1;
    }

    estimate_deg = math_rad_to_compass_deg(doa4_estimate_from_lags(lag10, lag20, lag30));
    err_deg = angle_error_deg(expected_deg, estimate_deg);
    if (err_deg > tol_deg) {
        fprintf(stderr,
                "FAIL lag replica angle %.1f deg -> estimate %.2f deg err %.2f\n",
                expected_deg,
                estimate_deg,
                err_deg);
        return 1;
    }

    return 0;
}

static int run_fixture_file(const char *path, float tol_deg)
{
    FILE *fp;
    char line[256];
    int failed = 0;
    int parsed_cases = 0;

    fp = fopen(path, "r");
    if (fp == NULL) {
        fprintf(stderr, "FAIL could not open fixture file: %s\n", path);
        return 1;
    }

    while (fgets(line, sizeof(line), fp) != NULL) {
        float expected_deg;
        int lag10;
        int lag20;
        int lag30;
        float estimate_deg;
        float err_deg;
        int parsed;

        if (line[0] == '#' || line[0] == '\n' || line[0] == '\r') {
            continue;
        }

        parsed = sscanf(line, " %f , %d , %d , %d", &expected_deg, &lag10, &lag20, &lag30);
        if (parsed != 4) {
            fprintf(stderr, "FAIL malformed fixture line: %s", line);
            failed += 1;
            continue;
        }

        estimate_deg = math_rad_to_compass_deg(doa4_estimate_from_lags(lag10, lag20, lag30));
        err_deg = angle_error_deg(expected_deg, estimate_deg);
        parsed_cases += 1;

        if (err_deg > tol_deg) {
            fprintf(stderr,
                    "FAIL fixture angle %.2f deg lags (%d,%d,%d) estimate %.2f deg err %.2f deg\n",
                    expected_deg,
                    lag10,
                    lag20,
                    lag30,
                    estimate_deg,
                    err_deg);
            failed += 1;
        }
    }

    fclose(fp);

    if (parsed_cases == 0) {
        fprintf(stderr, "FAIL fixture file has no valid test cases: %s\n", path);
        return failed + 1;
    }

    return failed;
}

int main(int argc, char **argv)
{
    const float tol_deg = 15.0f;
    const float cases[] = {0.0f, 45.0f, 90.0f, 135.0f, 180.0f, -45.0f, -90.0f, -135.0f};
    int failed = 0;
    unsigned i;

    if (argc > 2) {
        fprintf(stderr, "usage: %s [fixture_csv]\n", argv[0]);
        return 2;
    }

    if (argc == 2) {
        failed += run_fixture_file(argv[1], tol_deg);
    } else {
        for (i = 0; i < (sizeof(cases) / sizeof(cases[0])); i++) {
            failed += run_angle_case(cases[i], tol_deg);
            failed += run_lag_estimation_replica_case(cases[i], tol_deg);
        }
    }

    failed += run_channel_order_guard_case();

    if (failed != 0) {
        fprintf(stderr, "doa_from_lags_test: %d case(s) failed\n", failed);
        return 1;
    }

    printf("doa_from_lags_test: all cases passed\n");
    return 0;
}
