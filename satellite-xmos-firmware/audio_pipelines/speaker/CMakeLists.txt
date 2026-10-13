##******************************************
## Create empty audio pipeline
##******************************************

add_library(empty_2ch_pt INTERFACE)
target_sources(empty_2ch_pt
    INTERFACE
        ${CMAKE_CURRENT_LIST_DIR}/passthrough/speaker_pipeline.c
)
target_include_directories(empty_2ch_pt
    INTERFACE
        ${CMAKE_CURRENT_LIST_DIR}
        ${CMAKE_CURRENT_LIST_DIR}/passthrough
)
target_link_libraries(empty_2ch_pt
    INTERFACE
        core::general
        rtos::freertos
        rtos::sw_services::generic_pipeline
)


##******************************************
## Create speaker EQ audio pipeline
##******************************************

add_library(eq_2ch INTERFACE)
target_sources(eq_2ch
    INTERFACE
        ${CMAKE_CURRENT_LIST_DIR}/eq/speaker_pipeline.c
)
target_include_directories(eq_2ch
    INTERFACE
        ${CMAKE_CURRENT_LIST_DIR}
)
target_compile_definitions(eq_2ch
    INTERFACE
        appconfSPEAKER_EQ_ENABLED=1
)
target_link_libraries(eq_2ch
    INTERFACE
        core::general
        rtos::freertos
        rtos::sw_services::generic_pipeline
        fph::audio_dsp
)


##*********************************************
## Create aliases for sln_voice example designs
##*********************************************

add_library(sln_voice::app::ffva::sp::passthrough ALIAS empty_2ch_pt)
add_library(fph::ffva::sp::eq ALIAS eq_2ch)
