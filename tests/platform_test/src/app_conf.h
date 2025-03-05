#ifndef APP_CONF_H_
#define APP_CONF_H_

/* Boards */
#define BOARD_ID_SATELLITE1 0
#define BOARD_ID_EXPLORER   1

#ifndef BOARD_ID
#define BOARD_ID BOARD_ID_SATELLITE1
#endif

/* Tile specifiers */
#define FLASH_TILE_NO    0


/* Tile 0 - Cores */
#define appconfXUD_IO_CORE                      1
#define appconfUSB_INTERRUPT_CORE               4
#define appconfUSB_SOF_INTERRUPT_CORE           3 /* Must be kept off I/O cores. Best kept off cores with other ISRs. */

/* Tile 0 - Task Priorities */
#define appconfSTARTUP_TASK_PRIORITY            (configMAX_PRIORITIES-1)
#define appconfQSPI_FLASH_TASK_PRIORITY		    (configMAX_PRIORITIES-1)
#define appconfUSB_MGR_TASK_PRIORITY            (configMAX_PRIORITIES/2 + 1)
#define appconfUSB_AUDIO_TASK_PRIORITY          (configMAX_PRIORITIES/2 + 1)
#define appconfUSB_CDC_PRIORITY                 (configMAX_PRIORITIES/2)


/* Tile 1 - Task Priorities */
#define appconfAUDIO_PIPELINE_TASK_PRIORITY     (configMAX_PRIORITIES/2)


/* TILE 0 - Clock Blocks */
#define FLASH_CLKBLK  XS1_CLKBLK_1



/* Intertile Ports */
#define appconfUSB_AUDIO_PORT          0
#define appconfAUDIOPIPELINE_PORT      7
#define appconfUSB_CDC_PORT           16


/* Audio Pipelines */
/**
 * A positive delay will delay mics
 * A negative delay will delay ref
 */
#define appconfINPUT_SAMPLES_MIC_DELAY_MS       -50



/* Test case timeouts */
#define SOF_TIMEOUT_MS                          1000

#define USB_MOUNT_TIMEOUT_MS                    5000

#define CDC_FIRST_BYTE_TIMEOUT_MS               10000
#define CDC_NEXT_BYTE_TIMEOUT_MS                5000

#define DFU_FIRST_XFER_TIMEOUT_MS               10000
#define DFU_NEXT_XFER_TIMEOUT_MS                5000


#define appconfI2S_AUDIO_SAMPLE_RATE            16000

#define appconfAUDIO_PIPELINE_SAMPLE_RATE       16000
#define appconfAUDIO_PIPELINE_CHANNELS          2
#define appconfAUDIO_SPK_PL_SR_FACTOR           1

#define appconfAUDIO_PIPELINE_FRAME_ADVANCE     MIC_ARRAY_CONFIG_SAMPLES_PER_FRAME
#define appconfAUDIO_SPK_PIPELINE_FRAME_ADVANCE appconfAUDIO_SPK_PL_SR_FACTOR * appconfAUDIO_PIPELINE_FRAME_ADVANCE

        
#define appconfUSB_AUDIO_SAMPLE_RATE   appconfI2S_AUDIO_SAMPLE_RATE
#define appconfUSB_AUDIO_RELEASE   0
#define appconfUSB_AUDIO_TESTING   1



#endif /* APP_CONF_H_ */
