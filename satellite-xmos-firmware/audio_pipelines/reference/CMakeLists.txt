##******************************************
## Create fixed_delay 4Y1X AEC + residual average + NS + AGC
##   4 mic input channels, stereo reference mixed to mono
##******************************************

add_library(fixed_delay_4mic_1ref INTERFACE)
target_sources(fixed_delay_4mic_1ref
    INTERFACE
        ${CMAKE_CURRENT_LIST_DIR}/fixed_delay/audio_pipeline_t0.c
        ${CMAKE_CURRENT_LIST_DIR}/fixed_delay/audio_pipeline_t1.c
)
target_include_directories(fixed_delay_4mic_1ref
    INTERFACE
        ${CMAKE_CURRENT_LIST_DIR}
        ${CMAKE_CURRENT_LIST_DIR}/fixed_delay
)
target_link_libraries(fixed_delay_4mic_1ref
    INTERFACE
        voice_compat
        core::general
        rtos::freertos
        rtos::sw_services::generic_pipeline
        fph::aec_4y
        fwk_voice::agc
        fph::ic_4y
        fwk_voice::ns
        fwk_voice::vnr
)
target_compile_definitions(fixed_delay_4mic_1ref INTERFACE
    appconfMIC_PIPELINE_PROC_CHANNELS=4
    appconfAUDIO_PIPELINE_SKIP_IC_AND_VNR=1)
set_property(TARGET fixed_delay_4mic_1ref PROPERTY INTERFACE_FPH_MIC_CHANNELS 4)
set_property(TARGET fixed_delay_4mic_1ref APPEND PROPERTY
    COMPATIBLE_INTERFACE_STRING FPH_MIC_CHANNELS)

##******************************************
## Optional calibrated pre-AEC beam + stereo-reference 2Y2X AEC + IC + NS + AGC
## The upstream fixed_delay_4mic_1ref target and alias remain unchanged.
##******************************************

add_library(calibrated_beam_2mic_2ref INTERFACE)
target_sources(calibrated_beam_2mic_2ref INTERFACE
    ${CMAKE_CURRENT_LIST_DIR}/calibrated_beam/audio_pipeline_t0.c
    ${CMAKE_CURRENT_LIST_DIR}/calibrated_beam/audio_pipeline_t1.c
    ${CMAKE_CURRENT_LIST_DIR}/calibrated_beam/aec/aec_process_frame_1thread.c)
target_include_directories(calibrated_beam_2mic_2ref INTERFACE
    ${CMAKE_CURRENT_LIST_DIR}
    ${CMAKE_CURRENT_LIST_DIR}/calibrated_beam
    ${CMAKE_CURRENT_LIST_DIR}/calibrated_beam/aec)
target_link_libraries(calibrated_beam_2mic_2ref INTERFACE
    voice_compat core::general rtos::freertos
    rtos::sw_services::generic_pipeline
    fwk_voice::aec fwk_voice::ic fwk_voice::ns fwk_voice::vnr fwk_voice::agc)
target_compile_definitions(calibrated_beam_2mic_2ref INTERFACE
    appconfSAT1_CALIBRATED_BEAM=1
    appconfAUDIO_PIPELINE_CHANNELS=2
    appconfMIC_PIPELINE_INPUT_CHANNELS=2
    appconfMIC_PIPELINE_PROC_CHANNELS=2
    # Retain the IC/VNR stage used by the hardware-tested dev.4 candidate.
    appconfAUDIO_PIPELINE_SKIP_IC_AND_VNR=0)
set_property(TARGET calibrated_beam_2mic_2ref PROPERTY INTERFACE_FPH_MIC_CHANNELS 4)
set_property(TARGET calibrated_beam_2mic_2ref APPEND PROPERTY
    COMPATIBLE_INTERFACE_STRING FPH_MIC_CHANNELS)
add_library(fph::ffva::ap::calibrated_beam ALIAS calibrated_beam_2mic_2ref)

## Optional four-mic AEC -> speech tracking/beam -> protected IC -> NS/AGC.
## Explicit target only: the upstream fixed_delay alias remains unchanged.
add_library(speech_tracking_4mic_1ref INTERFACE)
target_sources(speech_tracking_4mic_1ref INTERFACE
    ${CMAKE_CURRENT_LIST_DIR}/fixed_delay4/audio_pipeline_t0.c
    ${CMAKE_CURRENT_LIST_DIR}/fixed_delay4/audio_pipeline_t1.c)
target_include_directories(speech_tracking_4mic_1ref INTERFACE
    ${CMAKE_CURRENT_LIST_DIR}
    ${CMAKE_CURRENT_LIST_DIR}/fixed_delay4)
target_link_libraries(speech_tracking_4mic_1ref INTERFACE
    voice_compat core::general rtos::freertos
    rtos::sw_services::generic_pipeline fph::aec_4y fph::ic_4y
    fwk_voice::agc fwk_voice::ns fwk_voice::vnr)
target_compile_definitions(speech_tracking_4mic_1ref INTERFACE
    appconfSAT1_SPEECH_FRONTEND=1 appconfSAT1_POST_AEC_BEAM=1
    appconfMIC_PIPELINE_PROC_CHANNELS=4 appconfAUDIO_PIPELINE_SKIP_IC_AND_VNR=0)
set_property(TARGET speech_tracking_4mic_1ref PROPERTY INTERFACE_FPH_MIC_CHANNELS 4)
set_property(TARGET speech_tracking_4mic_1ref APPEND PROPERTY
    COMPATIBLE_INTERFACE_STRING FPH_MIC_CHANNELS)
add_library(fph::ffva::ap::speech_tracking ALIAS speech_tracking_4mic_1ref)

##******************************************
## Create ADEC "prevarch" AEC+IC+NS+AGC 
##   2 mic input channels
#    2 reference input channels
##******************************************

add_library(adec_aec_ic_ns_agc_2mic_2ref INTERFACE)
target_sources(adec_aec_ic_ns_agc_2mic_2ref
    INTERFACE
        ${CMAKE_CURRENT_LIST_DIR}/adec/audio_pipeline_t0.c
        ${CMAKE_CURRENT_LIST_DIR}/adec/audio_pipeline_t1.c
        ${CMAKE_CURRENT_LIST_DIR}/adec/stage1/delay_buffer.c
        ${CMAKE_CURRENT_LIST_DIR}/adec/stage1/stage_1.c
        ${CMAKE_CURRENT_LIST_DIR}/adec/aec/aec_process_frame_1thread.c
)
target_include_directories(adec_aec_ic_ns_agc_2mic_2ref
    INTERFACE
        ${CMAKE_CURRENT_LIST_DIR}
        ${CMAKE_CURRENT_LIST_DIR}/adec
        ${CMAKE_CURRENT_LIST_DIR}/adec/aec
        ${CMAKE_CURRENT_LIST_DIR}/adec/stage1
)
target_link_libraries(adec_aec_ic_ns_agc_2mic_2ref
    INTERFACE
        voice_compat
        core::general
        rtos::freertos
        rtos::sw_services::generic_pipeline
        fwk_voice::adec
        fwk_voice::aec
        fwk_voice::agc
        fwk_voice::ic
        fwk_voice::ns
        fwk_voice::vnr
)

##******************************************
## Create ADEC altarch AEC+IC+NS+AGC 
##   2 mic input channels
#    2 reference input channels
##******************************************

add_library(adec_altarch_aec_ic_ns_agc_2mic_2ref INTERFACE)
target_sources(adec_altarch_aec_ic_ns_agc_2mic_2ref
    INTERFACE
        ${CMAKE_CURRENT_LIST_DIR}/adec_alt_arch/audio_pipeline_t0.c
        ${CMAKE_CURRENT_LIST_DIR}/adec_alt_arch/audio_pipeline_t1.c
        ${CMAKE_CURRENT_LIST_DIR}/adec_alt_arch/stage1/delay_buffer.c
        ${CMAKE_CURRENT_LIST_DIR}/adec_alt_arch/stage1/stage_1.c
        ${CMAKE_CURRENT_LIST_DIR}/adec_alt_arch/aec/aec_process_frame_1thread.c
)
target_include_directories(adec_altarch_aec_ic_ns_agc_2mic_2ref
    INTERFACE
        ${CMAKE_CURRENT_LIST_DIR}
        ${CMAKE_CURRENT_LIST_DIR}/adec_alt_arch
        ${CMAKE_CURRENT_LIST_DIR}/adec_alt_arch/aec
        ${CMAKE_CURRENT_LIST_DIR}/adec_alt_arch/stage1
)
target_link_libraries(adec_altarch_aec_ic_ns_agc_2mic_2ref
    INTERFACE
        voice_compat
        core::general
        rtos::freertos
        rtos::sw_services::generic_pipeline
        fwk_voice::adec
        fwk_voice::aec
        fwk_voice::agc
        fwk_voice::ic
        fwk_voice::ns
        fwk_voice::vnr
)

##******************************************
## Create empty audio pipeline
##******************************************

add_library(empty_2mic_2ref INTERFACE)
target_sources(empty_2mic_2ref
    INTERFACE
        ${CMAKE_CURRENT_LIST_DIR}/empty/audio_pipeline_t0.c
        ${CMAKE_CURRENT_LIST_DIR}/empty/audio_pipeline_t1.c
)
target_include_directories(empty_2mic_2ref
    INTERFACE
        ${CMAKE_CURRENT_LIST_DIR}
        ${CMAKE_CURRENT_LIST_DIR}/empty
)
target_link_libraries(empty_2mic_2ref
    INTERFACE
        core::general
        rtos::freertos
        rtos::sw_services::generic_pipeline
)

##*********************************************
## Create aliases for sln_voice example designs
##*********************************************

add_library(fph::ffva::ap::adec_altarch ALIAS adec_altarch_aec_ic_ns_agc_2mic_2ref)
add_library(fph::ffva::ap::fixed_delay ALIAS fixed_delay_4mic_1ref)
add_library(fph::ffva::ap::adec ALIAS adec_aec_ic_ns_agc_2mic_2ref)
add_library(fph::ffva::ap::empty ALIAS empty_2mic_2ref)
