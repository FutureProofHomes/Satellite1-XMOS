#include "speaker_eq/speaker_eq.h"

#if SPEAKER_EQ_ACTIVE

#include <math.h>
#include <string.h>
#include <xcore/assert.h>
#include <xcore/hwtimer.h>

#include "FreeRTOS.h"
#include "task.h"

#include "control/adsp_control.h"
#include "dsp/adsp.h"
#include "rtos_macros.h"

#include "speaker_eq/speaker_eq_design.h"

#define EQ_FRAME_LEN            (appconfAUDIO_SPK_PIPELINE_FRAME_ADVANCE)
#define EQ_FS                   ((float)appconfI2S_AUDIO_SAMPLE_RATE)
#define EQ_BLOCK                16
#define EQ_FADE_LEN             128
#define EQ_FADE_SHIFT           7
#define EQ_COEFF_SLEW_SHIFT     4       /* per block: ~5 ms time constant */
#define EQ_GAIN_SLEW_SHIFT      7
#define EQ_UNITY_GAIN           (1 << Q_GAIN)
#define EQ_LIMITER_RECOVERED    (INT32_MAX - (INT32_MAX >> 9))
/* Frames in 10 s, which outlasts the 5 s longest release. */
#define EQ_LIMITER_TIMEOUT      ((10 * appconfI2S_AUDIO_SAMPLE_RATE + EQ_FRAME_LEN - 1) / EQ_FRAME_LEN)
#define EQ_TICKS_PER_US         (XS1_TIMER_HZ / 1000000)
#define EQ_BUDGET_US            4000
#define EQ_WATCHDOG_US          8000
#define EQ_WATCHDOG_FRAMES      3
#define EQ_STATS_WINDOW         (3 * appconfI2S_AUDIO_SAMPLE_RATE / (2 * EQ_FRAME_LEN))  /* 1.5 s */
#define EQ_DESIGN_PRIORITY      (appconfAUDIO_PIPELINE_TASK_PRIORITY - 2)

#define EQ_BARRIER()            __asm__ volatile("" ::: "memory")

_Static_assert(appconfAUDIO_SPK_CHANNELS == 2, "speaker EQ expects stereo frames");
_Static_assert(EQ_FRAME_LEN % EQ_BLOCK == 0, "frame must be whole blocks");
_Static_assert(EQ_FADE_LEN % EQ_BLOCK == 0 && EQ_FADE_LEN <= EQ_FRAME_LEN,
               "fade must be whole blocks within one frame");
_Static_assert((1 << EQ_FADE_SHIFT) == EQ_FADE_LEN, "fade shift mismatch");
_Static_assert(appconfI2S_AUDIO_SAMPLE_RATE >= 40000,
               "filters go up to 20 kHz, which must stay under Nyquist");

/* Written by the servicer, read by the design task. */
typedef struct {
    speaker_eq_slot_params_t params[SPEAKER_EQ_NUM_SLOTS];
    uint32_t params_gen[SPEAKER_EQ_NUM_SLOTS];
    uint8_t written[SPEAKER_EQ_NUM_SLOTS];
    uint8_t eq_enabled;
    uint8_t profile_id;
    uint8_t readback_slot;
} eq_ctrl_t;

/* Owned by the design task; status fields are also read by the servicer. */
typedef struct {
    speaker_eq_bank_t bank[SPEAKER_EQ_NUM_SLOTS];
    speaker_eq_analysis_t analysis[SPEAKER_EQ_NUM_SLOTS];
    uint32_t designed_gen[SPEAKER_EQ_NUM_SLOTS];
    uint8_t status[SPEAKER_EQ_NUM_SLOTS];
    uint8_t valid[SPEAKER_EQ_NUM_SLOTS];
    uint32_t count;
    uint32_t rejects;
    uint32_t us_last;
} eq_designs_t;

typedef struct {
    /* adsp_biquad reads 8 words; [5..7] stay zero. */
    int32_t coeffs[SPEAKER_EQ_MAX_SECTIONS][8] __attribute__((aligned(8)));
    int32_t state[SPEAKER_EQ_MAX_SECTIONS][8] __attribute__((aligned(8)));
    int32_t target[SPEAKER_EQ_MAX_SECTIONS][5];
    int8_t lsh[SPEAKER_EQ_MAX_SECTIONS];
    uint16_t section_id[SPEAKER_EQ_MAX_SECTIONS];
    int32_t fade[EQ_FADE_LEN];      /* the other side of a crossfade */
    limiter_t limiter;
    gain_slew_t pre_gain;
    gain_slew_t post_gain;
    uint32_t bank_seq;
    uint32_t limiter_wait;
    int32_t frame_min_lim_gain;
    int32_t min_lim_gain;
    uint8_t active;
    uint8_t num_sections;
    uint8_t coeff_slewing;
    uint8_t limiter_on;
    uint8_t limiter_required;

    uint32_t us_last;
    uint32_t us_max;
    uint32_t us_avg_x16;
    uint32_t window_frames;
    uint32_t window_limited;
    uint32_t limited_frames;
    uint8_t limiter_pct;
} eq_channel_t;

static eq_ctrl_t ctrl;
static eq_designs_t designs;
static TaskHandle_t design_task_handle;

/* Seqlock: odd while the design task is writing. */
static speaker_eq_bank_t shared_bank;
static volatile uint32_t shared_seq;
/* GET_INFO's copies of the last finished publish, so it never reads one half written. */
static volatile uint8_t published_limiter_required;
static volatile uint32_t published_seq;

/* Stage 0 owns the double buffer; stage 1 reads the half named in the tag. */
static speaker_eq_bank_t frame_bank[2];
static uint32_t stage0_seq;
static uint8_t stage0_index;
static volatile uint32_t ch1_seen_seq;

static eq_channel_t channels[2];
static volatile uint8_t current_reason = SPEAKER_EQ_BYPASS_DISABLED;
static uint32_t watchdog_seq;
static uint8_t watchdog_run;
static uint8_t watchdog_tripped;
static volatile uint8_t watchdog_trips;
static volatile uint32_t frames;
static volatile uint32_t overruns;

/* ---------------------------------------------------------------- stages */

static void limiter_load(eq_channel_t *c, const speaker_eq_bank_t *b, bool fresh)
{
    if (fresh) {
        c->limiter.env_det.envelope = 0;
        c->limiter.gain = INT32_MAX;
    }
    c->limiter.threshold = b->limiter_threshold;
    c->limiter.env_det.attack_alpha = b->attack_alpha;
    c->limiter.env_det.release_alpha = b->release_alpha;
}

/*
 * A running limiter keeps its envelope so a design change cannot overshoot.
 * It also takes the new ceiling and times when the new design no longer
 * needs it: the old ceiling could be far lower, and would hold the music
 * down until the timeout. Every active bank carries both.
 */
static void limiter_retarget(eq_channel_t *c, const speaker_eq_bank_t *b)
{
    if (b->limiter_required || c->limiter_on) {
        limiter_load(c, b, !c->limiter_on);
        c->limiter_on = 1;
    }
    c->limiter_required = b->limiter_required;
    c->limiter_wait = 0;
}

/* Loads a design with cleared filter state. */
static void channel_start(eq_channel_t *c, const speaker_eq_bank_t *b, uint32_t seq)
{
    for (unsigned i = 0; i < b->num_sections; i++) {
        memcpy(c->coeffs[i], b->coeffs[i], sizeof(b->coeffs[i]));
        memcpy(c->target[i], b->coeffs[i], sizeof(b->coeffs[i]));
        memset(c->state[i], 0, sizeof(c->state[i]));
        c->lsh[i] = b->lsh[i];
        c->section_id[i] = b->section_id[i];
    }
    c->num_sections = b->num_sections;
    c->coeff_slewing = 0;
    c->pre_gain = adsp_slew_gain_init(b->pre_gain, EQ_GAIN_SLEW_SHIFT);
    c->post_gain = adsp_slew_gain_init(b->post_gain, EQ_GAIN_SLEW_SHIFT);
    limiter_retarget(c, b);
    c->bank_seq = seq;
    c->active = 1;
}

/*
 * Coefficients only glide between versions of the same filters. Re-sorted
 * or added sections would glide between unrelated filters, so those changes
 * crossfade instead.
 */
static bool channel_can_glide(const eq_channel_t *c, const speaker_eq_bank_t *b)
{
    if (b->num_sections != c->num_sections) {
        return false;
    }
    for (unsigned i = 0; i < b->num_sections; i++) {
        if (b->section_id[i] != c->section_id[i] || b->lsh[i] != c->lsh[i]) {
            return false;
        }
    }
    return true;
}

static void channel_glide(eq_channel_t *c, const speaker_eq_bank_t *b, uint32_t seq)
{
    for (unsigned i = 0; i < b->num_sections; i++) {
        memcpy(c->target[i], b->coeffs[i], sizeof(b->coeffs[i]));
    }
    c->coeff_slewing = 1;
    c->pre_gain.target_gain = b->pre_gain;
    c->post_gain.target_gain = b->post_gain;
    limiter_retarget(c, b);
    c->bank_seq = seq;
}

/*
 * Exponential slew, shifting before subtracting: -a1 can move by almost 4.0
 * in Q30, which overflows a plain difference (lib_audio_dsp's slew does that,
 * and a wrapped biquad can oscillate at full scale indefinitely).
 */
static void slew_coeffs(eq_channel_t *c)
{
    bool settled = true;

    for (unsigned i = 0; i < c->num_sections; i++) {
        for (unsigned j = 0; j < 5; j++) {
            const int32_t step = (c->target[i][j] >> EQ_COEFF_SLEW_SHIFT) -
                                 (c->coeffs[i][j] >> EQ_COEFF_SLEW_SHIFT);
            c->coeffs[i][j] += step;
            settled = settled && step == 0;
        }
    }
    if (settled) {
        for (unsigned i = 0; i < c->num_sections; i++) {
            memcpy(c->coeffs[i], c->target[i], sizeof(c->target[i]));
        }
        c->coeff_slewing = 0;
    }
}

static void apply_gain(gain_slew_t *g, int32_t *x, unsigned n)
{
    if (g->gain == g->target_gain) {
        if (g->gain != EQ_UNITY_GAIN) {
            for (unsigned k = 0; k < n; k++) {
                x[k] = adsp_fixed_gain(x[k], g->gain);
            }
        }
        return;
    }
    for (unsigned k = 0; k < n; k++) {
        x[k] = adsp_fixed_gain(x[k], adsp_slew_gain(g));
    }
    const int32_t diff = g->target_gain - g->gain;
    if (diff < (1 << g->slew_shift) && diff > -(1 << g->slew_shift)) {
        g->gain = g->target_gain;
    }
}

static void run_chain(eq_channel_t *c, int32_t *x, unsigned len)
{
    for (unsigned k = 0; k < len; k++) {
        x[k] = adsp_from_q31(x[k]);
    }

    for (unsigned blk = 0; blk < len; blk += EQ_BLOCK) {
        int32_t *b = &x[blk];

        if (c->coeff_slewing) {
            slew_coeffs(c);
        }

        apply_gain(&c->pre_gain, b, EQ_BLOCK);

        for (unsigned i = 0; i < c->num_sections; i++) {
            int32_t *coeffs = c->coeffs[i];
            int32_t *state = c->state[i];
            const left_shift_t lsh = c->lsh[i];
            for (unsigned k = 0; k < EQ_BLOCK; k++) {
                b[k] = adsp_biquad(b[k], coeffs, state, lsh);
            }
        }

        apply_gain(&c->post_gain, b, EQ_BLOCK);

        if (c->limiter_on) {
            for (unsigned k = 0; k < EQ_BLOCK; k++) {
                b[k] = adsp_hard_limiter_peak(&c->limiter, b[k]);
            }
            if (c->limiter.gain < c->frame_min_lim_gain) {
                c->frame_min_lim_gain = c->limiter.gain;
            }
        }
    }

    for (unsigned k = 0; k < len; k++) {
        x[k] = adsp_to_q31(x[k]);
    }
}

static inline int32_t crossfade(int32_t from, int32_t to, unsigned n)
{
    const int64_t acc = (int64_t)from * (int64_t)(EQ_FADE_LEN - n) + (int64_t)to * (int64_t)n;
    return (int32_t)(acc >> EQ_FADE_SHIFT);
}

static void channel_limiter_stats(eq_channel_t *c)
{
    const bool limited = c->frame_min_lim_gain < EQ_LIMITER_RECOVERED;

    if (c->frame_min_lim_gain < c->min_lim_gain) {
        c->min_lim_gain = c->frame_min_lim_gain;
    }
    if (limited) {
        c->window_limited++;
        c->limited_frames++;
    }
    if (++c->window_frames >= EQ_STATS_WINDOW) {
        c->limiter_pct = (uint8_t)((c->window_limited * 100) / c->window_frames);
        c->window_frames = 0;
        c->window_limited = 0;
    }
}

static void process_channel(eq_channel_t *c,
                            int32_t *x,
                            const speaker_eq_bank_t *b,
                            uint32_t seq,
                            bool active)
{
    c->frame_min_lim_gain = INT32_MAX;

    if (!c->active) {
        if (active) {
            channel_start(c, b, seq);
            memcpy(c->fade, x, sizeof(c->fade));
            run_chain(c, x, EQ_FRAME_LEN);
            for (unsigned n = 0; n < EQ_FADE_LEN; n++) {
                x[n] = crossfade(c->fade[n], x[n], n);
            }
        }
    } else if (!active) {
        /* Last wet block, faded out over the first 128 samples. */
        memcpy(c->fade, x, sizeof(c->fade));
        run_chain(c, c->fade, EQ_FADE_LEN);
        for (unsigned n = 0; n < EQ_FADE_LEN; n++) {
            x[n] = crossfade(c->fade[n], x[n], n);
        }
        c->active = 0;
        c->limiter_on = 0;
    } else {
        if (seq == c->bank_seq) {
            run_chain(c, x, EQ_FRAME_LEN);
        } else if (channel_can_glide(c, b)) {
            channel_glide(c, b, seq);
            run_chain(c, x, EQ_FRAME_LEN);
        } else {
            /* Old chain for the fade window, crossfaded into the new one. */
            memcpy(c->fade, x, sizeof(c->fade));
            run_chain(c, c->fade, EQ_FADE_LEN);
            channel_start(c, b, seq);
            run_chain(c, x, EQ_FRAME_LEN);
            for (unsigned n = 0; n < EQ_FADE_LEN; n++) {
                x[n] = crossfade(c->fade[n], x[n], n);
            }
        }
        if (c->limiter_on && !c->limiter_required) {
            if (c->limiter.gain >= EQ_LIMITER_RECOVERED ||
                ++c->limiter_wait >= EQ_LIMITER_TIMEOUT) {
                c->limiter_on = 0;
            }
        }
    }

    channel_limiter_stats(c);
}

static void channel_timing(eq_channel_t *c, uint32_t t0)
{
    const uint32_t us = (get_reference_time() - t0) / EQ_TICKS_PER_US;

    c->us_last = us;
    if (us > c->us_max) {
        c->us_max = us;
    }
    c->us_avg_x16 += us - (c->us_avg_x16 >> 4);
}

static void adopt_shared_bank(void)
{
    const uint32_t seq = shared_seq;

    if (seq == stage0_seq || (seq & 1) || ch1_seen_seq != stage0_seq) {
        return;
    }

    const uint8_t next = stage0_index ^ 1;
    EQ_BARRIER();
    memcpy(&frame_bank[next], &shared_bank, sizeof(shared_bank));
    EQ_BARRIER();
    if (shared_seq != seq) {
        return;
    }
    stage0_index = next;
    stage0_seq = seq;
}

/* Channel 1's time is from the previous frame; good enough for a watchdog. */
static void watchdog_check(void)
{
    const uint32_t worst = channels[0].us_last > channels[1].us_last ?
                           channels[0].us_last : channels[1].us_last;

    if (worst > EQ_BUDGET_US) {
        overruns++;
    }
    if (worst > EQ_WATCHDOG_US) {
        if (++watchdog_run >= EQ_WATCHDOG_FRAMES &&
            !(watchdog_tripped && watchdog_seq == stage0_seq)) {
            watchdog_tripped = 1;
            watchdog_seq = stage0_seq;
            watchdog_trips++;
        }
    } else {
        watchdog_run = 0;
    }
}

void speaker_eq_process_ch0(int32_t *samples, speaker_eq_frame_tag_t *tag)
{
    const uint32_t t0 = get_reference_time();
    uint8_t reason;

    adopt_shared_bank();

    const speaker_eq_bank_t *b = &frame_bank[stage0_index];
    reason = b->active ? SPEAKER_EQ_BYPASS_NONE : b->reason;
    if (reason == SPEAKER_EQ_BYPASS_NONE &&
        watchdog_tripped && watchdog_seq == stage0_seq) {
        reason = SPEAKER_EQ_BYPASS_OVERLOAD;
    }
    current_reason = reason;

    tag->bank_seq = stage0_seq;
    tag->bank_index = stage0_index;
    tag->active = reason == SPEAKER_EQ_BYPASS_NONE;

    process_channel(&channels[0], samples, b, stage0_seq, tag->active);
    channel_timing(&channels[0], t0);
    watchdog_check();
}

void speaker_eq_process_ch1(int32_t *samples, const speaker_eq_frame_tag_t *tag)
{
    const uint32_t t0 = get_reference_time();

    process_channel(&channels[1], samples, &frame_bank[tag->bank_index],
                    tag->bank_seq, tag->active);
    EQ_BARRIER();
    ch1_seen_seq = tag->bank_seq;
    channel_timing(&channels[1], t0);
    frames++;
}

/* ----------------------------------------------------------- design task */

static void publish_bank(uint8_t enabled, uint8_t profile)
{
    const uint32_t seq = shared_seq;
    shared_seq = seq + 1;
    EQ_BARRIER();
    if (!enabled) {
        speaker_eq_bank_set_bypass(&shared_bank, SPEAKER_EQ_BYPASS_DISABLED);
    } else if (profile < 1 || profile > SPEAKER_EQ_NUM_SLOTS || !designs.valid[profile - 1]) {
        speaker_eq_bank_set_bypass(&shared_bank, SPEAKER_EQ_BYPASS_NO_PROFILE);
    } else {
        memcpy(&shared_bank, &designs.bank[profile - 1], sizeof(shared_bank));
    }
    EQ_BARRIER();
    shared_seq = seq + 2;
    published_limiter_required = shared_bank.limiter_required;
    published_seq = seq + 2;
}

static void design_task(void *arg)
{
    static speaker_eq_slot_params_t params;
    static uint8_t published_enabled = UINT8_MAX;
    static uint8_t published_profile = UINT8_MAX;

    (void)arg;

    for (;;) {
        unsigned redesigned = 0;
        uint8_t enabled, profile;

        for (unsigned s = 0; s < SPEAKER_EQ_NUM_SLOTS; s++) {
            speaker_eq_analysis_t analysis;
            uint32_t gen;
            bool fresh;

            taskENTER_CRITICAL();
            gen = ctrl.params_gen[s];
            fresh = gen != designs.designed_gen[s];
            if (fresh) {
                params = ctrl.params[s];
            }
            taskEXIT_CRITICAL();

            if (!fresh) {
                continue;
            }

            /* Only this task touches designs.bank; a rejected design leaves it intact. */
            const uint32_t t0 = get_reference_time();
            const bool ok = speaker_eq_design(&params, EQ_FS, &designs.bank[s], &analysis);
            const uint32_t us = (get_reference_time() - t0) / EQ_TICKS_PER_US;

            taskENTER_CRITICAL();
            designs.designed_gen[s] = gen;
            designs.analysis[s] = analysis;
            if (ok) {
                designs.valid[s] = 1;
                designs.status[s] = SPEAKER_EQ_SLOT_OK;
            } else {
                designs.status[s] = SPEAKER_EQ_SLOT_REJECTED_HEADROOM;
                designs.rejects++;
            }
            designs.count++;
            designs.us_last = us;
            taskEXIT_CRITICAL();

            if (ok) {
                redesigned |= 1u << s;
            }
        }

        /*
         * Only a change to what plays is published. Each publish clears the
         * overload bypass and restarts the limiter's timeout, so a write to
         * the other slot or a routing write that changes nothing must not.
         */
        taskENTER_CRITICAL();
        enabled = ctrl.eq_enabled;
        profile = ctrl.profile_id;
        taskEXIT_CRITICAL();
        const bool playing_redesigned = enabled && profile >= 1 &&
                                        profile <= SPEAKER_EQ_NUM_SLOTS &&
                                        (redesigned & (1u << (profile - 1)));
        if (playing_redesigned || enabled != published_enabled || profile != published_profile) {
            published_enabled = enabled;
            published_profile = profile;
            publish_bank(enabled, profile);
        }

        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
    }
}

static void notify_design_task(void)
{
    TaskHandle_t handle = design_task_handle;
    if (handle != NULL) {
        xTaskNotifyGive(handle);
    }
}

void speaker_eq_init(void)
{
    speaker_eq_bank_set_bypass(&shared_bank, SPEAKER_EQ_BYPASS_DISABLED);
    speaker_eq_bank_set_bypass(&frame_bank[0], SPEAKER_EQ_BYPASS_DISABLED);
    speaker_eq_bank_set_bypass(&frame_bank[1], SPEAKER_EQ_BYPASS_DISABLED);
    for (unsigned ch = 0; ch < 2; ch++) {
        channels[ch].min_lim_gain = INT32_MAX;
        channels[ch].frame_min_lim_gain = INT32_MAX;
    }

    const BaseType_t created = xTaskCreate(design_task,
                                           "spk_eq_design",
                                           configMINIMAL_STACK_SIZE + RTOS_THREAD_STACK_SIZE(design_task),
                                           NULL,
                                           EQ_DESIGN_PRIORITY,
                                           &design_task_handle);
    xassert(created == pdPASS);
    (void)created;
    /* Catches servicer writes that raced the handle assignment. */
    xTaskNotifyGive(design_task_handle);
}

/* --------------------------------------------------------- device control */

static void put_u16(uint8_t *p, uint32_t v)
{
    const uint16_t x = v > UINT16_MAX ? UINT16_MAX : (uint16_t)v;
    memcpy(p, &x, sizeof(x));
}

static void put_u32(uint8_t *p, uint32_t v)
{
    memcpy(p, &v, sizeof(v));
}

static void put_f32(uint8_t *p, float v)
{
    memcpy(p, &v, sizeof(v));
}

static bool write_routing(const uint8_t *payload, size_t len)
{
    if (len != SPEAKER_EQ_ROUTING_BYTES || payload[0] > 1 ||
        payload[1] >= SPEAKER_EQ_NUM_PROFILES) {
        return false;
    }

    taskENTER_CRITICAL();
    ctrl.eq_enabled = payload[0];
    ctrl.profile_id = payload[1];
    taskEXIT_CRITICAL();
    notify_design_task();
    return true;
}

static bool write_slot(const uint8_t *payload, size_t len)
{
    speaker_eq_slot_params_t params;
    uint8_t slot;

    if (len != SPEAKER_EQ_SLOT_BYTES) {
        return false;
    }
    if (!speaker_eq_decode_slot(payload, &slot, &params)) {
        return false;
    }

    taskENTER_CRITICAL();
    ctrl.params[slot - 1] = params;
    ctrl.params_gen[slot - 1]++;
    ctrl.written[slot - 1] = 1;
    ctrl.readback_slot = slot;
    taskEXIT_CRITICAL();
    notify_design_task();
    return true;
}

bool speaker_eq_cmd_write(uint8_t cmd_id, const uint8_t *payload, size_t len)
{
    switch (cmd_id) {
    case SPEAKER_EQ_CMD_SET_ROUTING:
        return write_routing(payload, len);
    case SPEAKER_EQ_CMD_SET_SLOT:
        return write_slot(payload, len);
    default:
        return false;
    }
}

static void read_info(uint8_t *p)
{
    uint8_t status[SPEAKER_EQ_NUM_SLOTS];
    speaker_eq_analysis_t analysis[SPEAKER_EQ_NUM_SLOTS];
    uint8_t enabled, profile;
    uint32_t count;

    taskENTER_CRITICAL();
    for (unsigned s = 0; s < SPEAKER_EQ_NUM_SLOTS; s++) {
        if (!ctrl.written[s]) {
            status[s] = SPEAKER_EQ_SLOT_EMPTY;
        } else if (ctrl.params_gen[s] != designs.designed_gen[s]) {
            status[s] = SPEAKER_EQ_SLOT_PENDING;
        } else {
            status[s] = designs.status[s];
        }
        analysis[s] = designs.analysis[s];
    }
    enabled = ctrl.eq_enabled;
    profile = ctrl.profile_id;
    count = designs.count;
    taskEXIT_CRITICAL();

    memset(p, 0, SPEAKER_EQ_INFO_BYTES);
    p[0] = SPEAKER_EQ_API_MAJOR;
    p[1] = SPEAKER_EQ_API_MINOR;
    p[2] = SPEAKER_EQ_MAX_FILTERS;
    p[3] = SPEAKER_EQ_MAX_SECTIONS;
    put_u32(&p[4], appconfI2S_AUDIO_SAMPLE_RATE);
    p[8] = enabled;
    p[9] = profile;
    p[10] = current_reason;
    p[11] = published_limiter_required;
    for (unsigned s = 0; s < SPEAKER_EQ_NUM_SLOTS; s++) {
        p[12 + s] = status[s];
        p[14 + s] = analysis[s].sections;
        put_f32(&p[16 + 4 * s], analysis[s].max_gain_db);
        put_f32(&p[24 + 4 * s], analysis[s].peak_gain_db);
    }
    put_u32(&p[32], count);
    put_u32(&p[36], published_seq);
}

static void read_stats(uint8_t *p)
{
    int32_t min_gain = INT32_MAX;
    float max_gr_db = 0.0f;

    for (unsigned ch = 0; ch < 2; ch++) {
        if (channels[ch].min_lim_gain < min_gain) {
            min_gain = channels[ch].min_lim_gain;
        }
    }
    if (min_gain < INT32_MAX && min_gain > 0) {
        max_gr_db = -8.68588964f * logf((float)min_gain / (float)INT32_MAX);
    }

    memset(p, 0, SPEAKER_EQ_STATS_BYTES);
    put_u32(&p[0], frames);
    for (unsigned ch = 0; ch < 2; ch++) {
        put_u16(&p[4 + 2 * ch], channels[ch].us_max);
        put_u16(&p[8 + 2 * ch], channels[ch].us_avg_x16 >> 4);
        put_u16(&p[12 + 2 * ch], channels[ch].us_last);
        p[22 + ch] = channels[ch].limiter_pct;
    }
    put_u32(&p[16], overruns);
    p[20] = current_reason;
    p[21] = watchdog_trips;
    put_f32(&p[24], max_gr_db);
    put_u32(&p[28], channels[0].limited_frames + channels[1].limited_frames);
    put_u32(&p[32], (uint32_t)xPortGetMinimumEverFreeHeapSize());
    put_u32(&p[36], (uint32_t)xPortGetFreeHeapSize());
    put_u32(&p[40], designs.rejects);
    put_u32(&p[44], designs.us_last);
}

static void read_slot(uint8_t *p)
{
    speaker_eq_slot_params_t params;
    uint8_t slot;

    taskENTER_CRITICAL();
    slot = ctrl.readback_slot;
    if (slot >= 1 && slot <= SPEAKER_EQ_NUM_SLOTS) {
        params = ctrl.params[slot - 1];
    } else {
        slot = 0;
        memset(&params, 0, sizeof(params));
    }
    taskEXIT_CRITICAL();

    speaker_eq_encode_slot(slot, &params, p);
}

bool speaker_eq_cmd_read(uint8_t cmd_id, uint8_t *payload, size_t len)
{
    switch (cmd_id) {
    case SPEAKER_EQ_CMD_GET_INFO:
        if (len != SPEAKER_EQ_INFO_BYTES) {
            return false;
        }
        read_info(payload);
        return true;
    case SPEAKER_EQ_CMD_GET_STATS:
        if (len != SPEAKER_EQ_STATS_BYTES) {
            return false;
        }
        read_stats(payload);
        return true;
    case SPEAKER_EQ_CMD_GET_SLOT:
        if (len != SPEAKER_EQ_SLOT_BYTES) {
            return false;
        }
        read_slot(payload);
        return true;
    default:
        return false;
    }
}

#endif
