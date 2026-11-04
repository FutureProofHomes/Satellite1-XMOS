// Copyright 2026 Future Proof Homes
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "aec.h"
#include "aec_schedule_4y.h"

#define CANARY 0x8a4c2d19f6e735b0ULL
#define FRAMES 8
#define CHECK(condition) do { \
    if (!(condition)) { \
        printf("AEC check failed at line %d: %s\n", __LINE__, #condition); \
        return 1; \
    } \
} while (0)

void aec_serial_reference(aec_filter_state_t *, aec_filter_state_t *,
        int32_t (*)[AEC_FRAME_ADVANCE], int32_t (*)[AEC_FRAME_ADVANCE],
        const int32_t (*)[AEC_FRAME_ADVANCE], const int32_t (*)[AEC_FRAME_ADVANCE]);

static struct {
    uint64_t before;
    aec_state_t state;
    uint64_t after;
} DWORD_ALIGNED guarded;
static int32_t DWORD_ALIGNED y[4][AEC_FRAME_ADVANCE];
static int32_t DWORD_ALIGNED x[1][AEC_FRAME_ADVANCE];
static int32_t DWORD_ALIGNED output[4][AEC_FRAME_ADVANCE];
static int32_t DWORD_ALIGNED shadow[4][AEC_FRAME_ADVANCE];
static uint32_t expected[FRAMES][2][4];

static uint32_t hash_samples(const int32_t *samples) {
    uint32_t hash = 2166136261u;
    for (unsigned i = 0; i < AEC_FRAME_ADVANCE; ++i) {
        hash = (hash ^ (uint32_t)samples[i]) * 16777619u;
    }
    return hash;
}

static void input_frame(unsigned frame) {
    for (unsigned i = 0; i < AEC_FRAME_ADVANCE; ++i) {
        unsigned sample = frame * AEC_FRAME_ADVANCE + i;
        x[0][i] = (frame == 4) ? 0 : (int32_t)((sample * 7919u) % 100003u) * 1024;
        for (unsigned ch = 0; ch < 4; ++ch) {
            y[ch][i] = (int32_t)(((sample + ch * 97u) * 3571u) % 100019u) * 512;
        }
    }
}

static int check_schedule(void) {
    const aec_task_distribution_t *s = &aec_tdist_chans4_threads1;
    CHECK(s->thread_count == 1);
    const aec_par_tasks_and_channels_t *groups[] = {
        s->par_1_tasks_and_channels[0], s->par_2_tasks_and_channels[0],
        s->par_3_tasks_and_channels[0],
    };
    const unsigned passes[] = {s->passes_for_1_tasks_and_channels,
        s->passes_for_2_tasks_and_channels, s->passes_for_3_tasks_and_channels};
    for (unsigned tasks = 1; tasks <= 3; ++tasks) {
        unsigned seen[3][4] = {{0}};
        CHECK(passes[tasks - 1] == tasks * 4);
        for (unsigned i = 0; i < passes[tasks - 1]; ++i) {
            aec_par_tasks_and_channels_t entry = groups[tasks - 1][i];
            CHECK(entry.task >= 0 && entry.task < tasks);
            CHECK(entry.channel >= 0 && entry.channel < 4 && entry.is_active == 1);
            ++seen[entry.task][entry.channel];
        }
        for (unsigned task = 0; task < tasks; ++task) {
            for (unsigned ch = 0; ch < 4; ++ch) CHECK(seen[task][ch] == 1);
        }
    }
    CHECK(s->passes_for_2_tasks == 2 && s->passes_for_3_tasks == 3);
    for (unsigned i = 0; i < 2; ++i) {
        CHECK(s->par_2_tasks[0][i].task == i && s->par_2_tasks[0][i].is_active == 1);
    }
    return 0;
}

static int check_invalid_init(void) {
    const unsigned invalid[][4] = {
        {0, 1, 10, 5}, {5, 1, 10, 5}, {4, 0, 10, 5}, {4, 2, 10, 5},
        {4, 1, 0, 5}, {4, 1, 11, 5}, {4, 1, 10, 0}, {4, 1, 10, 6},
    };
    for (unsigned i = 0; i < sizeof(invalid) / sizeof(invalid[0]); ++i) {
        memset(&guarded, 0xa5, sizeof(guarded));
        aec_init(&guarded.state, invalid[i][0], invalid[i][1], invalid[i][2],
                invalid[i][3], &aec_tdist_chans4_threads1);
        const unsigned char *bytes = (const unsigned char *)&guarded;
        for (unsigned j = 0; j < sizeof(guarded); ++j) CHECK(bytes[j] == 0xa5);
    }
    return 0;
}

static int check_frames(int with_shadow) {
    for (unsigned scheduled = 0; scheduled < 2; ++scheduled) {
        memset(&guarded, 0, sizeof(guarded));
        guarded.before = CANARY;
        guarded.after = CANARY;
        aec_state_t *state = &guarded.state;
        aec_init(state, 4, 1, 10, 5, &aec_tdist_chans4_threads1);
        CHECK(state->shared_state.num_y_channels == 4 && state->shared_state.num_x_channels == 1);
        CHECK(state->main_state.shared_state == &state->shared_state);
        CHECK(state->shadow_state.shared_state == &state->shared_state);
        CHECK(state->shared_state.tdist == &aec_tdist_chans4_threads1);
        CHECK((uint8_t *)(state->main_state.overlap[3].data + 32) ==
                (uint8_t *)(&state->main_mem_pool + 1));
        CHECK((uint8_t *)(state->shadow_state.overlap[3].data + 32) ==
                (uint8_t *)(&state->shadow_mem_pool + 1));
        for (unsigned frame = 0; frame < FRAMES; ++frame) {
            input_frame(frame);
            memset(output, 0xa5, sizeof(output));
            memset(shadow, 0xa5, sizeof(shadow));
            if (scheduled) {
                aec_process_frame(state, output, with_shadow ? shadow : NULL, y, x);
            } else {
                aec_serial_reference(&state->main_state, &state->shadow_state,
                        output, with_shadow ? shadow : NULL, y, x);
            }
            CHECK(guarded.before == CANARY && guarded.after == CANARY);
            for (unsigned ch = 0; ch < 4; ++ch) {
                uint32_t main_hash = hash_samples(output[ch]);
                uint32_t shadow_hash = hash_samples(shadow[ch]);
                if (scheduled) {
                    CHECK(main_hash == expected[frame][0][ch]);
                    CHECK(shadow_hash == expected[frame][1][ch]);
                } else {
                    expected[frame][0][ch] = main_hash;
                    expected[frame][1][ch] = shadow_hash;
                }
            }
        }
        CHECK(hash_samples(output[0]) != hash_samples(output[3]));
        aec_reset_state(state);
        CHECK(guarded.before == CANARY && guarded.after == CANARY);
    }
    return 0;
}

int main(void) {
    CHECK(check_schedule() == 0);
    CHECK(check_invalid_init() == 0);
    CHECK(check_frames(1) == 0);
    CHECK(check_frames(0) == 0);
    printf("4Y1X AEC: canaries, pools, bounds, schedule and 32 reference/scheduled frames passed\n");
    printf("AEC state=%u main_pool=%u shadow_pool=%u\n", (unsigned)sizeof(aec_state_t),
            (unsigned)sizeof(aec_memory_pool_t), (unsigned)sizeof(aec_shadow_filt_memory_pool_t));
    return 0;
}
