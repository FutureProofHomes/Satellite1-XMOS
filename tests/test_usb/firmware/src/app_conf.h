// Copyright 2021-2023 XMOS LIMITED.
// This Software is subject to the terms of the XMOS Public Licence: Version 1.

#ifndef APP_CONF_H_
#define APP_CONF_H_

#define appconfXUD_IO_CORE                      1
#define appconfUSB_INTERRUPT_CORE               2

/* Test case timeouts */
#define SOF_TIMEOUT_MS                          1000

#define USB_MOUNT_TIMEOUT_MS                    5000

#define CDC_FIRST_BYTE_TIMEOUT_MS               10000
#define CDC_NEXT_BYTE_TIMEOUT_MS                5000

#define DFU_FIRST_XFER_TIMEOUT_MS               10000
#define DFU_NEXT_XFER_TIMEOUT_MS                5000

/* Task Priorities */
#define appconfSTARTUP_TASK_PRIORITY            (configMAX_PRIORITIES-1)

#endif /* APP_CONF_H_ */
