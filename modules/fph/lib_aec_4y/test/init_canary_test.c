// Copyright 2026 Future Proof Homes
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "aec.h"
#include "aec_schedule_4y.h"

#define CANARY UINT64_C(0x8a4c2d19f6e735b0)
#define FRAMES 8
#define CHECK(c) do { if (!(c)) { printf("AEC check failed at line %d: %s\n", __LINE__, #c); return 1; } } while (0)
_Static_assert(AEC_MAX_Y_CHANNELS == 4 && AEC_MAX_X_CHANNELS == 1, "4Y1X ABI");
_Static_assert(AEC_MAIN_FILTER_PHASES == 10 && AEC_SHADOW_FILTER_PHASES == 5, "10/5 phases");

void aec_serial_reference(aec_filter_state_t *, aec_filter_state_t *,
    int32_t (*)[AEC_FRAME_ADVANCE], int32_t (*)[AEC_FRAME_ADVANCE],
    const int32_t (*)[AEC_FRAME_ADVANCE], const int32_t (*)[AEC_FRAME_ADVANCE]);

static struct {
    uint64_t before;
    aec_state_t state;
    uint64_t after;
} DWORD_ALIGNED guarded;
static int32_t DWORD_ALIGNED y[4][AEC_FRAME_ADVANCE], x[1][AEC_FRAME_ADVANCE];
static int32_t DWORD_ALIGNED output[4][AEC_FRAME_ADVANCE], shadow[4][AEC_FRAME_ADVANCE];
static int32_t expected[FRAMES][2][4][AEC_FRAME_ADVANCE];

static int check_schedule(void)
{
    const aec_task_distribution_t *s = &aec_tdist_chans4_threads1;
    CHECK(s->thread_count == 1);
    const aec_par_tasks_and_channels_t *groups[] = {
        s->par_1_tasks_and_channels[0], s->par_2_tasks_and_channels[0],
        s->par_3_tasks_and_channels[0]};
    unsigned passes[] = {s->passes_for_1_tasks_and_channels,
        s->passes_for_2_tasks_and_channels, s->passes_for_3_tasks_and_channels};
    for (unsigned tasks = 1; tasks <= 3; ++tasks) {
        unsigned seen[3][4] = {{0}};
        CHECK(passes[tasks - 1] == tasks * 4);
        for (unsigned i = 0; i < passes[tasks - 1]; ++i) {
            aec_par_tasks_and_channels_t e = groups[tasks - 1][i];
            CHECK(e.task >= 0 && e.task < tasks && e.channel >= 0 && e.channel < 4 && e.is_active == 1);
            ++seen[e.task][e.channel];
        }
        for (unsigned t = 0; t < tasks; ++t)
            for (unsigned ch = 0; ch < 4; ++ch) CHECK(seen[t][ch] == 1);
    }
    CHECK(s->passes_for_2_tasks == 2 && s->passes_for_3_tasks == 3);
    for (unsigned i = 0; i < 2; ++i)
        CHECK(s->par_2_tasks[0][i].task == i && s->par_2_tasks[0][i].is_active == 1);
    for (unsigned i = 0; i < 3; ++i)
        CHECK(s->par_3_tasks[0][i].task == i && s->par_3_tasks[0][i].is_active == 1);
    return 0;
}

static int check_invalid_init(void)
{
    const unsigned invalid[][4] = {
        {0,1,10,5}, {5,1,10,5}, {4,0,10,5}, {4,2,10,5},
        {4,1,0,5}, {4,1,11,5}, {4,1,10,0}, {4,1,10,6}, {4,1,1,5}};
    for (unsigned i = 0; i < sizeof(invalid) / sizeof(invalid[0]); ++i) {
        memset(&guarded, 0xa5, sizeof(guarded));
        aec_init(&guarded.state, invalid[i][0], invalid[i][1], invalid[i][2],
            invalid[i][3], &aec_tdist_chans4_threads1);
        const unsigned char *bytes = (const unsigned char *)&guarded;
        for (unsigned j = 0; j < sizeof(guarded); ++j) CHECK(bytes[j] == 0xa5);
    }
    aec_init(NULL, 4, 1, 10, 5, &aec_tdist_chans4_threads1);
    aec_init(&guarded.state, 4, 1, 10, 5, NULL);
    const unsigned char *bytes = (const unsigned char *)&guarded;
    for (unsigned j = 0; j < sizeof(guarded); ++j) CHECK(bytes[j] == 0xa5);
    return 0;
}

static int check_frames(int with_shadow)
{
    for (unsigned scheduled = 0; scheduled < 2; ++scheduled) {
        memset(&guarded, 0, sizeof(guarded));
        guarded.before = guarded.after = CANARY;
        aec_state_t *s = &guarded.state;
        aec_init(s, 4, 1, 10, 5, &aec_tdist_chans4_threads1);
        CHECK(s->shared_state.num_y_channels == 4 && s->shared_state.num_x_channels == 1);
        CHECK(s->main_state.shared_state == &s->shared_state && s->shadow_state.shared_state == &s->shared_state);
        CHECK(s->shared_state.tdist == &aec_tdist_chans4_threads1);
        CHECK((uint8_t *)(s->main_state.overlap[3].data + 32) == (uint8_t *)(&s->main_mem_pool + 1));
        CHECK((uint8_t *)(s->shadow_state.overlap[3].data + 32) == (uint8_t *)(&s->shadow_mem_pool + 1));
        for (unsigned f = 0; f < FRAMES; ++f) {
            for (unsigned i = 0; i < AEC_FRAME_ADVANCE; ++i) {
                unsigned sample = f * AEC_FRAME_ADVANCE + i;
                x[0][i] = f == 4 ? 0 : (int32_t)((sample * 7919u) % 100003u) * 1024;
                for (unsigned ch = 0; ch < 4; ++ch)
                    y[ch][i] = (int32_t)(((sample + ch * 97u) * 3571u) % 100019u) * 512;
            }
            memset(output, 0xa5, sizeof(output));
            memset(shadow, 0xa5, sizeof(shadow));
            if (scheduled) aec_process_frame(s, output, with_shadow ? shadow : NULL, y, x);
            else aec_serial_reference(&s->main_state, &s->shadow_state,
                output, with_shadow ? shadow : NULL, y, x);
            CHECK(guarded.before == CANARY && guarded.after == CANARY);
            if (scheduled) {
                CHECK(memcmp(output, expected[f][0], sizeof(output)) == 0);
                CHECK(memcmp(shadow, expected[f][1], sizeof(shadow)) == 0);
            } else {
                memcpy(expected[f][0], output, sizeof(output));
                memcpy(expected[f][1], shadow, sizeof(shadow));
            }
        }
        CHECK(memcmp(output[0], output[3], sizeof(output[0])) != 0);
        aec_reset_state(s);
        CHECK(guarded.before == CANARY && guarded.after == CANARY);
    }
    return 0;
}

int main(void)
{
    CHECK(check_schedule() == 0);
    CHECK(check_invalid_init() == 0);
    CHECK(check_frames(1) == 0);
    CHECK(check_frames(0) == 0);
    printf("4Y1X AEC: canaries, pools, bounds, schedule and 32 reference/scheduled frames passed\n");
    printf("AEC state=%u main_pool=%u shadow_pool=%u\n", (unsigned)sizeof(aec_state_t),
        (unsigned)sizeof(aec_memory_pool_t), (unsigned)sizeof(aec_shadow_filt_memory_pool_t));
    return 0;
}
