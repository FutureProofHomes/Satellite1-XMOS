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


##*********************************************
## Create aliases for sln_voice example designs
##*********************************************

add_library(sln_voice::app::ffva::sp::passthrough ALIAS empty_2ch_pt)

##******************************************
## Create serial mono speaker EQ pipeline
##******************************************

add_library(serial_eq_2ch INTERFACE)
target_sources(serial_eq_2ch
    INTERFACE
        ${CMAKE_CURRENT_LIST_DIR}/serial_eq/speaker_pipeline.c
        ${CMAKE_CURRENT_LIST_DIR}/serial_eq/speaker_eq_preset.c
)
target_include_directories(serial_eq_2ch
    INTERFACE
        ${CMAKE_CURRENT_LIST_DIR}
        ${CMAKE_CURRENT_LIST_DIR}/serial_eq
)
target_link_libraries(serial_eq_2ch
    INTERFACE
        core::general
        fph::speaker_eq
        rtos::freertos
        rtos::sw_services::generic_pipeline
)

add_library(sln_voice::app::ffva::sp::serial_eq ALIAS serial_eq_2ch)
