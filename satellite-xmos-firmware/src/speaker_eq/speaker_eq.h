#pragma once

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
