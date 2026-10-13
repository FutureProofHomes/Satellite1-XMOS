#pragma once

/*
 * Speaker EQ device-control protocol (resource 231).
 *
 * All multi-byte fields are little endian. Floats are IEEE-754 binary32.
 * Payload sizes are fixed; device control rejects any other length.
 * ESPHome's satellite1_dsp component mirrors these definitions in
 * speaker_eq_protocol.h; change both together.
 */

#define SPEAKER_EQ_RESID                     231

#define SPEAKER_EQ_API_MAJOR                 1
#define SPEAKER_EQ_API_MINOR                 0

#define SPEAKER_EQ_CMD_GET_INFO              0   /* read,  SPEAKER_EQ_INFO_BYTES */
#define SPEAKER_EQ_CMD_GET_STATS             1   /* read,  SPEAKER_EQ_STATS_BYTES */
#define SPEAKER_EQ_CMD_SET_ROUTING           2   /* write, SPEAKER_EQ_ROUTING_BYTES */
#define SPEAKER_EQ_CMD_SET_SLOT              3   /* write, SPEAKER_EQ_SLOT_BYTES */
#define SPEAKER_EQ_CMD_GET_SLOT              4   /* read,  SPEAKER_EQ_SLOT_BYTES */

/*
 * SET_ROUTING payload (2 bytes): u8 eq_enabled (0 or 1), u8 profile_id.
 * Switches the EQ and selects which slot plays.
 */
#define SPEAKER_EQ_ROUTING_BYTES             2

typedef enum {
    SPEAKER_EQ_PROFILE_NONE = 0,
    SPEAKER_EQ_PROFILE_1 = 1,            /* Built-in Speaker slot */
    SPEAKER_EQ_PROFILE_2 = 2,            /* Line-out slot */

    SPEAKER_EQ_NUM_PROFILES
} speaker_eq_profile_id_t;

#define SPEAKER_EQ_NUM_SLOTS                 2
#define SPEAKER_EQ_MAX_FILTERS               14
#define SPEAKER_EQ_MAX_SECTIONS              16

/*
 * SET_SLOT / GET_SLOT payload (214 bytes):
 *   0   u8   slot            1 = Built-in Speaker (PROFILE_1), 2 = Line-out (PROFILE_2)
 *   1   f32  preamp_db       -24 .. +12
 *   5   f32  limiter_db      -12 .. 0     (peak ceiling, dBFS)
 *   9   f32  attack_ms       0.1 .. 100
 *   13  f32  release_ms      5 .. 5000
 *   17  u8   filter_count    0 .. 14
 *   18  filter[14], 14 bytes each:
 *         0  u8   type       speaker_eq_filter_type_t
 *         1  u8   flags      bit 0 = enabled
 *         2  f32  freq_hz    20 .. 20000
 *         6  f32  gain_db    peak/shelf only: -30 .. +12
 *         10 f32  q          0.1 .. 10 (peak, shelf, custom-Q cut)
 * GET_SLOT returns the slot most recently written.
 */
#define SPEAKER_EQ_FILTER_RECORD_BYTES       14
#define SPEAKER_EQ_SLOT_HEADER_BYTES         18
#define SPEAKER_EQ_SLOT_BYTES \
    (SPEAKER_EQ_SLOT_HEADER_BYTES + \
     SPEAKER_EQ_MAX_FILTERS * SPEAKER_EQ_FILTER_RECORD_BYTES)

#define SPEAKER_EQ_FILTER_FLAG_ENABLED       0x01

typedef enum {
    SPEAKER_EQ_FILTER_NONE = 0,
    SPEAKER_EQ_FILTER_PEAK = 1,
    SPEAKER_EQ_FILTER_LOW_SHELF = 2,
    SPEAKER_EQ_FILTER_HIGH_SHELF = 3,
    SPEAKER_EQ_FILTER_HIGHPASS_Q = 4,      /* 12 dB/oct, custom Q */
    SPEAKER_EQ_FILTER_LOWPASS_Q = 5,       /* 12 dB/oct, custom Q */
    SPEAKER_EQ_FILTER_HIGHPASS_BW12 = 6,
    SPEAKER_EQ_FILTER_HIGHPASS_BW24 = 7,
    SPEAKER_EQ_FILTER_HIGHPASS_LR12 = 8,
    SPEAKER_EQ_FILTER_HIGHPASS_LR24 = 9,
    SPEAKER_EQ_FILTER_LOWPASS_BW12 = 10,
    SPEAKER_EQ_FILTER_LOWPASS_BW24 = 11,
    SPEAKER_EQ_FILTER_LOWPASS_LR12 = 12,
    SPEAKER_EQ_FILTER_LOWPASS_LR24 = 13,

    SPEAKER_EQ_NUM_FILTER_TYPES
} speaker_eq_filter_type_t;

/*
 * GET_INFO payload (40 bytes):
 *   0   u8   api_major
 *   1   u8   api_minor
 *   2   u8   max_filters
 *   3   u8   max_sections
 *   4   u32  sample_rate
 *   8   u8   eq_enabled         as last set through SET_ROUTING
 *   9   u8   profile_id         0 = none, 1, 2
 *   10  u8   bypass_reason      speaker_eq_bypass_reason_t
 *   11  u8   limiter_required   active profile can exceed the limiter ceiling
 *   12  u8   slot_status[2]     speaker_eq_slot_status_t
 *   14  u8   slot_sections[2]
 *   16  f32  slot_max_gain_db[2]   net response maximum
 *   24  f32  slot_peak_gain_db[2]  worst gain at any section boundary
 *   32  u32  design_count
 *   36  u32  bank_seq
 */
#define SPEAKER_EQ_INFO_BYTES                40

typedef enum {
    SPEAKER_EQ_BYPASS_NONE = 0,         /* processing */
    SPEAKER_EQ_BYPASS_DISABLED = 1,     /* eq_enabled == 0 */
    SPEAKER_EQ_BYPASS_NO_PROFILE = 2,   /* profile NONE or slot never written */
    SPEAKER_EQ_BYPASS_FLAT = 3,         /* profile has no effect */
    SPEAKER_EQ_BYPASS_OVERLOAD = 4,     /* CPU watchdog tripped */
} speaker_eq_bypass_reason_t;

typedef enum {
    SPEAKER_EQ_SLOT_EMPTY = 0,
    SPEAKER_EQ_SLOT_OK = 1,
    SPEAKER_EQ_SLOT_REJECTED_HEADROOM = 2,
    SPEAKER_EQ_SLOT_PENDING = 3,
} speaker_eq_slot_status_t;

/* Worst gain allowed at any section boundary; leaves 6 dB of the Q27 range. */
#define SPEAKER_EQ_HEADROOM_CAP_DB           18.0f

/*
 * GET_STATS payload (48 bytes):
 *   0   u32  frames
 *   4   u16  eq_us_max[2]       per channel, since boot
 *   8   u16  eq_us_avg[2]
 *   12  u16  eq_us_last[2]
 *   16  u32  overruns           frames where a channel took over 4 ms
 *   20  u8   bypass_reason
 *   21  u8   watchdog_trips
 *   22  u8   limiter_pct[2]     frames with gain reduction, last 1.5 s window
 *   24  f32  limiter_max_gr_db  deepest gain reduction since boot (positive dB)
 *   28  u32  limiter_frames     channel-frames with gain reduction since boot
 *   32  u32  heap_min_free      tile 1
 *   36  u32  heap_free
 *   40  u32  design_rejects
 *   44  u32  design_us_last
 */
#define SPEAKER_EQ_STATS_BYTES               48
