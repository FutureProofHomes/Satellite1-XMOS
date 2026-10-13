#include "speaker_eq/speaker_eq.h"

#if SPEAKER_EQ_ACTIVE

#include <math.h>
#include <string.h>

#include "control/adsp_control.h"
#include "dsp/adsp.h"

#include "speaker_eq/speaker_eq_design.h"

#define EQ_GRID_POINTS      160
#define EQ_GRID_LOW_HZ      10.0f
#define EQ_GRID_HIGH_FRAC   0.49f
#define EQ_MIN_GAIN_DB      0.01f
#define EQ_BOOST_MAG2       1.0001f
#define EQ_LIMITER_SLACK_DB 0.01f

#define EQ_TWO_PI           6.28318531f
#define EQ_LN10             2.30258509f
#define EQ_DB_PER_LN        8.68588964f     /* 20 / ln(10) */

#define Q_BUTTERWORTH       0.70710678f
#define Q_LR12              0.5f
#define Q_BW24_A            0.54119610f
#define Q_BW24_B            1.30656296f

typedef struct {
    int32_t c[5];
    int32_t lsh;
    float fc;
    float b0, b1, b2, a1, a2;
    float max_mag2;
    uint16_t id;
} eq_section_t;

_Static_assert(2 * SPEAKER_EQ_MAX_FILTERS <= 32 && SPEAKER_EQ_NUM_FILTER_TYPES <= 2048,
               "section ids pack the type above five bits of position");

/* Only the design task calls speaker_eq_design(). */
static eq_section_t sections[SPEAKER_EQ_MAX_SECTIONS];

/*
 * Assembled from bytes on purpose: xcc 15.3.1 miscompiles comparisons on a
 * float memcpy'd from an unaligned address (wrong integer compare at -O2/-Os,
 * backend crash for a lone compare).
 */
static float get_f32(const uint8_t *p)
{
    const uint32_t bits = (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
                          ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
    float v;
    memcpy(&v, &bits, sizeof(v));
    return v;
}

static void put_f32(uint8_t *p, float v)
{
    memcpy(p, &v, sizeof(v));
}

/* Comparisons are false for NaN, so this also rejects NaN and infinities. */
static bool in_range(float v, float lo, float hi)
{
    return v >= lo && v <= hi;
}

static bool type_uses_gain(uint8_t type)
{
    return type == SPEAKER_EQ_FILTER_PEAK ||
           type == SPEAKER_EQ_FILTER_LOW_SHELF ||
           type == SPEAKER_EQ_FILTER_HIGH_SHELF;
}

static bool type_uses_q(uint8_t type)
{
    return type_uses_gain(type) ||
           type == SPEAKER_EQ_FILTER_HIGHPASS_Q ||
           type == SPEAKER_EQ_FILTER_LOWPASS_Q;
}

static unsigned filter_sections(const speaker_eq_filter_t *f)
{
    if (f->type == SPEAKER_EQ_FILTER_NONE ||
        !(f->flags & SPEAKER_EQ_FILTER_FLAG_ENABLED)) {
        return 0;
    }
    if (type_uses_gain(f->type) && fabsf(f->gain_db) < EQ_MIN_GAIN_DB) {
        return 0;
    }
    switch (f->type) {
    case SPEAKER_EQ_FILTER_HIGHPASS_BW24:
    case SPEAKER_EQ_FILTER_HIGHPASS_LR24:
    case SPEAKER_EQ_FILTER_LOWPASS_BW24:
    case SPEAKER_EQ_FILTER_LOWPASS_LR24:
        return 2;
    default:
        return 1;
    }
}

bool speaker_eq_decode_slot(const uint8_t *payload,
                            uint8_t *slot,
                            speaker_eq_slot_params_t *params)
{
    speaker_eq_slot_params_t p;
    unsigned total_sections = 0;

    memset(&p, 0, sizeof(p));

    if (payload[0] < 1 || payload[0] > SPEAKER_EQ_NUM_SLOTS) {
        return false;
    }

    p.preamp_db = get_f32(&payload[1]);
    p.limiter_db = get_f32(&payload[5]);
    p.attack_ms = get_f32(&payload[9]);
    p.release_ms = get_f32(&payload[13]);
    p.filter_count = payload[17];

    if (!in_range(p.preamp_db, -24.0f, 12.0f) ||
        !in_range(p.limiter_db, -12.0f, 0.0f) ||
        !in_range(p.attack_ms, 0.1f, 100.0f) ||
        !in_range(p.release_ms, 5.0f, 5000.0f) ||
        p.filter_count > SPEAKER_EQ_MAX_FILTERS) {
        return false;
    }

    for (unsigned i = 0; i < p.filter_count; i++) {
        const uint8_t *rec = &payload[SPEAKER_EQ_SLOT_HEADER_BYTES +
                                      i * SPEAKER_EQ_FILTER_RECORD_BYTES];
        speaker_eq_filter_t *f = &p.filters[i];

        f->type = rec[0];
        f->flags = rec[1] & SPEAKER_EQ_FILTER_FLAG_ENABLED;
        f->freq_hz = get_f32(&rec[2]);
        f->gain_db = get_f32(&rec[6]);
        f->q = get_f32(&rec[10]);

        if (f->type >= SPEAKER_EQ_NUM_FILTER_TYPES) {
            return false;
        }
        if (f->type == SPEAKER_EQ_FILTER_NONE) {
            /* Unchecked, so not kept: GET_SLOT would echo NaN back. */
            memset(f, 0, sizeof(*f));
            continue;
        }
        if (!in_range(f->freq_hz, 20.0f, 20000.0f)) {
            return false;
        }
        if (type_uses_q(f->type) && !in_range(f->q, 0.1f, 10.0f)) {
            return false;
        }
        if (type_uses_gain(f->type) && !in_range(f->gain_db, -30.0f, 12.0f)) {
            return false;
        }
        total_sections += filter_sections(f);
    }

    if (total_sections > SPEAKER_EQ_MAX_SECTIONS) {
        return false;
    }

    *slot = payload[0];
    *params = p;
    return true;
}

void speaker_eq_encode_slot(uint8_t slot,
                            const speaker_eq_slot_params_t *params,
                            uint8_t *payload)
{
    memset(payload, 0, SPEAKER_EQ_SLOT_BYTES);
    payload[0] = slot;
    put_f32(&payload[1], params->preamp_db);
    put_f32(&payload[5], params->limiter_db);
    put_f32(&payload[9], params->attack_ms);
    put_f32(&payload[13], params->release_ms);
    payload[17] = params->filter_count;

    for (unsigned i = 0; i < params->filter_count && i < SPEAKER_EQ_MAX_FILTERS; i++) {
        uint8_t *rec = &payload[SPEAKER_EQ_SLOT_HEADER_BYTES +
                                i * SPEAKER_EQ_FILTER_RECORD_BYTES];
        const speaker_eq_filter_t *f = &params->filters[i];

        rec[0] = f->type;
        rec[1] = f->flags;
        put_f32(&rec[2], f->freq_hz);
        put_f32(&rec[6], f->gain_db);
        put_f32(&rec[10], f->q);
    }
}

void speaker_eq_bank_set_bypass(speaker_eq_bank_t *bank, uint8_t reason)
{
    memset(bank, 0, sizeof(*bank));
    bank->pre_gain = 1 << Q_GAIN;
    bank->post_gain = 1 << Q_GAIN;
    bank->reason = reason;
}

/* Saturates instead of asserting, unlike the lib_audio_dsp helpers. */
static int32_t to_fixed(float x, int q)
{
    const float v = ldexpf(x, q);

    if (v >= 2147483648.0f) {
        return INT32_MAX;
    }
    if (v <= -2147483648.0f) {
        return INT32_MIN;
    }
    return (int32_t)(v >= 0.0f ? v + 0.5f : v - 0.5f);
}

static float db_to_lin(float db)
{
    return expf(db * (EQ_LN10 / 20.0f));
}

/* Headroom left shift for b coefficients that do not fit Q30. */
static int32_t b_shift(float b0, float b1, float b2)
{
    float m = fabsf(b0);
    int32_t sh = 0;

    if (fabsf(b1) > m) {
        m = fabsf(b1);
    }
    if (fabsf(b2) > m) {
        m = fabsf(b2);
    }
    while (m >= 2.0f && sh < 8) {
        m *= 0.5f;
        sh++;
    }
    return sh;
}

static void add_section(unsigned *n, float b0, float b1, float b2,
                        float a1, float a2, float fc)
{
    eq_section_t *s = &sections[*n];
    const int32_t lsh = b_shift(b0, b1, b2);

    s->c[0] = to_fixed(b0, 30 - lsh);
    s->c[1] = to_fixed(b1, 30 - lsh);
    s->c[2] = to_fixed(b2, 30 - lsh);
    s->c[3] = to_fixed(-a1, 30);
    s->c[4] = to_fixed(-a2, 30);
    s->lsh = lsh;
    s->fc = fc;
    /* Analyse the quantised coefficients the VPU will actually run. */
    s->b0 = ldexpf((float)s->c[0], lsh - 30);
    s->b1 = ldexpf((float)s->c[1], lsh - 30);
    s->b2 = ldexpf((float)s->c[2], lsh - 30);
    s->a1 = -ldexpf((float)s->c[3], -30);
    s->a2 = -ldexpf((float)s->c[4], -30);
    s->max_mag2 = 0.0f;
    (*n)++;
}

typedef enum {
    RBJ_LOWPASS,
    RBJ_HIGHPASS,
    RBJ_PEAK,
    RBJ_LOW_SHELF,
    RBJ_HIGH_SHELF,
} rbj_kind_t;

/* Audio EQ Cookbook (R. Bristow-Johnson) biquads, as lib_audio_dsp designs them. */
static void add_rbj(unsigned *n, rbj_kind_t kind, float fc, float fs, float q, float gain_db)
{
    const float w0 = EQ_TWO_PI * fc / fs;
    const float cw = f32_cos(w0);
    const float alpha = f32_sin(w0) / (2.0f * q);
    const float a = expf(gain_db * (EQ_LN10 / 40.0f));
    const float k = 2.0f * expf(gain_db * (EQ_LN10 / 80.0f)) * alpha;
    float b0, b1, b2, a0, a1, a2;

    switch (kind) {
    case RBJ_LOWPASS:
        b0 = 0.5f * (1.0f - cw);
        b1 = 1.0f - cw;
        b2 = b0;
        a0 = 1.0f + alpha;
        a1 = -2.0f * cw;
        a2 = 1.0f - alpha;
        break;
    case RBJ_HIGHPASS:
        b0 = 0.5f * (1.0f + cw);
        b1 = -(1.0f + cw);
        b2 = b0;
        a0 = 1.0f + alpha;
        a1 = -2.0f * cw;
        a2 = 1.0f - alpha;
        break;
    case RBJ_PEAK:
        b0 = 1.0f + alpha * a;
        b1 = -2.0f * cw;
        b2 = 1.0f - alpha * a;
        a0 = 1.0f + alpha / a;
        a1 = -2.0f * cw;
        a2 = 1.0f - alpha / a;
        break;
    case RBJ_LOW_SHELF:
        b0 = a * ((a + 1.0f) - (a - 1.0f) * cw + k);
        b1 = 2.0f * a * ((a - 1.0f) - (a + 1.0f) * cw);
        b2 = a * ((a + 1.0f) - (a - 1.0f) * cw - k);
        a0 = (a + 1.0f) + (a - 1.0f) * cw + k;
        a1 = -2.0f * ((a - 1.0f) + (a + 1.0f) * cw);
        a2 = (a + 1.0f) + (a - 1.0f) * cw - k;
        break;
    case RBJ_HIGH_SHELF:
    default:
        b0 = a * ((a + 1.0f) + (a - 1.0f) * cw + k);
        b1 = -2.0f * a * ((a - 1.0f) + (a + 1.0f) * cw);
        b2 = a * ((a + 1.0f) + (a - 1.0f) * cw - k);
        a0 = (a + 1.0f) - (a - 1.0f) * cw + k;
        a1 = 2.0f * ((a - 1.0f) - (a + 1.0f) * cw);
        a2 = (a + 1.0f) - (a - 1.0f) * cw - k;
        break;
    }

    const float inv = 1.0f / a0;
    add_section(n, b0 * inv, b1 * inv, b2 * inv, a1 * inv, a2 * inv, fc);
}

static void design_filter(const speaker_eq_filter_t *f, float fs, unsigned *n)
{
    const float fc = f->freq_hz;

    if (filter_sections(f) == 0) {
        return;
    }

    switch (f->type) {
    case SPEAKER_EQ_FILTER_PEAK:
        add_rbj(n, RBJ_PEAK, fc, fs, f->q, f->gain_db);
        break;
    case SPEAKER_EQ_FILTER_LOW_SHELF:
        add_rbj(n, RBJ_LOW_SHELF, fc, fs, f->q, f->gain_db);
        break;
    case SPEAKER_EQ_FILTER_HIGH_SHELF:
        add_rbj(n, RBJ_HIGH_SHELF, fc, fs, f->q, f->gain_db);
        break;
    case SPEAKER_EQ_FILTER_HIGHPASS_Q:
        add_rbj(n, RBJ_HIGHPASS, fc, fs, f->q, 0.0f);
        break;
    case SPEAKER_EQ_FILTER_LOWPASS_Q:
        add_rbj(n, RBJ_LOWPASS, fc, fs, f->q, 0.0f);
        break;
    case SPEAKER_EQ_FILTER_HIGHPASS_BW12:
        add_rbj(n, RBJ_HIGHPASS, fc, fs, Q_BUTTERWORTH, 0.0f);
        break;
    case SPEAKER_EQ_FILTER_HIGHPASS_LR12:
        add_rbj(n, RBJ_HIGHPASS, fc, fs, Q_LR12, 0.0f);
        break;
    case SPEAKER_EQ_FILTER_HIGHPASS_BW24:
        add_rbj(n, RBJ_HIGHPASS, fc, fs, Q_BW24_A, 0.0f);
        add_rbj(n, RBJ_HIGHPASS, fc, fs, Q_BW24_B, 0.0f);
        break;
    case SPEAKER_EQ_FILTER_HIGHPASS_LR24:
        add_rbj(n, RBJ_HIGHPASS, fc, fs, Q_BUTTERWORTH, 0.0f);
        add_rbj(n, RBJ_HIGHPASS, fc, fs, Q_BUTTERWORTH, 0.0f);
        break;
    case SPEAKER_EQ_FILTER_LOWPASS_BW12:
        add_rbj(n, RBJ_LOWPASS, fc, fs, Q_BUTTERWORTH, 0.0f);
        break;
    case SPEAKER_EQ_FILTER_LOWPASS_LR12:
        add_rbj(n, RBJ_LOWPASS, fc, fs, Q_LR12, 0.0f);
        break;
    case SPEAKER_EQ_FILTER_LOWPASS_BW24:
        add_rbj(n, RBJ_LOWPASS, fc, fs, Q_BW24_A, 0.0f);
        add_rbj(n, RBJ_LOWPASS, fc, fs, Q_BW24_B, 0.0f);
        break;
    case SPEAKER_EQ_FILTER_LOWPASS_LR24:
        add_rbj(n, RBJ_LOWPASS, fc, fs, Q_BUTTERWORTH, 0.0f);
        add_rbj(n, RBJ_LOWPASS, fc, fs, Q_BUTTERWORTH, 0.0f);
        break;
    default:
        break;
    }
}

static float section_mag2(const eq_section_t *s,
                          float cos1, float sin1, float cos2, float sin2)
{
    const float nr = s->b0 + s->b1 * cos1 + s->b2 * cos2;
    const float ni = s->b1 * sin1 + s->b2 * sin2;
    const float dr = 1.0f + s->a1 * cos1 + s->a2 * cos2;
    const float di = s->a1 * sin1 + s->a2 * sin2;
    float den = dr * dr + di * di;

    if (den < 1e-20f) {
        den = 1e-20f;
    }
    return (nr * nr + ni * ni) / den;
}

/*
 * Analysis grid: log-spaced points across the band plus every section's
 * centre frequency, so narrow peaks between grid points are not missed.
 */
typedef struct {
    float hz;
    float ratio;
    unsigned index;
} eq_grid_t;

static void grid_start(eq_grid_t *g, float fs)
{
    g->hz = EQ_GRID_LOW_HZ;
    g->ratio = expf(logf(EQ_GRID_HIGH_FRAC * fs / EQ_GRID_LOW_HZ) /
                    (float)(EQ_GRID_POINTS - 1));
    g->index = 0;
}

static bool grid_next(eq_grid_t *g, unsigned n, float fs,
                      float *cos1, float *sin1, float *cos2, float *sin2)
{
    float hz;

    if (g->index < EQ_GRID_POINTS) {
        hz = g->hz;
        g->hz *= g->ratio;
    } else if (g->index < EQ_GRID_POINTS + n) {
        hz = sections[g->index - EQ_GRID_POINTS].fc;
    } else {
        return false;
    }
    g->index++;

    const float w = EQ_TWO_PI * hz / fs;
    *cos1 = f32_cos(w);
    *sin1 = f32_sin(w);
    *cos2 = 2.0f * *cos1 * *cos1 - 1.0f;
    *sin2 = 2.0f * *sin1 * *cos1;
    return true;
}

static float mag2_to_db(float mag2)
{
    if (mag2 < 1e-12f) {
        mag2 = 1e-12f;
    }
    return EQ_DB_PER_LN * 0.5f * logf(mag2);
}

bool speaker_eq_design(const speaker_eq_slot_params_t *params,
                       float fs,
                       speaker_eq_bank_t *bank,
                       speaker_eq_analysis_t *analysis)
{
    unsigned n = 0;
    uint8_t order[SPEAKER_EQ_MAX_SECTIONS];
    unsigned n_order = 0;
    const float pre_db = params->preamp_db < 0.0f ? params->preamp_db : 0.0f;
    const float post_db = params->preamp_db > 0.0f ? params->preamp_db : 0.0f;
    const float pre_mag2 = db_to_lin(2.0f * pre_db);
    const float post_mag2 = db_to_lin(2.0f * post_db);
    float worst_mag2 = 0.0f;
    float net_mag2 = 0.0f;
    float cos1, sin1, cos2, sin2;
    eq_grid_t grid;

    for (unsigned i = 0; i < params->filter_count && i < SPEAKER_EQ_MAX_FILTERS; i++) {
        const unsigned first = n;
        if (n + filter_sections(&params->filters[i]) > SPEAKER_EQ_MAX_SECTIONS) {
            break;
        }
        design_filter(&params->filters[i], fs, &n);
        /* The type is part of the id, so a peak that becomes a shelf crossfades: a glide between
         * unrelated filters passes through responses the headroom check never saw. */
        for (unsigned s = first; s < n; s++) {
            sections[s].id = (uint16_t)((params->filters[i].type << 5) | (2 * i + (s - first)));
        }
    }

    grid_start(&grid, fs);
    while (grid_next(&grid, n, fs, &cos1, &sin1, &cos2, &sin2)) {
        for (unsigned s = 0; s < n; s++) {
            const float m = section_mag2(&sections[s], cos1, sin1, cos2, sin2);
            if (m > sections[s].max_mag2) {
                sections[s].max_mag2 = m;
            }
        }
    }

    /* Cuts first, then boosts, so intermediate levels stay low. */
    for (unsigned s = 0; s < n; s++) {
        if (sections[s].max_mag2 <= EQ_BOOST_MAG2) {
            order[n_order++] = (uint8_t)s;
        }
    }
    for (unsigned s = 0; s < n; s++) {
        if (sections[s].max_mag2 > EQ_BOOST_MAG2) {
            order[n_order++] = (uint8_t)s;
        }
    }

    grid_start(&grid, fs);
    while (grid_next(&grid, n, fs, &cos1, &sin1, &cos2, &sin2)) {
        float level = pre_mag2;

        if (level > worst_mag2) {
            worst_mag2 = level;
        }
        for (unsigned k = 0; k < n_order; k++) {
            level *= section_mag2(&sections[order[k]], cos1, sin1, cos2, sin2);
            if (level > worst_mag2) {
                worst_mag2 = level;
            }
        }
        level *= post_mag2;
        if (level > worst_mag2) {
            worst_mag2 = level;
        }
        if (level > net_mag2) {
            net_mag2 = level;
        }
    }

    analysis->sections = (uint8_t)n;
    analysis->max_gain_db = mag2_to_db(net_mag2);
    analysis->peak_gain_db = mag2_to_db(worst_mag2);

    if (analysis->peak_gain_db > SPEAKER_EQ_HEADROOM_CAP_DB) {
        return false;
    }

    if (n == 0 && params->preamp_db == 0.0f) {
        speaker_eq_bank_set_bypass(bank, SPEAKER_EQ_BYPASS_FLAT);
        return true;
    }

    memset(bank, 0, sizeof(*bank));
    for (unsigned k = 0; k < n_order; k++) {
        const eq_section_t *s = &sections[order[k]];
        memcpy(bank->coeffs[k], s->c, sizeof(s->c));
        bank->lsh[k] = (int8_t)s->lsh;
        bank->section_id[k] = s->id;
    }
    bank->num_sections = (uint8_t)n;
    bank->pre_gain = to_fixed(db_to_lin(pre_db), Q_GAIN);
    bank->post_gain = to_fixed(db_to_lin(post_db), Q_GAIN);

    bank->limiter_threshold = to_fixed(db_to_lin(params->limiter_db), Q_SIG);
    if (bank->limiter_threshold < 1) {
        bank->limiter_threshold = 1;
    }
    bank->attack_alpha = calc_alpha(fs, params->attack_ms / 1000.0f);
    bank->release_alpha = calc_alpha(fs, params->release_ms / 1000.0f);
    bank->limiter_required =
        analysis->max_gain_db > params->limiter_db + EQ_LIMITER_SLACK_DB;
    bank->active = 1;
    bank->reason = SPEAKER_EQ_BYPASS_NONE;
    return true;
}

#endif
