#include <stdint.h>
#include <string.h>
#include <math.h>

static inline float wrap_0_2pi(float a){
  const float two_pi = 6.2831853071795864769f;
  while(a < 0.0f)      a += two_pi;
  while(a >= two_pi)   a -= two_pi;
  return a;
}

// Set one LED in GRB order
static inline void led_set_grb(uint8_t *led_buffer, unsigned i, uint8_t g, uint8_t r, uint8_t b){
  // Buffer order is [G,B,R,...] per your note
  // So: G at +0, B at +1, R at +2
  unsigned base = 3u * i;
  led_buffer[base + 0] = g;
  led_buffer[base + 1] = b;
  led_buffer[base + 2] = r;
}

// Simple DOA -> LED ring renderer
// ang_rad: output of doa4_process_frame() (atan2 style, radians)
// num_leds: LED_RING_NUM_LEDS
// led0_angle_offset_rad: rotate mapping so "front" points at desired LED (often 0, +pi/2, etc.)
// led_index_offset: additional integer offset (if easier than radians)
// brightness: 0..255
void led_ring_show_doa(
    uint8_t *led_buffer,
    unsigned num_leds,
    float ang_rad,
    float led0_angle_offset_rad,
    int led_index_offset,
    uint8_t brightness
){
  // clear
  memset(led_buffer, 0, num_leds * 3);

  // map angle -> [0..num_leds)
  float a = wrap_0_2pi(ang_rad + led0_angle_offset_rad);
  float pos = (a / (2.0f * (float)M_PI)) * (float)num_leds;

  int center = (int)lroundf(pos);
  center = (center + led_index_offset) % (int)num_leds;
  if(center < 0) center += (int)num_leds;

  // 3-LED blob (center + neighbors) with crude falloff
  // You can change these weights
  const uint8_t w0 = brightness;            // center
  const uint8_t w1 = (uint8_t)(brightness / 3);  // neighbors

  int left  = (center - 1 + (int)num_leds) % (int)num_leds;
  int right = (center + 1) % (int)num_leds;

  // Pick a color (green blob). Adjust as desired.
  led_set_grb(led_buffer, (unsigned)center, w0, 0, 0); // G
  led_set_grb(led_buffer, (unsigned)left,   w1, 0, 0);
  led_set_grb(led_buffer, (unsigned)right,  w1, 0, 0);
}