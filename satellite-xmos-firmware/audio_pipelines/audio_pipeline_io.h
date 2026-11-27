#ifndef AUDIO_PIPELINE_IO_H_
#define AUDIO_PIPELINE_IO_H_

#include <stddef.h>
#include <stdint.h>

/* The microphone driver writes all channels into one channel-major buffer. */
void audio_pipeline_capture(void *mic_samples,
                            int32_t *reference_left,
                            int32_t *reference_right,
                            size_t frame_count);

int audio_pipeline_output_channels(const int32_t *processed_samples,
                                   const int32_t *ns_samples,
                                   size_t frame_count);

#endif /* AUDIO_PIPELINE_IO_H_ */
