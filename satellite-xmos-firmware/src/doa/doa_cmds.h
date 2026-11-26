#pragma once

typedef enum {
    DOA_SERVICER_CMD_READ_STATE = 0,
    DOA_SERVICER_CMD_READ_DIAGNOSTICS = 1,
    DOA_SERVICER_CMD_SET_CONTROL = 2,
    DOA_SERVICER_CMD_READ_CAPABILITIES = 3,
    DOA_SERVICER_CMD_SET_HOST_HINTS = 4,
    NUM_DOA_SERVICER_CMDS
} doa_servicer_cmd_id_t;

/*
 * READ_STATE payload:
 *   bytes 0-1: int16 sample delay, little-endian
 *   byte  2  : confidence, 0-255
 *   byte  3  : flags, bit 0 means estimate is valid
 *   bytes 4-7: frame energy, little-endian
 *   bytes 8-11: estimator frame counter, little-endian
 *   bytes 12-13: int16 vertical delay, little-endian
 *   byte  14: angle index for the ESP LED ring
 *   byte  15: reserved
 *   bytes 16-31: four uint32 mic energy values, little-endian
 */
#define DOA_SERVICER_STATE_NUM_VALUES (32)

/*
 * READ_DIAGNOSTICS payload:
 *   bytes 0-1: int16 horizontal steering delay Q8, little-endian
 *   bytes 2-3: int16 vertical steering delay Q8, little-endian
 *   bytes 4-7: adaptive room-noise floor, little-endian
 *   byte  8  : signal gate active
 *   byte  9  : requested control flags
 *   byte  10 : steering mode flags
 *   byte  11 : active microphone mask (E, W, N, S)
 *   bytes 12-19: four int16 current beam delays Q8, little-endian
 *   bytes 20-27: four uint16 microphone gains Q15, little-endian
 *   bytes 28-31: four microphone health flag bytes
 *   bytes 32-47: four uint32 smoothed microphone levels, little-endian
 *
 * SET_CONTROL accepts one byte containing DOA_ESTIMATOR_CONTROL_* flags.
 */
#define DOA_SERVICER_DIAGNOSTICS_NUM_VALUES (48)
#define DOA_SERVICER_CONTROL_NUM_VALUES (1)

/* Capability response: 'S', '1', 'D', protocol version 1, uint32 flags LE.
 * Existing READ_STATE/READ_DIAGNOSTICS layouts and commands are unchanged.
 * Hosts must probe this before SET_HOST_HINTS (write command 4, one byte).
 * It updates only bits 0/3, preserving manual force-omni/lock controls.
 * Older images may
 * reject the command; calibrated_beam advertises no speech-frontend hints. */
#define DOA_SERVICER_CAPABILITIES_NUM_VALUES (8)
#define DOA_SERVICER_CAPABILITY_HOST_HINTS (1u << 0)
