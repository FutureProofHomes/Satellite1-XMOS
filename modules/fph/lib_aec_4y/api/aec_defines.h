// Copyright 2022 XMOS LIMITED.
// This Software is subject to the terms of the XMOS Public Licence: Version 1.
#ifndef AEC_DEFINES_H
#define AEC_DEFINES_H

#ifdef __aec_conf_h_exists__
    #include "aec_conf.h"
#endif

#ifndef AEC_MAIN_FILTER_PHASES
#define AEC_MAIN_FILTER_PHASES (10)
#endif

#ifndef AEC_SHADOW_FILTER_PHASES
#define AEC_SHADOW_FILTER_PHASES (5)
#endif

/**
 * @page page_aec_defines_h aec_defines.h
 *
 * This header contains lib_aec public defines
 *
 * @ingroup aec_header_file
 */
/**
 * @defgroup aec_defines   AEC #define constants
 */

/** @brief Maximum number of microphone input channels supported in the library.
 * Microphone input to the AEC refers to the input from the device's microphones from which AEC removes the echo
 * created in the room by the device's loudspeakers.
 *
 * AEC functions follow the convention of using @math{y} and @math{Y} for referring to time domain and frequency domain
 * representation of microphone input.
 *
 * The `num_y_channels` passed into aec_init() call should be less than or equal to AEC_MAX_Y_CHANNELS.
 * This define is only used for defining data structures in the aec_state. The library code implementation uses only the
 * num_y_channels aec is initialised for in the aec_init() call.
 *
 * @ingroup aec_defines
 */
#ifndef AEC_MAX_Y_CHANNELS
#define AEC_MAX_Y_CHANNELS (2)
#endif

/** @brief Maximum number of reference input channels supported in the library.
 * Reference input to the AEC refers to a copy of the device's speaker output audio that is also sent as an input to the
 * AEC. It is used to model the echo characteristics between a mic-loudspeaker pair.
 *
 * AEC functions follow the convention of using @math{x} and @math{X} for referring to time domain and frequency domain
 * representation of reference input.
 *
 * The `num_x_channels` passed into aec_init() call should be less than or equal to AEC_MAX_X_CHANNELS.
 * This define is only used for defining data structures in the aec_state. The library code implementation uses only the
 * num_x_channels aec is initialised for in the aec_init() call.
 *
 * @ingroup aec_defines
 */
#ifndef AEC_MAX_X_CHANNELS
#define AEC_MAX_X_CHANNELS (2)
#endif

/** @brief AEC frame size
 * This is the number of samples of new data that the AEC works on every frame. 240 samples at 16kHz is 15msec. Every
 * frame, the echo canceller takes in 15msec of mic and reference data and generates 15msec of echo cancelled output.
 *
 * @ingroup aec_defines
 */
#define AEC_FRAME_ADVANCE (240)

/** Time domain samples block length used internally in AEC's block LMS algorithm
 *
 * @ingroup aec_defines
 */
#define AEC_PROC_FRAME_LENGTH (512)

/** Number of bins of spectrum data computed when doing a DFT of a AEC_PROC_FRAME_LENGTH length time domain vector. The
 * AEC_FD_FRAME_LENGTH spectrum values represent the bins from DC to Nyquist.
 *
 * @ingroup aec_defines
 */
#define AEC_FD_FRAME_LENGTH ((AEC_PROC_FRAME_LENGTH / 2) + 1)

/** @brief Descriptor capacity in each microphone's coefficient row.
 * Must hold num_x_channels * num_filter_phases for either filter. Pool payloads
 * are independently bounded by AEC_MAIN_FILTER_PHASES/AEC_SHADOW_FILTER_PHASES.
 * All state consumers must use the same descriptor capacity.
 *
 * @ingroup aec_defines
 */
#ifndef AEC_LIB_MAX_PHASES
#define AEC_LIB_MAX_PHASES (AEC_MAX_Y_CHANNELS * AEC_MAX_X_CHANNELS * AEC_MAIN_FILTER_PHASES)
#endif

/** Overlap data length
 *
 * @ingroup aec_defines
 */
#define AEC_UNUSED_TAPS_PER_PHASE (16)

/** Extra 2 samples you need to allocate in time domain so that the full spectrum (DC to nyquist) can be stored
 * after the in-place FFT. NOT USER MODIFIABLE.
 *
 * @ingroup aec_defines
 */
//
#define AEC_FFT_PADDING (2)

#define AEC_ZEROVAL_EXP (-1024) /// A very small exponent indicating 0 value.
#define AEC_ZEROVAL_HR (31) /// Headroom value used in BFP arrays when indicating 0 value by setting exponent to AEC_ZEROVAL_EXP

#define AEC_LIB_MAX_THREADS (3)

#endif
