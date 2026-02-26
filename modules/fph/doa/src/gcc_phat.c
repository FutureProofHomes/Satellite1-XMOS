// doa4_gcc_phat.c
// GCC-PHAT DOA estimator for 4-mic circular array using lib_xcore_math
//
// Matches doa4_gcc_phat.h API.
//
// Assumptions (IMPORTANT):
//   - Input buffer layout is [240 mic0][240 mic1][240 mic2][240 mic3].
//   - Mic geometry mapping used for DOA is:
//       mic0 at 0°, mic1 at 90°, mic2 at 180°, mic3 at 270°
//     i.e. p0=(+r,0), p1=(0,+r), p2=(-r,0), p3=(0,-r)
//   - Angle returned is atan2(u_y, u_x) in radians.
//     If your physical mic order differs, update the mapping in doa_from_lags().

#include "gcc_phat.h"
#include <string.h>
#include <math.h>

#ifndef GCC_PHAT_EPS_MANT
#define GCC_PHAT_EPS_MANT (1)   // magnitude clamp to avoid divide-by-zero
#endif

// --- Utility: signed lag from correlation index in circular buffer ---
static inline int signed_lag(unsigned idx, unsigned N) {
  return (idx > (N / 2)) ? ((int)idx - (int)N) : (int)idx;
}

// --- DOA from 3 lags for 4 mics on circle at 0,90,180,270 deg ---
// Returns radians.
static float doa_from_lags(int lag10, int lag20, int lag30)
{
  const float r  = DOA4_ARRAY_RADIUS_M;
  const float fs = DOA4_SAMPLE_RATE_HZ;
  const float c  = DOA4_SPEED_OF_SOUND;

  // Positions:
  // p0=( r, 0), p1=(0, r), p2=(-r,0), p3=(0,-r)
  // A rows are (pi - p0):
  // a1 = (-r,  r)
  // a2 = (-2r, 0)
  // a3 = (-r, -r)
  const float a1x = -r,    a1y =  r;
  const float a2x = -2*r,  a2y =  0.0f;
  const float a3x = -r,    a3y = -r;

  const float b1 = c * ((float)lag10 / fs);
  const float b2 = c * ((float)lag20 / fs);
  const float b3 = c * ((float)lag30 / fs);

  // ATA = A^T A (2x2)
  const float ata00 = a1x*a1x + a2x*a2x + a3x*a3x;
  const float ata01 = a1x*a1y + a2x*a2y + a3x*a3y;
  const float ata11 = a1y*a1y + a2y*a2y + a3y*a3y;

  // ATb = A^T b (2x1)
  const float atb0  = a1x*b1 + a2x*b2 + a3x*b3;
  const float atb1  = a1y*b1 + a2y*b2 + a3y*b3;

  // Invert ATA
  const float det = ata00*ata11 - ata01*ata01;
  if (fabsf(det) < 1e-12f) return 0.0f;

  const float inv00 =  ata11 / det;
  const float inv01 = -ata01 / det;
  const float inv11 =  ata00 / det;

  float ux = inv00*atb0 + inv01*atb1;
  float uy = inv01*atb0 + inv11*atb1;

  // Normalize to unit direction (recommended)
  const float n = sqrtf(ux*ux + uy*uy);
  if (n > 1e-12f) { ux /= n; uy /= n; }

  return atan2f(uy, ux);
}

// --- GCC-PHAT using already-FFT’d spectra (unpacked mono FFT, length DOA4_SPEC_BINS) ---
// Returns signed lag in samples (circular correlation), peak searched within ±max_lag.
static int gcc_phat_from_spectra(
    bfp_complex_s32_t *Z,     // length K, scratch
    bfp_s32_t         *mag,   // length K, scratch
    bfp_s32_t         *corr,  // length N, scratch/output
    const bfp_complex_s32_t *A,
    const bfp_complex_s32_t *B,
    unsigned max_lag
){
  const unsigned N = DOA4_FFT_LENGTH;
  const unsigned K = DOA4_SPEC_BINS;

  // Z = A * conj(B)
  exponent_t z_exp;
  right_shift_t a_shr, b_shr;

  vect_complex_s32_conj_mul_prepare(
      &z_exp, &a_shr, &b_shr,
      A->exp, B->exp,
      A->hr,  B->hr
  );

  vect_complex_s32_conj_mul(
      Z->data, A->data, B->data,
      K, a_shr, b_shr
  );

  Z->exp = z_exp;
  Z->hr  = bfp_complex_s32_headroom(Z);

  // Optional: zero DC & Nyquist to avoid odd dominance / div-by-zero sensitivity
  Z->data[0].re   = 0; Z->data[0].im   = 0;
  Z->data[K-1].re = 0; Z->data[K-1].im = 0;

  // mag = |Z|
  bfp_complex_s32_mag(mag, Z);

  // Clamp magnitude to epsilon (in mantissa units)
  for (unsigned k = 0; k < K; ++k) {
    if (mag->data[k] == 0) mag->data[k] = GCC_PHAT_EPS_MANT;
  }
  mag->hr = bfp_s32_headroom(mag);

  // w = 1/mag (in-place ok)
  bfp_s32_t w = *mag;
  bfp_s32_inverse(&w, mag);

  // Z *= w (PHAT)
  bfp_complex_s32_real_mul(Z, Z, &w);

  // IFFT: unpacked -> pack -> inverse
  const uint32_t zlen = Z->length;
  bfp_fft_pack_mono(Z);
  bfp_s32_t *tmp = bfp_fft_inverse_mono(Z);
  memcpy(corr, tmp, sizeof(*corr));
  Z->length = zlen;

  // Peak search within ±max_lag (circular)
  // Search [0..max_lag] and [N-max_lag..N-1]
  if (max_lag == 0 || max_lag >= (N/2)) {
    unsigned peak = bfp_s32_argmax(corr);
    return signed_lag(peak, N);
  }

  // Segment A: 0..max_lag
  bfp_s32_t segA;
  bfp_s32_init(&segA, &corr->data[0], corr->exp, max_lag + 1, 1);
  const unsigned idxA = bfp_s32_argmax(&segA);
  const float_s32_t bestA = bfp_s32_max(&segA);

  // Segment B: N-max_lag..N-1
  bfp_s32_t segB;
  bfp_s32_init(&segB, &corr->data[N - max_lag], corr->exp, max_lag, 1);
  const unsigned idxB = bfp_s32_argmax(&segB) + (N - max_lag);
  const float_s32_t bestB = bfp_s32_max(&segB);

  const unsigned peak = float_s32_gt(bestB, bestA) ? idxB : idxA;
  return signed_lag(peak, N);
}

void doa4_init(doa4_state_t *state)
{
  memset(state, 0, sizeof(*state));

  // Init BFP wrappers (buffers are owned by the state)
  for (unsigned m = 0; m < DOA4_NUM_MICS; ++m) {
    bfp_complex_s32_init(&state->Spec[m],
                         state->spec_mem[m],
                         /*exp=*/0,
                         /*length=*/DOA4_SPEC_BINS,
                         /*calc_hr=*/1);
  }

  bfp_complex_s32_init(&state->Z,
                       state->z_mem,
                       /*exp=*/0,
                       /*length=*/DOA4_SPEC_BINS,
                       /*calc_hr=*/1);

  bfp_s32_init(&state->Mag,
               state->mag_mem,
               /*exp=*/0,
               /*length=*/DOA4_SPEC_BINS,
               /*calc_hr=*/1);

  bfp_s32_init(&state->Corr,
               state->corr_mem,
               /*exp=*/0,
               /*length=*/DOA4_FFT_LENGTH,
               /*calc_hr=*/1);
}

float doa4_process_frame(doa4_state_t *state,
                         const int32_t *input,
                         exponent_t in_exp)
{
  // 1) Build 256-sample frames per mic: tail16 + new240
  for (unsigned m = 0; m < DOA4_NUM_MICS; ++m) {
    // Copy tail
    memcpy(&state->td[m][0],
           &state->tail[m][0],
           DOA4_TAIL_SAMPLES * sizeof(int32_t));

    // Copy new block
    memcpy(&state->td[m][DOA4_TAIL_SAMPLES],
           &input[m * DOA4_FRAME_ADVANCE],
           DOA4_FRAME_ADVANCE * sizeof(int32_t));

    // Update tail for next call (last 16 samples of current FFT frame)
    memcpy(&state->tail[m][0],
           &state->td[m][DOA4_FFT_LENGTH - DOA4_TAIL_SAMPLES],
           DOA4_TAIL_SAMPLES * sizeof(int32_t));
  }

  // 2) FFT each mic (real mono forward + unpack)
  for (unsigned m = 0; m < DOA4_NUM_MICS; ++m) {
    bfp_s32_t td_bfp;
    bfp_s32_init(&td_bfp, state->td[m], in_exp, DOA4_FFT_LENGTH, 1);

    // Forward FFT in-place (mono packed)
    const uint32_t len = td_bfp.length;
    bfp_complex_s32_t *tmp = bfp_fft_forward_mono(&td_bfp);

    // Workaround noted in your AEC codebase style
    tmp->hr = bfp_complex_s32_headroom(tmp);

    // Copy returned view + unpack to (N/2)+1 bins
    memcpy(&state->Spec[m], tmp, sizeof(bfp_complex_s32_t));
    bfp_fft_unpack_mono(&state->Spec[m]);

    td_bfp.length = len;
  }

  // 3) GCC-PHAT lags vs mic0
  const int lag10 = gcc_phat_from_spectra(&state->Z, &state->Mag, &state->Corr,
                                         &state->Spec[1], &state->Spec[0],
                                         DOA4_MAX_LAG_SAMPLES);
  const int lag20 = gcc_phat_from_spectra(&state->Z, &state->Mag, &state->Corr,
                                         &state->Spec[2], &state->Spec[0],
                                         DOA4_MAX_LAG_SAMPLES);
  const int lag30 = gcc_phat_from_spectra(&state->Z, &state->Mag, &state->Corr,
                                         &state->Spec[3], &state->Spec[0],
                                         DOA4_MAX_LAG_SAMPLES);

  // 4) Convert lags to DOA (radians)
  return doa_from_lags(lag10, lag20, lag30);
}