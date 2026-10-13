/*
 * Speaker EQ tests, run under xsim against the real lib_audio_dsp build.
 * Prints machine-readable lines that check_speaker_eq.py verifies against
 * an independent double-precision model.
 */

#include <math.h>
#include <setjmp.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <xcore/hwtimer.h>

#include "FreeRTOS.h"
#include "speaker_eq/speaker_eq.h"
#include "speaker_eq/speaker_eq_design.h"

#define FS          48000.0f
#define FRAME       720
#define TWO_PI      6.283185307179586

static int failures;

#define CHECK(cond, ...)                                                    \
    do {                                                                    \
        if (!(cond)) {                                                      \
            failures++;                                                     \
            printf("FAIL line %d: ", __LINE__);                             \
            printf(__VA_ARGS__);                                            \
            printf("\n");                                                   \
        }                                                                   \
    } while (0)

/* ------------------------------------------------------------ RTOS stubs */

static void (*design_fn)(void *);
static jmp_buf design_jmp;

BaseType_t xTaskCreate(void (*fn)(void *), const char *name, uint32_t stack_words,
                       void *arg, UBaseType_t priority, TaskHandle_t *handle)
{
    (void)name; (void)stack_words; (void)arg; (void)priority;
    design_fn = fn;
    *handle = (TaskHandle_t)1;
    return pdPASS;
}

BaseType_t xTaskNotifyGive(TaskHandle_t handle)
{
    (void)handle;
    return pdPASS;
}

uint32_t ulTaskNotifyTake(BaseType_t clear, TickType_t wait)
{
    (void)clear; (void)wait;
    longjmp(design_jmp, 1);
}

size_t xPortGetFreeHeapSize(void) { return 1000; }
size_t xPortGetMinimumEverFreeHeapSize(void) { return 900; }

/* One pass of the design task loop, up to its wait for a notification. */
static void run_design(void)
{
    if (setjmp(design_jmp) == 0) {
        design_fn(NULL);
    }
}

/* -------------------------------------------------------------- profiles */

static speaker_eq_filter_t filt(uint8_t type, float hz, float gain, float q)
{
    speaker_eq_filter_t f = { type, SPEAKER_EQ_FILTER_FLAG_ENABLED, hz, gain, q };
    return f;
}

static speaker_eq_slot_params_t base_params(float preamp)
{
    speaker_eq_slot_params_t p;
    memset(&p, 0, sizeof(p));
    p.preamp_db = preamp;
    p.limiter_db = -1.0f;
    p.attack_ms = 1.0f;
    p.release_ms = 100.0f;
    return p;
}

static void add(speaker_eq_slot_params_t *p, speaker_eq_filter_t f)
{
    p->filters[p->filter_count++] = f;
}

/* "FPH Large Desk Smart Speaker" */
static speaker_eq_slot_params_t preset_fph(void)
{
    speaker_eq_slot_params_t p = base_params(10.0f);
    add(&p, filt(SPEAKER_EQ_FILTER_PEAK, 138.0f, -3.0f, 1.93f));
    add(&p, filt(SPEAKER_EQ_FILTER_PEAK, 1600.0f, -4.5f, 4.0f));
    add(&p, filt(SPEAKER_EQ_FILTER_PEAK, 3455.0f, -8.0f, 2.66f));
    add(&p, filt(SPEAKER_EQ_FILTER_PEAK, 5700.0f, 7.0f, 3.42f));
    add(&p, filt(SPEAKER_EQ_FILTER_PEAK, 13700.0f, -10.0f, 1.0f));
    add(&p, filt(SPEAKER_EQ_FILTER_HIGHPASS_Q, 60.0f, 0.0f, 1.0f));
    return p;
}

static speaker_eq_slot_params_t preset_crossovers(void)
{
    speaker_eq_slot_params_t p = base_params(0.0f);
    add(&p, filt(SPEAKER_EQ_FILTER_HIGHPASS_LR24, 80.0f, 0.0f, 0.7f));
    add(&p, filt(SPEAKER_EQ_FILTER_LOWPASS_BW24, 12000.0f, 0.0f, 0.7f));
    add(&p, filt(SPEAKER_EQ_FILTER_HIGHPASS_BW12, 40.0f, 0.0f, 0.7f));
    add(&p, filt(SPEAKER_EQ_FILTER_LOWPASS_LR12, 16000.0f, 0.0f, 0.7f));
    add(&p, filt(SPEAKER_EQ_FILTER_LOW_SHELF, 200.0f, 4.0f, 0.707f));
    add(&p, filt(SPEAKER_EQ_FILTER_HIGH_SHELF, 8000.0f, -6.0f, 0.707f));
    add(&p, filt(SPEAKER_EQ_FILTER_LOWPASS_Q, 19000.0f, 0.0f, 2.0f));
    add(&p, filt(SPEAKER_EQ_FILTER_HIGHPASS_LR12, 25.0f, 0.0f, 0.7f));
    add(&p, filt(SPEAKER_EQ_FILTER_LOWPASS_LR24, 19500.0f, 0.0f, 0.7f));
    add(&p, filt(SPEAKER_EQ_FILTER_HIGHPASS_BW24, 22.0f, 0.0f, 0.7f));
    return p;
}

/* 2 + 2 + 12 = 16 sections, the most a profile may use. */
static speaker_eq_slot_params_t preset_full(void)
{
    speaker_eq_slot_params_t p = base_params(6.0f);
    add(&p, filt(SPEAKER_EQ_FILTER_HIGHPASS_LR24, 50.0f, 0.0f, 0.7f));
    add(&p, filt(SPEAKER_EQ_FILTER_LOWPASS_LR24, 18000.0f, 0.0f, 0.7f));
    for (int i = 0; i < 12; i++) {
        add(&p, filt(SPEAKER_EQ_FILTER_PEAK, 100.0f * powf(1.5f, (float)i),
                     (i & 1) ? 2.0f : -3.0f, 2.0f));
    }
    return p;
}

/* ------------------------------------------------------- design printing */

static void print_case(const char *name, const speaker_eq_slot_params_t *p,
                       bool ok, const speaker_eq_bank_t *b, const speaker_eq_analysis_t *a)
{
    printf("CASE %s\n", name);
    printf("PARAMS %.6f %.6f\n", p->preamp_db, p->limiter_db);
    for (unsigned i = 0; i < p->filter_count; i++) {
        const speaker_eq_filter_t *f = &p->filters[i];
        printf("FILTER %u %u %.6f %.6f %.6f\n", f->type, f->flags, f->freq_hz, f->gain_db, f->q);
    }
    printf("RESULT %d %.4f %.4f %u\n", ok, a->max_gain_db, a->peak_gain_db, a->sections);
    if (ok) {
        printf("BANK %u %u %u %ld %ld\n", b->active, b->reason, b->limiter_required,
               (long)b->pre_gain, (long)b->post_gain);
        for (unsigned s = 0; s < b->num_sections; s++) {
            printf("SECTION %d %ld %ld %ld %ld %ld\n", b->lsh[s],
                   (long)b->coeffs[s][0], (long)b->coeffs[s][1], (long)b->coeffs[s][2],
                   (long)b->coeffs[s][3], (long)b->coeffs[s][4]);
        }
    }
    printf("END\n");
}

static bool design_roundtrip(const speaker_eq_slot_params_t *p,
                             speaker_eq_bank_t *bank, speaker_eq_analysis_t *a)
{
    uint8_t payload[SPEAKER_EQ_SLOT_BYTES];
    uint8_t payload2[SPEAKER_EQ_SLOT_BYTES];
    speaker_eq_slot_params_t q;
    uint8_t slot = 0;

    speaker_eq_encode_slot(1, p, payload);
    CHECK(speaker_eq_decode_slot(payload, &slot, &q), "decode of a valid slot failed");
    CHECK(slot == 1, "slot %u", slot);
    speaker_eq_encode_slot(slot, &q, payload2);
    CHECK(memcmp(payload, payload2, sizeof(payload)) == 0, "encode/decode not symmetric");
    return speaker_eq_design(&q, FS, bank, a);
}

static bool decodes(const speaker_eq_slot_params_t *p, uint8_t slot)
{
    uint8_t payload[SPEAKER_EQ_SLOT_BYTES];
    speaker_eq_slot_params_t q;
    uint8_t out;

    speaker_eq_encode_slot(slot, p, payload);
    return speaker_eq_decode_slot(payload, &out, &q);
}

static void test_design(void)
{
    speaker_eq_bank_t bank;
    speaker_eq_analysis_t a;
    speaker_eq_slot_params_t p;
    bool ok;

    p = preset_fph();
    ok = design_roundtrip(&p, &bank, &a);
    CHECK(ok, "default preset rejected");
    CHECK(bank.active && bank.limiter_required, "default preset should run with the limiter");
    CHECK(bank.num_sections == 6, "default preset sections %u", bank.num_sections);
    print_case("fph", &p, ok, &bank, &a);

    p = preset_crossovers();
    ok = design_roundtrip(&p, &bank, &a);
    CHECK(ok, "crossover profile rejected");
    CHECK(bank.num_sections == 14, "crossover sections %u", bank.num_sections);
    print_case("crossovers", &p, ok, &bank, &a);

    p = preset_full();
    ok = design_roundtrip(&p, &bank, &a);
    CHECK(ok && bank.num_sections == 16, "full profile %d %u", ok, bank.num_sections);
    print_case("full", &p, ok, &bank, &a);

    /* Cut-only: no limiter needed. */
    p = base_params(-3.0f);
    add(&p, filt(SPEAKER_EQ_FILTER_PEAK, 1000.0f, -6.0f, 1.0f));
    ok = design_roundtrip(&p, &bank, &a);
    CHECK(ok && bank.active && !bank.limiter_required, "cut-only profile");
    print_case("cut_only", &p, ok, &bank, &a);

    /* Boost below the ceiling margin still needs the limiter at -1 dBFS. */
    p = base_params(0.0f);
    add(&p, filt(SPEAKER_EQ_FILTER_PEAK, 1000.0f, 0.5f, 1.0f));
    ok = design_roundtrip(&p, &bank, &a);
    CHECK(ok && bank.limiter_required, "small boost should need the limiter");

    /* Flat profiles bypass. */
    p = base_params(0.0f);
    ok = design_roundtrip(&p, &bank, &a);
    CHECK(ok && !bank.active && bank.reason == SPEAKER_EQ_BYPASS_FLAT, "flat profile");
    add(&p, filt(SPEAKER_EQ_FILTER_PEAK, 1000.0f, 0.005f, 1.0f));
    p.filters[0].flags = SPEAKER_EQ_FILTER_FLAG_ENABLED;
    add(&p, filt(SPEAKER_EQ_FILTER_PEAK, 2000.0f, -6.0f, 1.0f));
    p.filters[1].flags = 0;
    ok = design_roundtrip(&p, &bank, &a);
    CHECK(ok && !bank.active && a.sections == 0, "negligible and disabled filters ignored");

    /* Too hot: rejected, bank untouched. */
    p = base_params(12.0f);
    add(&p, filt(SPEAKER_EQ_FILTER_PEAK, 1000.0f, 12.0f, 0.5f));
    add(&p, filt(SPEAKER_EQ_FILTER_LOW_SHELF, 300.0f, 12.0f, 0.7f));
    memset(&bank, 0xA5, sizeof(bank));
    ok = design_roundtrip(&p, &bank, &a);
    CHECK(!ok, "over-headroom profile accepted (peak %.2f)", a.peak_gain_db);
    CHECK(a.peak_gain_db > SPEAKER_EQ_HEADROOM_CAP_DB, "peak %.2f", a.peak_gain_db);
    {
        uint8_t pattern[sizeof(bank)];
        memset(pattern, 0xA5, sizeof(pattern));
        CHECK(memcmp(&bank, pattern, sizeof(bank)) == 0, "rejected design wrote the bank");
    }

    /* Cuts are ordered before boosts. */
    p = base_params(0.0f);
    add(&p, filt(SPEAKER_EQ_FILTER_PEAK, 1000.0f, 6.0f, 1.0f));
    add(&p, filt(SPEAKER_EQ_FILTER_PEAK, 1000.0f, -6.0f, 1.0f));
    ok = design_roundtrip(&p, &bank, &a);
    CHECK(ok && bank.num_sections == 2, "order profile");
    CHECK(bank.coeffs[0][0] < bank.coeffs[1][0] || bank.lsh[0] < bank.lsh[1],
          "cut section should come first");
    print_case("order", &p, ok, &bank, &a);

    /* Validation. */
    p = preset_fph();
    CHECK(decodes(&p, 1) && decodes(&p, 2), "valid slots");
    CHECK(!decodes(&p, 0) && !decodes(&p, 3), "slot range");
    p.preamp_db = NAN;
    CHECK(!decodes(&p, 1), "NaN preamp");
    p = preset_fph(); p.preamp_db = 12.5f;
    CHECK(!decodes(&p, 1), "preamp range");
    p = preset_fph(); p.limiter_db = 0.5f;
    CHECK(!decodes(&p, 1), "limiter range");
    p = preset_fph(); p.attack_ms = 0.0f;
    CHECK(!decodes(&p, 1), "attack range");
    p = preset_fph(); p.release_ms = 6000.0f;
    CHECK(!decodes(&p, 1), "release range");
    p = preset_fph(); p.filters[0].freq_hz = 19.9f;
    CHECK(!decodes(&p, 1), "freq range");
    p = preset_fph(); p.filters[0].q = INFINITY;
    CHECK(!decodes(&p, 1), "inf Q");
    p = preset_fph(); p.filters[0].gain_db = 12.5f;
    CHECK(!decodes(&p, 1), "gain range");
    p = preset_fph(); p.filters[5].gain_db = NAN;
    CHECK(decodes(&p, 1), "cut filters ignore the gain field");
    p = preset_fph(); p.filters[0].type = SPEAKER_EQ_NUM_FILTER_TYPES;
    CHECK(!decodes(&p, 1), "filter type range");
    p = preset_fph(); p.filters[0].flags = 0; p.filters[0].q = 0.0f;
    CHECK(!decodes(&p, 1), "disabled filters are still range checked");
    {
        uint8_t payload[SPEAKER_EQ_SLOT_BYTES];
        speaker_eq_slot_params_t q;
        uint8_t slot;
        p = preset_fph();
        speaker_eq_encode_slot(1, &p, payload);
        payload[17] = SPEAKER_EQ_MAX_FILTERS + 1;
        CHECK(!speaker_eq_decode_slot(payload, &slot, &q), "filter_count range");
    }
    p = base_params(0.0f);
    for (int i = 0; i < 8; i++) {
        add(&p, filt(SPEAKER_EQ_FILTER_HIGHPASS_BW24, 20.0f + i, 0.0f, 0.7f));
    }
    CHECK(decodes(&p, 1), "16 sections allowed");
    add(&p, filt(SPEAKER_EQ_FILTER_PEAK, 1000.0f, 1.0f, 1.0f));
    CHECK(!decodes(&p, 1), "17 sections rejected");
}

/* --------------------------------------------------------------- runtime */

static int32_t in_l[FRAME], in_r[FRAME], out_l[FRAME], out_r[FRAME];
static int32_t history[4 * FRAME];
static float osc_c = 1.0f, osc_s = 0.0f;

/* Byte-assembled, avoiding xcc's unaligned float load bug. */
static uint32_t get_u32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static float get_f32(const uint8_t *p)
{
    const uint32_t bits = get_u32(p);
    float v;
    memcpy(&v, &bits, sizeof(v));
    return v;
}

static uint16_t get_u16(const uint8_t *p)
{
    return (uint16_t)(p[0] | (p[1] << 8));
}

static void process_frame(void)
{
    speaker_eq_frame_tag_t tag;

    memcpy(out_l, in_l, sizeof(out_l));
    memcpy(out_r, in_r, sizeof(out_r));
    speaker_eq_process_ch0(out_l, &tag);
    speaker_eq_process_ch1(out_r, &tag);
    memmove(history, history + FRAME, 3 * FRAME * sizeof(int32_t));
    memcpy(history + 3 * FRAME, out_l, sizeof(out_l));
}

/* Rotating-phasor oscillator: hardware float only, so xsim stays fast. */
static void fill_tone(float hz, float amp_dbfs)
{
    const float amp = powf(10.0f, amp_dbfs / 20.0f) * 2147483520.0f;
    const float w = (float)TWO_PI * hz / FS;
    const float cw = cosf(w), sw = sinf(w);

    for (int k = 0; k < FRAME; k++) {
        in_l[k] = (int32_t)(amp * osc_s);
        in_r[k] = in_l[k];
        const float c = osc_c * cw - osc_s * sw;
        osc_s = osc_s * cw + osc_c * sw;
        osc_c = c;
    }
    const float g = 1.5f - 0.5f * (osc_c * osc_c + osc_s * osc_s);
    osc_c *= g;
    osc_s *= g;
}

static uint32_t rng = 12345;

static void fill_noise(void)
{
    for (int k = 0; k < FRAME; k++) {
        rng = rng * 1664525u + 1013904223u;
        in_l[k] = (int32_t)rng >> 2;
        rng = rng * 1664525u + 1013904223u;
        in_r[k] = (int32_t)rng >> 2;
    }
}

static bool frame_is_dry(void)
{
    return memcmp(out_l, in_l, sizeof(in_l)) == 0 && memcmp(out_r, in_r, sizeof(in_r)) == 0;
}

/* Gain of the last frames at hz relative to the input level, over whole cycles. */
static double measure_db(float hz, float amp_dbfs)
{
    const unsigned cycles = (unsigned)(4.0 * FRAME * hz / FS);
    const unsigned n = (unsigned)(cycles * FS / hz + 0.5);
    const unsigned start = 4 * FRAME - n;
    const float w = (float)TWO_PI * hz / FS;
    const float cw = cosf(w), sw = sinf(w);
    float c = 1.0f, s = 0.0f;
    double re = 0.0, im = 0.0;

    for (unsigned k = 0; k < n; k++) {
        re += (double)history[start + k] * c;
        im += (double)history[start + k] * s;
        const float nc = c * cw - s * sw;
        s = s * cw + c * sw;
        c = nc;
    }
    const double amp = 2.0 * sqrt(re * re + im * im) / n;
    return 20.0 * log10(amp / 2147483647.0) - amp_dbfs;
}

static int32_t probe_prev;

/* Largest sample-to-sample change on a steady 100 Hz probe tone. */
static int64_t probe_steps(int frames)
{
    int64_t worst = 0;

    for (int f = 0; f < frames; f++) {
        fill_tone(100.0f, -20.0f);
        process_frame();
        for (int k = 0; k < FRAME; k++) {
            const int64_t d = llabs((int64_t)out_l[k] - probe_prev);
            if (d > worst) {
                worst = d;
            }
            probe_prev = out_l[k];
        }
    }
    return worst;
}

static bool same_sections(const speaker_eq_slot_params_t *a, const speaker_eq_slot_params_t *b)
{
    static speaker_eq_bank_t ba, bb;
    speaker_eq_analysis_t an;

    CHECK(speaker_eq_design(a, FS, &ba, &an) && speaker_eq_design(b, FS, &bb, &an), "design");
    return ba.num_sections == bb.num_sections &&
           memcmp(ba.section_id, bb.section_id, ba.num_sections * sizeof(ba.section_id[0])) == 0 &&
           memcmp(ba.lsh, bb.lsh, ba.num_sections) == 0;
}

static void measure_case(const char *name, const speaker_eq_slot_params_t *p,
                         const float *tones, unsigned count)
{
    speaker_eq_bank_t bank;
    speaker_eq_analysis_t a;

    for (unsigned t = 0; t < count; t++) {
        for (int f = 0; f < 10; f++) {
            fill_tone(tones[t], -20.0f);
            process_frame();
        }
        printf("TONE %s %.1f %.4f\n", name, tones[t], measure_db(tones[t], -20.0f));
    }
    print_case(name, p, speaker_eq_design(p, FS, &bank, &a), &bank, &a);
}

static void write_slot(uint8_t slot, const speaker_eq_slot_params_t *p, bool expect_ok)
{
    uint8_t payload[SPEAKER_EQ_SLOT_BYTES];

    speaker_eq_encode_slot(slot, p, payload);
    CHECK(speaker_eq_cmd_write(SPEAKER_EQ_CMD_SET_SLOT, payload, sizeof(payload)) == expect_ok,
          "SET_SLOT %u", slot);
    run_design();
}

static void routing(uint8_t enabled, uint8_t profile)
{
    const uint8_t payload[SPEAKER_EQ_ROUTING_BYTES] = { enabled, profile };

    CHECK(speaker_eq_cmd_write(SPEAKER_EQ_CMD_SET_ROUTING, payload, sizeof(payload)),
          "SET_ROUTING %u %u", enabled, profile);
    run_design();
}

typedef struct {
    uint8_t enabled, profile, reason, limiter_required;
    uint8_t status[2], sections[2];
    float max_db[2], peak_db[2];
    uint32_t design_count, bank_seq;
} info_t;

static info_t read_info(void)
{
    uint8_t b[SPEAKER_EQ_INFO_BYTES];
    info_t i;

    CHECK(speaker_eq_cmd_read(SPEAKER_EQ_CMD_GET_INFO, b, sizeof(b)), "GET_INFO");
    CHECK(!speaker_eq_cmd_read(SPEAKER_EQ_CMD_GET_INFO, b, sizeof(b) - 1), "GET_INFO short");
    CHECK(b[0] == SPEAKER_EQ_API_MAJOR && b[2] == SPEAKER_EQ_MAX_FILTERS &&
          b[3] == SPEAKER_EQ_MAX_SECTIONS, "info header");
    CHECK(get_u32(&b[4]) == 48000, "info sample rate %lu", (unsigned long)get_u32(&b[4]));
    i.enabled = b[8];
    i.profile = b[9];
    i.reason = b[10];
    i.limiter_required = b[11];
    for (int s = 0; s < 2; s++) {
        i.status[s] = b[12 + s];
        i.sections[s] = b[14 + s];
        i.max_db[s] = get_f32(&b[16 + 4 * s]);
        i.peak_db[s] = get_f32(&b[24 + 4 * s]);
    }
    i.design_count = get_u32(&b[32]);
    i.bank_seq = get_u32(&b[36]);
    return i;
}

typedef struct {
    uint32_t frames, overruns, limiter_frames, rejects;
    uint16_t us_max[2], us_avg[2], us_last[2];
    uint8_t reason, trips, pct[2];
    float gr_db;
} stats_t;

static stats_t read_stats(void)
{
    uint8_t b[SPEAKER_EQ_STATS_BYTES];
    stats_t s;

    CHECK(speaker_eq_cmd_read(SPEAKER_EQ_CMD_GET_STATS, b, sizeof(b)), "GET_STATS");
    s.frames = get_u32(&b[0]);
    for (int ch = 0; ch < 2; ch++) {
        s.us_max[ch] = get_u16(&b[4 + 2 * ch]);
        s.us_avg[ch] = get_u16(&b[8 + 2 * ch]);
        s.us_last[ch] = get_u16(&b[12 + 2 * ch]);
        s.pct[ch] = b[22 + ch];
    }
    s.overruns = get_u32(&b[16]);
    s.reason = b[20];
    s.trips = b[21];
    s.gr_db = get_f32(&b[24]);
    s.limiter_frames = get_u32(&b[28]);
    CHECK(get_u32(&b[32]) == 900 && get_u32(&b[36]) == 1000, "heap fields");
    s.rejects = get_u32(&b[40]);
    return s;
}

static void test_runtime(void)
{
    info_t info;
    stats_t stats;
    speaker_eq_slot_params_t p;

    speaker_eq_init();
    run_design();

    /* Boot state: disabled, bit-exact. */
    info = read_info();
    CHECK(info.reason == SPEAKER_EQ_BYPASS_DISABLED, "boot reason %u", info.reason);
    CHECK(info.status[0] == SPEAKER_EQ_SLOT_EMPTY && info.status[1] == SPEAKER_EQ_SLOT_EMPTY,
          "boot slots");
    for (int f = 0; f < 3; f++) {
        fill_noise();
        process_frame();
        CHECK(frame_is_dry(), "boot frame %d not bit-exact", f);
    }

    /* Slot written but EQ still disabled: bit-exact. */
    p = preset_fph();
    write_slot(1, &p, true);
    info = read_info();
    CHECK(info.status[0] == SPEAKER_EQ_SLOT_OK && info.sections[0] == 6, "slot 1 status");
    printf("INFO fph %.4f %.4f\n", info.max_db[0], info.peak_db[0]);
    fill_noise();
    process_frame();
    CHECK(frame_is_dry(), "disabled frame not bit-exact");

    /* Readback returns the last written slot. */
    {
        uint8_t want[SPEAKER_EQ_SLOT_BYTES], got[SPEAKER_EQ_SLOT_BYTES];
        speaker_eq_encode_slot(1, &p, want);
        CHECK(speaker_eq_cmd_read(SPEAKER_EQ_CMD_GET_SLOT, got, sizeof(got)), "GET_SLOT");
        CHECK(memcmp(want, got, sizeof(got)) == 0, "GET_SLOT readback mismatch");
    }

    /* Routing takes eq_enabled 0 or 1 and a known profile, in exactly two bytes. */
    {
        const uint8_t bad_enable[] = { 2, 1 };
        const uint8_t bad_profile[] = { 1, SPEAKER_EQ_NUM_PROFILES };
        CHECK(!speaker_eq_cmd_write(SPEAKER_EQ_CMD_SET_ROUTING, bad_enable, sizeof(bad_enable)),
              "routing with eq_enabled 2 accepted");
        CHECK(!speaker_eq_cmd_write(SPEAKER_EQ_CMD_SET_ROUTING, bad_profile, sizeof(bad_profile)),
              "routing to an unknown profile accepted");
        CHECK(!speaker_eq_cmd_write(SPEAKER_EQ_CMD_SET_ROUTING, bad_enable, 1), "short routing accepted");
        CHECK(read_info().enabled == 0, "a refused routing write changed the switch");
    }

    /* Enable: the first wet frame starts from the dry signal. */
    routing(1, 1);
    fill_tone(1000.0f, -20.0f);
    process_frame();
    CHECK(out_l[0] == in_l[0], "fade-in must start dry");
    CHECK(memcmp(out_l, out_r, sizeof(out_l)) == 0, "channels differ for identical input");
    info = read_info();
    CHECK(info.reason == SPEAKER_EQ_BYPASS_NONE && info.limiter_required, "enabled info");

    /* Steady-state tone response through the real VPU chain. */
    static const float tones[] = { 30, 60, 138, 400, 1000, 1600, 3455, 5700, 10000, 13700, 18000 };
    for (unsigned t = 0; t < sizeof(tones) / sizeof(tones[0]); t++) {
        for (int f = 0; f < 10; f++) {
            fill_tone(tones[t], -20.0f);
            process_frame();
        }
        printf("TONE fph %.1f %.4f\n", tones[t], measure_db(tones[t], -20.0f));
    }

    /* Hot input: the limiter holds the -1 dBFS ceiling and never wraps. */
    {
        const int32_t ceiling = (int32_t)(powf(10.0f, -1.0f / 20.0f) * 2147483647.0f);
        const uint32_t limited_before = read_stats().limiter_frames;
        int32_t peak = 0;
        for (int f = 0; f < 20; f++) {
            fill_tone(5700.0f, 0.0f);
            process_frame();
            for (int k = 0; k < FRAME; k++) {
                const int32_t m = out_l[k] < 0 ? -out_l[k] : out_l[k];
                if (f >= 1 && m > peak) {
                    peak = m;
                }
            }
        }
        printf("LIMIT peak_dbfs %.4f\n", 20.0 * log10(peak / 2147483647.0));
        CHECK(peak <= ceiling + 64, "limiter ceiling exceeded: %ld > %ld", (long)peak, (long)ceiling);
        stats = read_stats();
        const uint32_t limited = stats.limiter_frames - limited_before;
        CHECK(limited >= 2 * 19 && stats.gr_db > 10.0f, "limiter stats frames %lu gr %.2f",
              (unsigned long)limited, stats.gr_db);
        printf("LIMIT gr_db %.3f frames %lu\n", stats.gr_db, (unsigned long)limited);
    }

    /* Design changes while playing: re-sorted sections crossfade, same ones glide. */
    {
        const speaker_eq_slot_params_t before = preset_fph();
        int64_t steady, during;

        /* Filter 0 becomes a boost, so the cut-first order changes. */
        p = before;
        p.preamp_db = 4.0f;
        p.filters[0].gain_db = 6.0f;
        CHECK(!same_sections(&before, &p), "crossfade case must re-sort sections");
        probe_steps(20);
        steady = probe_steps(3);
        write_slot(1, &p, true);
        during = probe_steps(6);
        printf("GLIDE crossfade steady %lld during %lld\n", (long long)steady, (long long)during);
        CHECK(during < 2 * steady, "crossfade produced a step");
        static const float crossfade_tones[] = { 5700, 138 };
        measure_case("crossfaded", &p, crossfade_tones, 2);

        /* Same sections; the 13.7 kHz cut moves to 120 Hz, a -a1 jump of about 2.3. */
        const speaker_eq_slot_params_t moved_from = p;
        p.filters[4].freq_hz = 120.0f;
        CHECK(same_sections(&moved_from, &p), "glide case must keep its sections");
        probe_steps(10);
        steady = probe_steps(3);
        write_slot(1, &p, true);
        during = probe_steps(6);
        printf("GLIDE glide steady %lld during %lld\n", (long long)steady, (long long)during);
        CHECK(during < 2 * steady, "glide produced a step");
        static const float glide_tones[] = { 120, 5700 };
        measure_case("glided", &p, glide_tones, 2);

        /* A filter that changes type crossfades, even with the same section count and shift. */
        speaker_eq_slot_params_t retyped = p;
        retyped.filters[4].type = SPEAKER_EQ_FILTER_LOW_SHELF;
        CHECK(!same_sections(&p, &retyped), "type change must not glide");
    }

    /* A design that no longer needs the limiter moves a running one to its own ceiling. */
    {
        p = preset_fph();
        p.preamp_db = -5.5f;    /* net peak about -0.7 dB, under a 0 dBFS ceiling */
        p.limiter_db = 0.0f;
        write_slot(1, &p, true);
        CHECK(!read_info().limiter_required, "retarget case must not need the limiter");
        int32_t peak = 0;
        for (int f = 0; f < 30; f++) {
            fill_tone(5700.0f, 0.0f);
            process_frame();
            for (int k = 0; f >= 20 && k < FRAME; k++) {
                const int32_t m = out_l[k] < 0 ? -out_l[k] : out_l[k];
                if (m > peak) {
                    peak = m;
                }
            }
        }
        printf("LIMIT retarget_peak_dbfs %.4f\n", 20.0 * log10(peak / 2147483647.0));
        CHECK(peak > (int32_t)(powf(10.0f, -0.9f / 20.0f) * 2147483647.0f),
              "running limiter kept the old -1 dBFS ceiling");
        p = preset_fph();
        write_slot(1, &p, true);
    }

    /* A rejected write keeps the running design. */
    {
        const uint32_t seq = read_info().bank_seq;
        speaker_eq_slot_params_t hot = base_params(12.0f);
        add(&hot, filt(SPEAKER_EQ_FILTER_PEAK, 1000.0f, 12.0f, 0.5f));
        add(&hot, filt(SPEAKER_EQ_FILTER_LOW_SHELF, 300.0f, 12.0f, 0.7f));
        write_slot(1, &hot, true);
        info = read_info();
        CHECK(info.status[0] == SPEAKER_EQ_SLOT_REJECTED_HEADROOM, "rejected status %u", info.status[0]);
        CHECK(info.bank_seq == seq, "rejected design was published");
        CHECK(read_stats().rejects == 1, "reject counter");
        fill_tone(5700.0f, -20.0f);
        process_frame();
        CHECK(!frame_is_dry(), "EQ stopped after a rejected write");
        uint8_t bad[SPEAKER_EQ_SLOT_BYTES];
        speaker_eq_encode_slot(1, &hot, bad);
        bad[0] = 9;
        CHECK(!speaker_eq_cmd_write(SPEAKER_EQ_CMD_SET_SLOT, bad, sizeof(bad)), "bad slot accepted");
        CHECK(!speaker_eq_cmd_write(SPEAKER_EQ_CMD_SET_SLOT, bad, sizeof(bad) - 1), "short write accepted");
        CHECK(!speaker_eq_cmd_write(SPEAKER_EQ_CMD_GET_INFO, bad, SPEAKER_EQ_INFO_BYTES), "write to read cmd");
    }

    /* Disable: one 128-sample fade, then bit-exact. */
    routing(0, 1);
    fill_noise();
    process_frame();
    CHECK(memcmp(out_l + 128, in_l + 128, (FRAME - 128) * 4) == 0, "fade-out tail not dry");
    CHECK(memcmp(out_l, in_l, 128 * 4) != 0, "fade-out head should still carry wet signal");
    fill_noise();
    process_frame();
    CHECK(frame_is_dry(), "frame after fade-out not bit-exact");
    CHECK(read_info().reason == SPEAKER_EQ_BYPASS_DISABLED, "disabled reason");

    /* Profile 2 never written: bypass with NO_PROFILE. */
    routing(1, 2);
    fill_noise();
    process_frame();
    CHECK(frame_is_dry(), "empty profile not bit-exact");
    CHECK(read_info().reason == SPEAKER_EQ_BYPASS_NO_PROFILE, "no-profile reason");

    /* Flat line-out profile: bypass with FLAT. */
    p = base_params(0.0f);
    write_slot(2, &p, true);
    fill_noise();
    process_frame();
    CHECK(frame_is_dry(), "flat profile not bit-exact");
    CHECK(read_info().reason == SPEAKER_EQ_BYPASS_FLAT, "flat reason %u", read_info().reason);

    /* A design for the slot not playing, or routing that changes nothing, publishes nothing: a
     * publish clears the overload bypass. */
    {
        routing(1, 1);
        const uint32_t seq = read_info().bank_seq;
        p = base_params(0.0f);
        add(&p, filt(SPEAKER_EQ_FILTER_PEAK, 1000.0f, -3.0f, 1.0f));
        write_slot(2, &p, true);
        routing(1, 1);
        CHECK(read_info().bank_seq == seq, "idle write republished the bank");
    }

    /* CPU cost of the largest profile. */
    p = preset_full();
    write_slot(1, &p, true);
    for (int f = 0; f < 12; f++) {
        fill_noise();
        process_frame();
    }
    stats = read_stats();
    printf("BENCH sections 16 us_last %u %u us_avg %u %u\n",
           stats.us_last[0], stats.us_last[1], stats.us_avg[0], stats.us_avg[1]);
    {
        uint32_t t0 = get_reference_time();
        speaker_eq_bank_t bank;
        speaker_eq_analysis_t a;
        speaker_eq_design(&p, FS, &bank, &a);
        printf("BENCH design_us %lu\n", (unsigned long)((get_reference_time() - t0) / 100));
    }
    CHECK(stats.frames > 0 && stats.overruns == 0, "overruns %lu", (unsigned long)stats.overruns);
}

int main(void)
{
    test_design();
    test_runtime();
    printf("DONE failures=%d\n", failures);
    return failures ? 1 : 0;
}
