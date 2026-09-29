#ifndef BIQUAD_EQ_H
#define BIQUAD_EQ_H

#include <stdint.h>
#include <stddef.h>

/*
 * 3-Band Parametric EQ for speaker output (48 kHz, int32_t samples).
 *
 * All coefficients are Q28 fixed-point (1 sign, 3 integer, 28 fractional bits).
 * Direct Form I biquad with int64_t accumulator.
 *
 * Band definitions (peaking EQ, Audio EQ Cookbook):
 *   Band 1: 1825 Hz, -7.7 dB, Q=2.00
 *   Band 2: 3542 Hz, -10.0 dB, Q=2.66
 *   Band 3:  166 Hz, -6.1 dB, Q=1.10
 */

#define BIQUAD_EQ_NUM_BANDS 3
#define BIQUAD_EQ_Q28_SHIFT 28

typedef struct {
    int32_t x1, x2;  /* input history  */
    int32_t y1, y2;  /* output history */
} biquad_state_t;

typedef struct {
    int32_t b0, b1, b2;
    int32_t a1, a2;
} biquad_coeffs_t;

/* Pre-computed Q28 coefficients for each band (Fs = 48000 Hz) */
static const biquad_coeffs_t biquad_eq_bands[BIQUAD_EQ_NUM_BANDS] = {
    /* Band 1: 1825 Hz, -7.7 dB, Q=2.00 */
    {  255119724, -477611531,  236452069, -477611531,  223136337 },
    /* Band 2: 3542 Hz, -10.0 dB, Q=2.66 */
    {  244565590, -417744852,  222487144, -417744852,  198617278 },
    /* Band 3: 166 Hz, -6.1 dB, Q=1.10 */
    {  266561400, -529317299,  262880886, -529317299,  261006830 },
};

static inline int32_t biquad_process_sample(const biquad_coeffs_t *c,
                                            biquad_state_t *s,
                                            int32_t x)
{
    int64_t acc;
    acc  = (int64_t)c->b0 * (int64_t)x;
    acc += (int64_t)c->b1 * (int64_t)s->x1;
    acc += (int64_t)c->b2 * (int64_t)s->x2;
    acc -= (int64_t)c->a1 * (int64_t)s->y1;
    acc -= (int64_t)c->a2 * (int64_t)s->y2;

    int32_t y = (int32_t)(acc >> BIQUAD_EQ_Q28_SHIFT);

    s->x2 = s->x1;
    s->x1 = x;
    s->y2 = s->y1;
    s->y1 = y;

    return y;
}

/*
 * Apply 3 cascaded biquad bands to a frame of samples for one channel.
 *
 * buf:    pointer to first sample (stride = sample_stride int32_t's)
 * states: array of BIQUAD_EQ_NUM_BANDS biquad_state_t for this channel
 * count:  number of samples in the frame
 * sample_stride: distance in int32_t's between consecutive samples
 */
static inline void biquad_eq_process_frame(int32_t *buf,
                                           biquad_state_t states[],
                                           size_t count,
                                           size_t sample_stride)
{
    for (size_t i = 0; i < count; i++) {
        int32_t sample = buf[i * sample_stride];
        for (int b = 0; b < BIQUAD_EQ_NUM_BANDS; b++) {
            sample = biquad_process_sample(&biquad_eq_bands[b],
                                           &states[b], sample);
        }
        buf[i * sample_stride] = sample;
    }
}

#endif /* BIQUAD_EQ_H */
