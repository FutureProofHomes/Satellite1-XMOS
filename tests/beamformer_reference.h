/* Frozen pre-optimization rational arithmetic, used only by differential tests. */
static int32_t reference_fractional_delay_sample(
    const int32_t *input,
    const int32_t history[SAT1_BEAMFORMER_HISTORY_SAMPLES],
    size_t sample_index,
    int delay_q8)
{
    int whole_samples = delay_q8 / DOA_ESTIMATOR_LAG_Q8_SCALE;
    int fraction_q8 = delay_q8 % DOA_ESTIMATOR_LAG_Q8_SCALE;
    int newest_index = (int)sample_index - whole_samples;
    int32_t sample0 = sample_at(input, history, newest_index);
    if (fraction_q8 == 0) {
        return sample0;
    }
    int32_t sample1 = sample_at(input, history, newest_index - 1);
    int32_t sample2 = sample_at(input, history, newest_index - 2);
    int32_t sample3 = sample_at(input, history, newest_index - 3);
    int64_t scale = DOA_ESTIMATOR_LAG_Q8_SCALE;
    int64_t fraction = fraction_q8;
    int64_t numerator =
        (int64_t)sample0 * (scale - fraction) *
            ((2 * scale) - fraction) * ((3 * scale) - fraction) +
        (int64_t)sample1 * 3 * fraction *
            ((2 * scale) - fraction) * ((3 * scale) - fraction) -
        (int64_t)sample2 * 3 * fraction *
            (scale - fraction) * ((3 * scale) - fraction) +
        (int64_t)sample3 * fraction *
            (scale - fraction) * ((2 * scale) - fraction);
    const int64_t denominator = 6 * scale * scale * scale;
    numerator += numerator >= 0 ? denominator / 2 : -denominator / 2;
    return saturate_i32(numerator / denominator);
}
