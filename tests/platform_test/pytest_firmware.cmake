#**********************
# Individual tests
#**********************
set(USB_TEST  1)

#**********************
# Gather Sources
#**********************
#file(GLOB_RECURSE APP_SOURCES ${CMAKE_CURRENT_LIST_DIR}/src/*.c)
file(GLOB APP_SOURCES 
    ${CMAKE_CURRENT_LIST_DIR}/src/*.c
    ${CMAKE_CURRENT_LIST_DIR}/src/dfu/*.c
    ${CMAKE_CURRENT_LIST_DIR}/src/individual_tests/*.c
    ${CMAKE_CURRENT_LIST_DIR}/src/usb/*.c
    #${XMOS_FIRMWARE_ROOT_PATH}/satellite-xmos-firmware/src/usb/*.c
)

set(APP_INCLUDES 
    ${CMAKE_CURRENT_LIST_DIR}/src
    ${CMAKE_CURRENT_LIST_DIR}/src/usb
    #${XMOS_FIRMWARE_ROOT_PATH}/satellite-xmos-firmware/src/usb/
    ${CMAKE_CURRENT_LIST_DIR}/src/dfu
)

include(${XMOS_FIRMWARE_ROOT_PATH}/satellite-xmos-firmware/bsp_config/bsp_config.cmake)
add_subdirectory(${XMOS_FIRMWARE_ROOT_PATH}/satellite-xmos-firmware/audio_pipelines)

# Declare the variable with a default value (optional)
if(NOT DEFINED appconfINPUT_SAMPLES_MIC_DELAY_MS)
    set(appconfINPUT_SAMPLES_MIC_DELAY_MS 0)
endif()


set(BOARD SATELLITE1)
#set(BOARD EXPLORER)

#**********************
# Flags
#**********************
set(APP_COMPILER_FLAGS
    #-Os
    -O0
    -g
    -report
    -lquadspi
    -mcmodel=large
    -Wno-xcore-fptrgroup
)
set(APP_COMPILE_DEFINITIONS
    PLATFORM_SUPPORTS_TILE_0=1
    PLATFORM_SUPPORTS_TILE_1=1
    PLATFORM_SUPPORTS_TILE_2=0
    PLATFORM_SUPPORTS_TILE_3=0
    PLATFORM_USES_TILE_0=1
    PLATFORM_USES_TILE_1=1
    
    USB_TILE_NO=0
    USB_TILE=tile[USB_TILE_NO]
    
    XE_BASE_TILE=0
    XUD_CORE_CLOCK=600
    RUN_USB_TESTS=${USB_TEST}

    TEST_FRAMEWORK=1
    appconfUSB_ENABLED=1
    appconfUSB_DFU_ENABLED=1
    appconfUSB_CDC_ENABLED=1
    appconfUSB_AUDIO_ENABLED=1
    appconfMICS_ENABLED=1
    appconfI2S_ENABLED=1
    appconfUSE_SPK_PIPELINE_AS_REF=1
    appconfINPUT_SAMPLES_MIC_DELAY_MS=${appconfINPUT_SAMPLES_MIC_DELAY_MS}
)

set(APP_LINK_OPTIONS
    -lquadspi
    -report
)

set(APP_COMMON_LINK_LIBRARIES
    rtos::freertos_usb
    fph::device_control
    lib_src
    lib_sw_pll
)

#set(CMAKE_C_FLAGS "-O0" CACHE STRING "Optimization flag" FORCE)
#set(CMAKE_CXX_FLAGS "-O0" CACHE STRING "Optimization flag" FORCE)


if(BOARD STREQUAL SATELLITE1)
list(APPEND APP_COMPILE_DEFINITIONS
    BOARD_ID=BOARD_ID_SATELLITE1
    DEBUG_PRINT_ENABLE=0
)
list(APPEND APP_COMMON_LINK_LIBRARIES
    fph::ffva::satellite1_usb
    sln_voice::app::ffva::sp::passthrough
    fph::ffva::ap::fixed_delay
    #fph::ffva::ap::adec
)
endif()


if(BOARD STREQUAL EXPLORER)
list(APPEND APP_COMPILE_DEFINITIONS
    BOARD_ID=BOARD_ID_EXPLORER
    DEBUG_PRINT_ENABLE=1
)
list(APPEND APP_COMMON_LINK_LIBRARIES
    sln_voice::app::ffva::xcore_ai_explorer
    sln_voice::app::ffva::sp::passthrough
    fph::ffva::ap::fixed_delay
)
list(APPEND APP_COMPILER_FLAGS
    -fxscope
    ${CMAKE_CURRENT_LIST_DIR}/src/config.xscope
)
list(APPEND APP_LINK_OPTIONS
    ${CMAKE_CURRENT_LIST_DIR}/src/config.xscope
)
endif()


query_tools_version()

#**********************
# Tile Targets
#**********************
set(TARGET_NAME ${TEST_TARGET_NAME}_tile0)
add_executable(${TARGET_NAME} EXCLUDE_FROM_ALL)
target_sources(${TARGET_NAME} PUBLIC ${APP_SOURCES})
target_include_directories(${TARGET_NAME} PUBLIC ${APP_INCLUDES})
target_compile_definitions(${TARGET_NAME} PUBLIC ${APP_COMPILE_DEFINITIONS} THIS_XCORE_TILE=0)
target_compile_options(${TARGET_NAME} PRIVATE ${APP_COMPILER_FLAGS})
target_link_libraries(${TARGET_NAME} 
    PUBLIC 
        ${APP_COMMON_LINK_LIBRARIES}
)
target_link_options(${TARGET_NAME} PRIVATE ${APP_LINK_OPTIONS})
unset(TARGET_NAME)

set(TARGET_NAME ${TEST_TARGET_NAME}_tile1)
add_executable(${TARGET_NAME} EXCLUDE_FROM_ALL)
target_sources(${TARGET_NAME} PUBLIC ${APP_SOURCES})
target_include_directories(${TARGET_NAME} PUBLIC ${APP_INCLUDES})
target_compile_definitions(${TARGET_NAME} PUBLIC ${APP_COMPILE_DEFINITIONS} THIS_XCORE_TILE=1)
target_compile_options(${TARGET_NAME} PRIVATE ${APP_COMPILER_FLAGS})
target_link_libraries(${TARGET_NAME} 
    PUBLIC 
    ${APP_COMMON_LINK_LIBRARIES}
)
target_link_options(${TARGET_NAME} PRIVATE ${APP_LINK_OPTIONS})
unset(TARGET_NAME)

#**********************
# Merge binaries
#**********************
merge_binaries(${TEST_TARGET_NAME} ${TEST_TARGET_NAME}_tile0 ${TEST_TARGET_NAME}_tile1 1)

create_upgrade_img_target(${TEST_TARGET_NAME} ${XTC_VERSION_MAJOR} ${XTC_VERSION_MINOR})

create_flash_image_target(
        #[[ Target ]]                  ${TEST_TARGET_NAME}
        #[[ Boot Partition Size ]]     0x100000
)