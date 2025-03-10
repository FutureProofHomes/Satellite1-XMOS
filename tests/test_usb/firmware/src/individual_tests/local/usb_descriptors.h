// Copyright 2021-2023 XMOS LIMITED.
// This Software is subject to the terms of the XMOS Public Licence: Version 1.

#ifndef USB_DESCRIPTORS_H_
#define USB_DESCRIPTORS_H_

#include "tusb_config.h"

// Number of Alternate Interface (each for 1 flash partition)
#define ALT_COUNT   3

enum {
    ITF_NUM_CDC_0,
    ITF_NUM_CDC_0_DATA,
    ITF_NUM_CDC_1,
    ITF_NUM_CDC_1_DATA,
    ITF_NUM_DFU_MODE,
    ITF_NUM_TOTAL
};

#endif /* USB_DESCRIPTORS_H_ */
