// Copyright 2026 Future Proof Homes
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "aec.h"
#include "aec_schedule_4y.h"
#include "aec_main_only_control.h"

#define CANARY 0x8a4c2d19f6e735b0ULL
#define CHECK(c) do { if (!(c)) { printf("line %d: %s\n", __LINE__, #c); return 1; } } while (0)
static struct {
    uint64_t before;
    aec_state_t state;
    uint64_t after;
} DWORD_ALIGNED guarded;
static int32_t DWORD_ALIGNED y[4][AEC_FRAME_ADVANCE], x[2][AEC_FRAME_ADVANCE];
static int32_t DWORD_ALIGNED output[4][AEC_FRAME_ADVANCE], shadow[4][AEC_FRAME_ADVANCE];
static uint32_t hashes[3][4];

static int canaries(void) {
    CHECK(guarded.before == CANARY && guarded.after == CANARY);
    return 0;
}

static int initialize(void) {
    memset(&guarded, 0, sizeof(guarded));
    guarded.before = guarded.after = CANARY;
    aec_init(&guarded.state, 4, 2, 10, 0, &aec_tdist_chans4_threads1);
    CHECK(guarded.state.shared_state.num_y_channels == 4);
    CHECK(guarded.state.shared_state.num_x_channels == 2);
    CHECK(guarded.state.shared_state.tdist == &aec_tdist_chans4_threads1);
    CHECK(guarded.state.main_state.num_phases == 10);
    CHECK((uint8_t *)(guarded.state.main_state.overlap[3].data + 32) ==
            (uint8_t *)(&guarded.state.main_mem_pool + 1));
    CHECK(canaries() == 0);
    return 0;
}

static int invalid_init(void) {
    const unsigned bounds[][4] = {
        {0,2,10,0}, {5,2,10,0}, {4,0,10,0}, {4,3,10,0},
        {4,2,0,0}, {4,2,11,0}, {4,2,10,1},
    };
    for (unsigned i = 0; i < sizeof(bounds)/sizeof(bounds[0]); ++i) {
        memset(&guarded, 0xa5, sizeof(guarded));
        aec_init(&guarded.state, bounds[i][0], bounds[i][1], bounds[i][2], bounds[i][3], &aec_tdist_chans4_threads1);
        const unsigned char *p = (const unsigned char *)&guarded;
        for (unsigned j = 0; j < sizeof(guarded); ++j) CHECK(p[j] == 0xa5);
    }
    /* Dummy non-null arguments must be rejected before even being dereferenced. */
    aec_filter_state_t *dummy = (aec_filter_state_t *)(uintptr_t)8;
    for (unsigned mode = 0; mode < 4; ++mode) {
        memset(&guarded, 0xa5, sizeof(guarded));
        CHECK(!aec_init_filters(&guarded.state.main_state, mode & 1 ? dummy : NULL,
            &guarded.state.shared_state, (uint8_t *)&guarded.state.main_mem_pool,
            mode & 2 ? (uint8_t *)(uintptr_t)8 : NULL,
            4, 2, 10, mode == 0 ? 1 : 0, &aec_tdist_chans4_threads1));
        const unsigned char *p = (const unsigned char *)&guarded;
        for (unsigned j = 0; j < sizeof(guarded); ++j) CHECK(p[j] == 0xa5);
    }
    return 0;
}

static int schedule(void) {
    const aec_task_distribution_t *s = &aec_tdist_chans4_threads1;
    const aec_par_tasks_and_channels_t *groups[] = {s->par_1_tasks_and_channels[0],
        s->par_2_tasks_and_channels[0], s->par_3_tasks_and_channels[0]};
    const unsigned passes[] = {s->passes_for_1_tasks_and_channels,
        s->passes_for_2_tasks_and_channels, s->passes_for_3_tasks_and_channels};
    CHECK(s->thread_count == 1);
    for (unsigned tasks = 1; tasks <= 3; ++tasks) {
        unsigned seen[3][4] = {{0}};
        CHECK(passes[tasks-1] == tasks * 4);
        for (unsigned i = 0; i < passes[tasks-1]; ++i) {
            aec_par_tasks_and_channels_t e = groups[tasks-1][i];
            CHECK(e.task >= 0 && e.task < tasks && e.channel >= 0 && e.channel < 4 && e.is_active);
            ++seen[e.task][e.channel];
        }
        for (unsigned t = 0; t < tasks; ++t)
            for (unsigned c = 0; c < 4; ++c) CHECK(seen[t][c] == 1);
    }
    return 0;
}

static int frames(void) {
    for (unsigned mode = 0; mode < 3; ++mode) {
        CHECK(initialize() == 0);
        uint32_t random = 17;
        for (unsigned frame = 0; frame < 24; ++frame) {
            for (unsigned i = 0; i < AEC_FRAME_ADVANCE; ++i) {
                random = random * 1664525u + 1013904223u;
                int32_t left = (int32_t)(random >> 8) - 8388608;
                random = random * 1664525u + 1013904223u;
                int32_t right = (int32_t)(random >> 8) - 8388608;
                x[0][i] = mode == 1 || frame == 12 ? 0 : left * 32;
                x[1][i] = mode == 2 || frame == 12 ? 0 : right * 32;
                for (unsigned c = 0; c < 4; ++c) y[c][i] = left * (4+c) + right * (8-c);
            }
            memset(shadow, 0xa5, sizeof(shadow));
            aec_process_frame(&guarded.state, output, frame & 1 ? shadow : NULL, y, x);
            CHECK(canaries() == 0);
            const unsigned char *p = (const unsigned char *)shadow;
            for (unsigned j = 0; j < sizeof(shadow); ++j) CHECK(p[j] == 0xa5);
        }
        for (unsigned c = 0; c < 4; ++c) {
            uint32_t h = 2166136261u;
            for (unsigned i = 0; i < AEC_FRAME_ADVANCE; ++i) h = (h ^ (uint32_t)output[c][i]) * 16777619u;
            hashes[mode][c] = h;
        }
        CHECK(aec_main_only_control_stats()->seen_reference_mask == (mode == 0 ? 3 : mode == 1 ? 2 : 1));
        aec_reset_state(&guarded.state);
        CHECK(canaries() == 0);
        CHECK(aec_main_only_control_stats()->seen_reference_mask == 0);
        for (unsigned c = 0; c < 4; ++c)
            for (unsigned ph = 0; ph < 20; ++ph)
                CHECK(guarded.state.main_state.H_hat[c][ph].exp == AEC_ZEROVAL_EXP);
    }
    for (unsigned c = 0; c < 4; ++c) {
        CHECK(hashes[0][c] != hashes[1][c]);
        CHECK(hashes[0][c] != hashes[2][c]);
    }
    return 0;
}

static int controller(void) {
    CHECK(initialize() == 0);
    aec_filter_state_t *main = &guarded.state.main_state;
    aec_shared_filter_state_t *shared = &guarded.state.shared_state;
    shared->sum_X_energy[0] = shared->sum_X_energy[1] = f64_to_float_s32(1.0);
    for (unsigned c = 0; c < 4; ++c) {
        shared->overall_Y[c] = f64_to_float_s32(1.0);
        main->overall_Error[c] = f64_to_float_s32(0.5);
    }
    aec_main_only_control_update(main);
    CHECK(aec_main_only_control_stats()->bootstrap_remaining[0] == 99);
    for (unsigned c = 0; c < 4; ++c) {
        shared->coh_mu_state[c].coh = f64_to_float_s32(0.9);
        main->overall_Error[c] = f64_to_float_s32(0.01);
    }
    for (unsigned i = 0; i < 5; ++i) aec_main_only_control_update(main);
    CHECK(aec_main_only_control_stats()->bootstrap_remaining[0] == 0);
    shared->overall_Y[0] = f64_to_float_s32(8.0);
    aec_main_only_control_update(main);
    CHECK(main->mu[0][0].mant == 0 && main->mu[0][1].mant == 0);
    shared->overall_Y[0] = f64_to_float_s32(1.0);
    main->overall_Error[0] = f64_to_float_s32(1.0);
    for (unsigned i = 0; i < 20; ++i) aec_main_only_control_update(main);
    CHECK(aec_main_only_control_stats()->reset_events[0] == 1);
    CHECK(aec_main_only_control_stats()->bootstrap_remaining[0] == 100);
    CHECK(main->mu[0][0].mant == 0 && main->mu[0][1].mant == 0);
    aec_reset_state(&guarded.state);
    CHECK(aec_main_only_control_stats()->reset_events[0] == 0);
    shared->sum_X_energy[0] = shared->sum_X_energy[1] = f64_to_float_s32(0.0);
    aec_main_only_control_update(main);
    CHECK(main->mu[0][0].mant == 0 && main->mu[0][1].mant == 0);
    for (unsigned c = 0; c < 4; ++c) {
        shared->overall_Y[c] = f64_to_float_s32(1.0);
        shared->coh_mu_state[c].coh = f64_to_float_s32(0.0);
        main->overall_Error[c] = f64_to_float_s32(0.5);
    }
    shared->sum_X_energy[0] = f64_to_float_s32(1.0);
    aec_main_only_control_update(main);
    CHECK(aec_main_only_control_stats()->bootstrap_remaining[0] == 99);
    CHECK(main->mu[0][1].mant == 0);
    shared->sum_X_energy[1] = f64_to_float_s32(1.0);
    aec_main_only_control_update(main);
    CHECK(aec_main_only_control_stats()->bootstrap_remaining[0] == 33);
    shared->sum_X_energy[0] = shared->sum_X_energy[1] = f64_to_float_s32(0.0);
    aec_main_only_control_update(main);
    shared->sum_X_energy[0] = shared->sum_X_energy[1] = f64_to_float_s32(1.0);
    aec_main_only_control_update(main);
    CHECK(aec_main_only_control_stats()->bootstrap_remaining[0] == 33);
    CHECK(aec_main_only_control_stats()->bootstrap_events[0] == 3);
    for (unsigned i = 0; i < 100; ++i) aec_main_only_control_update(main);
    CHECK(aec_main_only_control_stats()->bootstrap_events[0] >= 4);
    CHECK(aec_main_only_control_stats()->reset_events[0] == 0);
    return 0;
}

static int independent_lanes(void) {
    /* Anti-phase references have exactly zero mono mix. Distinct real filter
     * banks must nevertheless produce a nonzero echo estimate. */
    CHECK(initialize() == 0);
    for (unsigned c = 0; c < 4; ++c) {
        for (unsigned lane = 0; lane < 2; ++lane) {
            bfp_complex_s32_t *h = &guarded.state.main_state.H_hat[c][lane * 10];
            for (unsigned bin = 0; bin < AEC_FD_FRAME_LENGTH; ++bin) {
                h->data[bin].re = lane == 0 ? 268435456 : 536870912;
                h->data[bin].im = 0;
            }
            h->exp = -30;
            bfp_complex_s32_headroom(h);
        }
    }
    memset(y, 0, sizeof(y));
    for (unsigned i = 0; i < AEC_FRAME_ADVANCE; ++i) {
        x[0][i] = (i & 1) ? 33554432 : -33554432;
        x[1][i] = -x[0][i];
    }
    aec_process_frame(&guarded.state, output, NULL, y, x);
    for (unsigned c = 0; c < 4; ++c) {
        int nonzero = 0;
        for (unsigned i = 0; i < AEC_FRAME_ADVANCE; ++i)
            if (output[c][i] > 1024 || output[c][i] < -1024) nonzero = 1;
        CHECK(nonzero);
    }
    CHECK(canaries() == 0);
    return 0;
}

int main(void) {
    CHECK(AEC_LIB_MAX_PHASES == 20 && AEC_SHADOW_FILTER_PHASES == 0);
    CHECK(invalid_init() == 0);
    CHECK(schedule() == 0);
    CHECK(frames() == 0);
    CHECK(controller() == 0);
    CHECK(independent_lanes() == 0);
    printf("4Y2X main-only: null-shadow bounds/canaries/reset, schedule, 72 frames, separate reference influence and controller passed\n");
    printf("AEC state=%u main_pool=%u controller=%u\n", (unsigned)sizeof(aec_state_t),
        (unsigned)sizeof(aec_memory_pool_t), (unsigned)sizeof(aec_main_only_control_t));
    return 0;
}
