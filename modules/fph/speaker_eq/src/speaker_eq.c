#include "speaker_eq.h"

#include <limits.h>
#include <string.h>

#include "dsp/adsp.h"

void speaker_eq_reset(speaker_eq_t *eq)
{
    if (eq != NULL) {
        memset(eq->state, 0, sizeof(eq->state));
    }
}

speaker_eq_status_t speaker_eq_apply_program(
    speaker_eq_t *eq,
    const speaker_eq_program_t *program)
{
    if (eq == NULL || program == NULL) {
        return SPEAKER_EQ_STATUS_INVALID_ARGUMENT;
    }
    if (program->channel_mode != SPEAKER_EQ_MODE_STEREO_LINKED &&
        program->channel_mode != SPEAKER_EQ_MODE_MONO) {
        return SPEAKER_EQ_STATUS_INVALID_CHANNEL_MODE;
    }

    memcpy(&eq->program, program, sizeof(eq->program));
    speaker_eq_reset(eq);
    return SPEAKER_EQ_STATUS_OK;
}

speaker_eq_status_t speaker_eq_init(
    speaker_eq_t *eq,
    const speaker_eq_program_t *initial_program)
{
    if (eq == NULL || initial_program == NULL) {
        return SPEAKER_EQ_STATUS_INVALID_ARGUMENT;
    }

    memset(eq, 0, sizeof(*eq));
    return speaker_eq_apply_program(eq, initial_program);
}

static int32_t process_sample(speaker_eq_t *eq,
                              int32_t sample,
                              size_t channel)
{
    sample = adsp_fixed_gain(sample, eq->program.pregain_q27);
    sample = adsp_cascaded_biquads_8b(
        sample,
        eq->program.coeffs,
        eq->state[channel],
        eq->program.shifts);

    if (eq->program.clip_threshold < INT32_MAX) {
        sample = adsp_clipper(eq->program.clip_threshold, sample);
    }
    return sample;
}

void speaker_eq_process_frame(
    speaker_eq_t *eq,
    int32_t *channels[SPEAKER_EQ_CHANNEL_COUNT],
    size_t frame_length)
{
    if (eq == NULL || channels == NULL ||
        channels[0] == NULL || channels[1] == NULL) {
        return;
    }

    if (eq->program.channel_mode == SPEAKER_EQ_MODE_MONO) {
        for (size_t i = 0; i < frame_length; ++i) {
            int32_t sample = (int32_t)(((int64_t)channels[0][i] +
                                        (int64_t)channels[1][i]) / 2);
            if (!eq->program.bypass) {
                sample = process_sample(eq, sample, 0);
            }
            channels[0][i] = sample;
            channels[1][i] = sample;
        }
        return;
    }

    if (eq->program.bypass) {
        return;
    }

    for (size_t channel = 0; channel < SPEAKER_EQ_CHANNEL_COUNT; ++channel) {
        for (size_t i = 0; i < frame_length; ++i) {
            channels[channel][i] = process_sample(
                eq, channels[channel][i], channel);
        }
    }
}
