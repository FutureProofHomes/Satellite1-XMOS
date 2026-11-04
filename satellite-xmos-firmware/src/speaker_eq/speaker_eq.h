#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include <platform.h>

#include "app_conf.h"
#include "platform/driver_instances.h"
#include "speaker_eq/speaker_eq_cmds.h"

#ifndef appconfSPEAKER_EQ_ENABLED
#define appconfSPEAKER_EQ_ENABLED 0
#endif

#if appconfSPEAKER_EQ_ENABLED && appconfDEVICE_CTRL_SPI && ON_TILE(SPEAKER_PIPELINE_TILE_NO)
#define SPEAKER_EQ_ACTIVE 1
#else
#define SPEAKER_EQ_ACTIVE 0
#endif

/* Servicers the EQ registers; the SPI host on tile 0 waits for every one. */
#define SPEAKER_EQ_NUM_SERVICERS ((appconfSPEAKER_EQ_ENABLED && appconfDEVICE_CTRL_SPI) ? 1 : 0)

/* Per-frame tag written by stage 0 so both channels use the same design. */
typedef struct {
    uint32_t bank_seq;
    uint8_t bank_index;
    uint8_t active;
} speaker_eq_frame_tag_t;

#if SPEAKER_EQ_ACTIVE

/* Starts the design task; call before the speaker pipeline stages run. */
void speaker_eq_init(void);

/* Stage-thread entry points. Channel 0 must run before channel 1 per frame. */
void speaker_eq_process_ch0(int32_t *samples, speaker_eq_frame_tag_t *tag);
void speaker_eq_process_ch1(int32_t *samples, const speaker_eq_frame_tag_t *tag);

/* Starts the resource 231 servicer task on this tile. */
void speaker_eq_servicer_start(void);

/* Resource 231 commands, called from the servicer. False rejects the payload. */
bool speaker_eq_cmd_write(uint8_t cmd_id, const uint8_t *payload, size_t len);
bool speaker_eq_cmd_read(uint8_t cmd_id, uint8_t *payload, size_t len);

#endif
