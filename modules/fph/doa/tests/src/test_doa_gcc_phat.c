#include "gcc_phat.h"

#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define PACKAGED_SYNC_WORD (0x7E57A55A)

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

static float compass_deg_to_math_deg(float compass_deg)
{
    return 90.0f - compass_deg;
}

static float math_rad_to_compass_deg(float math_rad)
{
    return 90.0f - rad_to_deg(math_rad);
}

static float angle_error_deg(float expected_deg, float actual_deg)
{
    return fabsf(wrap_deg(actual_deg - expected_deg));
}

static int parse_angles_csv(const char *csv, float *angles, int max_count)
{
    const char *p = csv;
    int count = 0;

    while (*p != '\0' && count < max_count) {
        char *endp;
        float value;

        while (*p == ' ' || *p == '\t') {
            ++p;
        }
        value = strtof(p, &endp);
        if (endp == p) {
            return -1;
        }
        angles[count++] = value;
        p = endp;

        while (*p == ' ' || *p == '\t') {
            ++p;
        }
        if (*p == ',') {
            ++p;
        } else if (*p != '\0') {
            return -1;
        }
    }

    return (*p == '\0') ? count : -1;
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
    const float a2y = -2.0f * r;
    const float a3x = -r;
    const float a3y = -r;

    *lag10 = (int) lroundf(fs_over_c * ((a1x * ux) + (a1y * uy)));
    *lag20 = (int) lroundf(fs_over_c * ((a2x * ux) + (a2y * uy)));
    *lag30 = (int) lroundf(fs_over_c * ((a3x * ux) + (a3y * uy)));
}

static void build_frame_from_lags(int *frame,
                                  int lag10,
                                  int lag20,
                                  int lag30)
{
    enum { AMP = 400000000, PULSE_COUNT = 4 };
    const int pulse_starts[PULSE_COUNT] = {24, 72, 128, 184};
    int m0[DOA4_FRAME_ADVANCE] = {0};
    int m1[DOA4_FRAME_ADVANCE] = {0};
    int m2[DOA4_FRAME_ADVANCE] = {0};
    int m3[DOA4_FRAME_ADVANCE] = {0};
    int p;

    for (p = 0; p < PULSE_COUNT; ++p) {
        int i0 = pulse_starts[p];
        int i1 = i0 + lag10;
        int i2 = i0 + lag20;
        int i3 = i0 + lag30;

        if (i0 >= 0 && i0 < DOA4_FRAME_ADVANCE) {
            m0[i0] = AMP;
        }
        if (i1 >= 0 && i1 < DOA4_FRAME_ADVANCE) {
            m1[i1] = AMP;
        }
        if (i2 >= 0 && i2 < DOA4_FRAME_ADVANCE) {
            m2[i2] = AMP;
        }
        if (i3 >= 0 && i3 < DOA4_FRAME_ADVANCE) {
            m3[i3] = AMP;
        }
    }

    memcpy(&frame[0 * DOA4_FRAME_ADVANCE], m0, sizeof(m0));
    memcpy(&frame[1 * DOA4_FRAME_ADVANCE], m1, sizeof(m1));
    memcpy(&frame[2 * DOA4_FRAME_ADVANCE], m2, sizeof(m2));
    memcpy(&frame[3 * DOA4_FRAME_ADVANCE], m3, sizeof(m3));
}

static int run_process_case(float expected_deg, float tol_deg)
{
    doa4_state_t state;
    int frame[DOA4_NUM_MICS * DOA4_FRAME_ADVANCE];
    int lag10;
    int lag20;
    int lag30;
    float out_deg;
    float err_deg;

    synthesize_lags_from_angle(expected_deg, &lag10, &lag20, &lag30);
    build_frame_from_lags(frame, lag10, lag20, lag30);

    doa4_init(&state);
    out_deg = math_rad_to_compass_deg(doa4_process_frame(&state, frame, 0));
    err_deg = angle_error_deg(expected_deg, out_deg);

    if (err_deg > tol_deg) {
        fprintf(stderr,
                "FAIL gcc_phat %.1f deg -> lags (%d,%d,%d) estimate %.2f deg err %.2f deg\n",
                expected_deg,
                lag10,
                lag20,
                lag30,
                out_deg,
                err_deg);
        return 1;
    }
    return 0;
}

static int run_channel_order_guard_case(void)
{
    doa4_state_t state;
    int frame[DOA4_NUM_MICS * DOA4_FRAME_ADVANCE];
    int swapped[DOA4_NUM_MICS * DOA4_FRAME_ADVANCE];
    int lag10;
    int lag20;
    int lag30;
    float out_deg;
    float err_deg;

    synthesize_lags_from_angle(45.0f, &lag10, &lag20, &lag30);
    build_frame_from_lags(frame, lag10, lag20, lag30);

    memcpy(swapped, frame, sizeof(swapped));
    memcpy(&swapped[1 * DOA4_FRAME_ADVANCE],
           &frame[3 * DOA4_FRAME_ADVANCE],
           DOA4_FRAME_ADVANCE * sizeof(int));
    memcpy(&swapped[3 * DOA4_FRAME_ADVANCE],
           &frame[1 * DOA4_FRAME_ADVANCE],
           DOA4_FRAME_ADVANCE * sizeof(int));

    doa4_init(&state);
    out_deg = math_rad_to_compass_deg(doa4_process_frame(&state, swapped, 0));
    err_deg = angle_error_deg(45.0f, out_deg);
    if (err_deg < 20.0f) {
        fprintf(stderr,
                "FAIL gcc_phat channel-order guard expected mismatch, got %.2f deg (err %.2f)\n",
                out_deg,
                err_deg);
        return 1;
    }
    return 0;
}

static uint32_t read_u32_le(const uint8_t *p)
{
    return ((uint32_t) p[0]) |
           ((uint32_t) p[1] << 8) |
           ((uint32_t) p[2] << 16) |
           ((uint32_t) p[3] << 24);
}

static uint16_t read_u16_le(const uint8_t *p)
{
    return (uint16_t) (((uint16_t) p[0]) | ((uint16_t) p[1] << 8));
}

static int read_packed_wav(const char *path, int32_t **samples, size_t *stereo_frames)
{
    FILE *fp;
    uint8_t hdr[12];
    int have_fmt = 0;
    int have_data = 0;
    uint16_t fmt_tag = 0;
    uint16_t channels = 0;
    uint16_t bits = 0;
    uint32_t sample_rate = 0;

    *samples = NULL;
    *stereo_frames = 0;

    fp = fopen(path, "rb");
    if (fp == NULL) {
        fprintf(stderr, "FAIL could not open wav: %s\n", path);
        return 1;
    }

    if (fread(hdr, 1, sizeof(hdr), fp) != sizeof(hdr)) {
        fprintf(stderr, "FAIL short wav header: %s\n", path);
        fclose(fp);
        return 1;
    }
    if (memcmp(&hdr[0], "RIFF", 4) != 0 || memcmp(&hdr[8], "WAVE", 4) != 0) {
        fprintf(stderr, "FAIL not a RIFF/WAVE file: %s\n", path);
        fclose(fp);
        return 1;
    }

    while (!have_data) {
        uint8_t chdr[8];
        uint32_t csize;
        if (fread(chdr, 1, sizeof(chdr), fp) != sizeof(chdr)) {
            break;
        }
        csize = read_u32_le(&chdr[4]);

        if (memcmp(&chdr[0], "fmt ", 4) == 0) {
            uint8_t *buf;
            if (csize < 16) {
                fprintf(stderr, "FAIL invalid fmt chunk in %s\n", path);
                fclose(fp);
                return 1;
            }
            buf = (uint8_t *) malloc(csize);
            if (buf == NULL) {
                fclose(fp);
                return 1;
            }
            if (fread(buf, 1, csize, fp) != csize) {
                free(buf);
                fclose(fp);
                return 1;
            }
            fmt_tag = read_u16_le(&buf[0]);
            channels = read_u16_le(&buf[2]);
            sample_rate = read_u32_le(&buf[4]);
            bits = read_u16_le(&buf[14]);
            free(buf);
            have_fmt = 1;
        } else if (memcmp(&chdr[0], "data", 4) == 0) {
            int32_t *buf;
            size_t data_bytes = csize;
            size_t read_bytes;
            if ((data_bytes % (2 * sizeof(int32_t))) != 0) {
                fprintf(stderr, "FAIL unsupported data length in %s\n", path);
                fclose(fp);
                return 1;
            }
            buf = (int32_t *) malloc(data_bytes);
            if (buf == NULL) {
                fclose(fp);
                return 1;
            }
            read_bytes = fread(buf, 1, data_bytes, fp);
            if (read_bytes != data_bytes) {
                free(buf);
                fclose(fp);
                return 1;
            }
            *samples = buf;
            *stereo_frames = data_bytes / (2 * sizeof(int32_t));
            have_data = 1;
        } else {
            if (fseek(fp, (long) csize, SEEK_CUR) != 0) {
                fclose(fp);
                return 1;
            }
        }

        if ((csize & 1U) != 0U) {
            if (fseek(fp, 1, SEEK_CUR) != 0) {
                fclose(fp);
                return 1;
            }
        }
    }

    fclose(fp);

    if (!have_fmt || !have_data) {
        fprintf(stderr, "FAIL missing fmt/data chunk in %s\n", path);
        free(*samples);
        *samples = NULL;
        return 1;
    }
    if (fmt_tag != 1 || channels != 2 || sample_rate != 48000U || bits != 32) {
        fprintf(stderr,
                "FAIL expected PCM s32le stereo 48k, got fmt=%u ch=%u rate=%u bits=%u\n",
                (unsigned) fmt_tag,
                (unsigned) channels,
                (unsigned) sample_rate,
                (unsigned) bits);
        free(*samples);
        *samples = NULL;
        return 1;
    }
    return 0;
}

static int run_wav_mode(const char *wav_path,
                        const float *angles,
                        int angle_count,
                        float segment_s,
                        float tol_deg)
{
    int32_t *stereo = NULL;
    size_t stereo_frames = 0;
    size_t sample_count_16k;
    int32_t *gen_n = NULL;
    int32_t *gen_e = NULL;
    int32_t *gen_s = NULL;
    int32_t *gen_w = NULL;
    int32_t *gen_expected_mrad = NULL;
    size_t i;
    doa4_state_t state;
    double seg_sum_err[128] = {0.0};
    double seg_sum_sin[128] = {0.0};
    double seg_sum_cos[128] = {0.0};
    int seg_count[128] = {0};
    size_t seg_start[128] = {0};
    size_t seg_end[128] = {0};
    float seg_expected_deg[128] = {0.0f};
    int failed = 0;
    const float settle_s = 0.30f;
    size_t settle_samples;
    size_t total_samples_target = 0;
    size_t frame_count;
    int seg_total = 0;

    if (angle_count > 128) {
        fprintf(stderr, "FAIL invalid angle count for wav mode\n");
        return 1;
    }

    if (read_packed_wav(wav_path, &stereo, &stereo_frames) != 0) {
        return 1;
    }

    sample_count_16k = stereo_frames / 3;
    settle_samples = (size_t) lroundf(settle_s * DOA4_SAMPLE_RATE_HZ);

    gen_n = (int32_t *) calloc(sample_count_16k, sizeof(int32_t));
    gen_e = (int32_t *) calloc(sample_count_16k, sizeof(int32_t));
    gen_s = (int32_t *) calloc(sample_count_16k, sizeof(int32_t));
    gen_w = (int32_t *) calloc(sample_count_16k, sizeof(int32_t));
    gen_expected_mrad = (int32_t *) calloc(sample_count_16k, sizeof(int32_t));
    if (gen_n == NULL || gen_e == NULL || gen_s == NULL || gen_w == NULL || gen_expected_mrad == NULL) {
        free(stereo);
        free(gen_n);
        free(gen_e);
        free(gen_s);
        free(gen_w);
        free(gen_expected_mrad);
        return 1;
    }

    for (i = 0; i < sample_count_16k; ++i) {
        int32_t left_sync = stereo[(3 * i + 0) * 2 + 0];
        int32_t left_l1 = stereo[(3 * i + 1) * 2 + 0];
        int32_t left_l2 = stereo[(3 * i + 2) * 2 + 0];
        int32_t right_l3 = stereo[(3 * i + 0) * 2 + 1];
        int32_t right_l4 = stereo[(3 * i + 1) * 2 + 1];
        int32_t right_l5 = stereo[(3 * i + 2) * 2 + 1];

        if ((uint32_t) left_sync != (uint32_t) PACKAGED_SYNC_WORD) {
            if (i < 5) {
                fprintf(stderr,
                        "WARN sync mismatch at sample %lu: got 0x%08x\n",
                        (unsigned long) i,
                        (unsigned) left_sync);
            }
        }

        gen_n[i] = left_l1;
        gen_e[i] = left_l2;
        gen_s[i] = right_l3;
        gen_w[i] = right_l4;
        gen_expected_mrad[i] = right_l5;
    }

    if (angle_count > 0) {
        size_t seg_idx;
        if (segment_s <= 0.0f) {
            fprintf(stderr, "FAIL --segment-s must be > 0 when --angles-deg is used\n");
            free(stereo);
            free(gen_n);
            free(gen_e);
            free(gen_s);
            free(gen_w);
            free(gen_expected_mrad);
            return 1;
        }
        total_samples_target = (size_t) lroundf((float) angle_count * segment_s * DOA4_SAMPLE_RATE_HZ);
        if (sample_count_16k < total_samples_target) {
            fprintf(stderr,
                    "WARN wav shorter than requested schedule (%lu < %lu samples at 16k)\n",
                    (unsigned long) sample_count_16k,
                    (unsigned long) total_samples_target);
        }
        seg_total = angle_count;
        for (seg_idx = 0; seg_idx < (size_t) seg_total; ++seg_idx) {
            seg_start[seg_idx] = (size_t) lroundf(((float) seg_idx) * segment_s * DOA4_SAMPLE_RATE_HZ);
            seg_end[seg_idx] = (size_t) lroundf(((float) (seg_idx + 1)) * segment_s * DOA4_SAMPLE_RATE_HZ);
            seg_expected_deg[seg_idx] = angles[seg_idx];
        }
    } else {
        size_t s0 = 0;
        while (s0 < sample_count_16k && seg_total < 128) {
            size_t s1 = s0 + 1;
            int32_t m0 = gen_expected_mrad[s0];
            while (s1 < sample_count_16k && gen_expected_mrad[s1] == m0) {
                ++s1;
            }
            seg_start[seg_total] = s0;
            seg_end[seg_total] = s1;
            seg_expected_deg[seg_total] = rad_to_deg(((float) m0) / 1000.0f);
            seg_total += 1;
            s0 = s1;
        }
        total_samples_target = sample_count_16k;
        if (seg_total <= 0) {
            fprintf(stderr, "FAIL could not derive expected-angle segments from lane 5\n");
            free(stereo);
            free(gen_n);
            free(gen_e);
            free(gen_s);
            free(gen_w);
            free(gen_expected_mrad);
            return 1;
        }
    }

    doa4_init(&state);
    frame_count = sample_count_16k / DOA4_FRAME_ADVANCE;
    for (i = 0; i < frame_count; ++i) {
        int frame[DOA4_NUM_MICS * DOA4_FRAME_ADVANCE];
        size_t base = i * DOA4_FRAME_ADVANCE;
        size_t center = base + (DOA4_FRAME_ADVANCE / 2);
        int seg_idx = -1;
        float out_deg;
        float err_deg;
        int n;
        int s;

        if (center >= total_samples_target) {
            break;
        }

        for (s = 0; s < seg_total; ++s) {
            if (seg_start[s] <= center && center < seg_end[s]) {
                seg_idx = s;
                break;
            }
        }
        if (seg_idx < 0) {
            continue;
        }
        if (center < (seg_start[seg_idx] + settle_samples)) {
            continue;
        }
        if ((center + settle_samples) >= seg_end[seg_idx]) {
            continue;
        }

        for (n = 0; n < DOA4_FRAME_ADVANCE; ++n) {
            size_t idx = base + (size_t) n;
            /* Estimator order expected by gcc_phat.c: [N, E, S, W]. */
            frame[0 * DOA4_FRAME_ADVANCE + n] = (int) gen_n[idx];
            frame[1 * DOA4_FRAME_ADVANCE + n] = (int) gen_e[idx];
            frame[2 * DOA4_FRAME_ADVANCE + n] = (int) gen_s[idx];
            frame[3 * DOA4_FRAME_ADVANCE + n] = (int) gen_w[idx];
        }

        out_deg = math_rad_to_compass_deg(doa4_process_frame(&state, frame, 0));
        err_deg = angle_error_deg(seg_expected_deg[seg_idx], out_deg);
        seg_sum_err[seg_idx] += (double) err_deg;
        seg_sum_sin[seg_idx] += sin((double) deg_to_rad(out_deg));
        seg_sum_cos[seg_idx] += cos((double) deg_to_rad(out_deg));
        seg_count[seg_idx] += 1;
    }

    for (i = 0; i < (size_t) seg_total; ++i) {
        if (seg_count[i] == 0) {
            fprintf(stderr, "FAIL wav segment %lu has no evaluated frames\n", (unsigned long) i);
            failed += 1;
            continue;
        }
        {
            float mean_est_deg = rad_to_deg((float) atan2(seg_sum_sin[i], seg_sum_cos[i]));
            float mean_err = (float) (seg_sum_err[i] / (double) seg_count[i]);
            printf("SEGMENT_RESULT idx=%lu expected_deg=%.3f mean_est_deg=%.3f mean_err_deg=%.3f frames=%d\n",
                   (unsigned long) i,
                   seg_expected_deg[i],
                   mean_est_deg,
                   mean_err,
                   seg_count[i]);
            if (mean_err > tol_deg) {
                fprintf(stderr,
                        "FAIL wav segment %lu expected %.1f deg mean_err %.2f deg (frames=%d)\n",
                        (unsigned long) i,
                        seg_expected_deg[i],
                        mean_err,
                        seg_count[i]);
                failed += 1;
            }
        }
    }

    free(stereo);
    free(gen_n);
    free(gen_e);
    free(gen_s);
    free(gen_w);
    free(gen_expected_mrad);
    return failed;
}

static void print_usage(const char *argv0)
{
    fprintf(stderr,
            "usage: %s [--wav path [--angles-deg csv --segment-s sec]]\n",
            argv0);
}

int main(int argc, char **argv)
{
    const float tol_deg = 20.0f;
    const float cases[] = {0.0f, 45.0f, 90.0f, 135.0f, 180.0f, -45.0f, -90.0f, -135.0f};
    int failed = 0;
    unsigned i;
    const char *wav_path = NULL;
    const char *angles_csv = NULL;
    float segment_s = 0.0f;

    if (argc > 1) {
        int argi;
        for (argi = 1; argi < argc; ++argi) {
            if (strcmp(argv[argi], "--wav") == 0 && (argi + 1) < argc) {
                wav_path = argv[++argi];
            } else if (strcmp(argv[argi], "--angles-deg") == 0 && (argi + 1) < argc) {
                angles_csv = argv[++argi];
            } else if (strcmp(argv[argi], "--segment-s") == 0 && (argi + 1) < argc) {
                segment_s = strtof(argv[++argi], NULL);
            } else {
                print_usage(argv[0]);
                return 2;
            }
        }
    }

    if (wav_path != NULL) {
        float angles[128];
        int angle_count = 0;

        if ((angles_csv != NULL) || (segment_s > 0.0f)) {
            if (angles_csv == NULL || segment_s <= 0.0f) {
                print_usage(argv[0]);
                return 2;
            }
            angle_count = parse_angles_csv(angles_csv, angles, 128);
            if (angle_count <= 0) {
                fprintf(stderr, "FAIL could not parse --angles-deg\n");
                return 1;
            }
        }

        failed += run_wav_mode(wav_path, angles, angle_count, segment_s, tol_deg);
        if (failed != 0) {
            fprintf(stderr, "doa_gcc_phat_test (wav mode): %d failure(s)\n", failed);
            return 1;
        }
        printf("doa_gcc_phat_test (wav mode): all cases passed\n");
        return 0;
    }

    for (i = 0; i < (sizeof(cases) / sizeof(cases[0])); ++i) {
        failed += run_process_case(cases[i], tol_deg);
    }

    failed += run_channel_order_guard_case();

    if (failed != 0) {
        fprintf(stderr, "doa_gcc_phat_test: %d case(s) failed\n", failed);
        return 1;
    }

    printf("doa_gcc_phat_test: all cases passed\n");
    return 0;
}
