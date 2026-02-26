#ifndef FPH_DOA_H_
#define FPH_DOA_H_

#include <stdint.h>

void led_ring_show_doa(
    uint8_t *led_buffer,
    unsigned num_leds,
    float ang_rad,
    float led0_angle_offset_rad,
    int led_index_offset,
    uint8_t brightness
);

#endif