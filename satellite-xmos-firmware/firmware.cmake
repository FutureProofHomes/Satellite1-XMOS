#**********************
# Gather Sources
#**********************

file(GLOB APP_SOURCES   
    ${CMAKE_CURRENT_LIST_DIR}/src/*.c
    ${CMAKE_CURRENT_LIST_DIR}/src/control/*.c
    ${CMAKE_CURRENT_LIST_DIR}/src/gpio/*.c
    ${CMAKE_CURRENT_LIST_DIR}/src/dfu_int/*.c
)

set(APP_INCLUDES
    ${CMAKE_CURRENT_LIST_DIR}/src
    ${CMAKE_CURRENT_LIST_DIR}/src/control
    ${CMAKE_CURRENT_LIST_DIR}/src/dfu_int
)

include(${CMAKE_CURRENT_LIST_DIR}/bsp_config/bsp_config.cmake)
add_subdirectory(${CMAKE_CURRENT_LIST_DIR}/audio_pipelines)

set(VERSIONING_SCRIPT ${CMAKE_CURRENT_LIST_DIR}/versioning.py)
option(USE_DEV_TRACKING "Enable dev-build tracking" OFF)
option(USE_DEV_MODE "Enable dev-mode" OFF)

#**********************
# Flags
#**********************
set(APP_COMPILER_FLAGS
    -Os
    -g
    -report
    -mcmodel=large
    -Wno-xcore-fptrgroup
)

set(APP_COMPILE_DEFINITIONS
    PLATFORM_USES_TILE_0=1
    PLATFORM_USES_TILE_1=1
    XUD_CORE_CLOCK=600

    CFG_TUSB_DEBUG_PRINTF=rtos_printf
    CFG_TUSB_DEBUG=0
)

set(APP_LINK_OPTIONS
    -lquadspi
    -report
    -lotp3
)

set(APP_COMMON_LINK_LIBRARIES
    fph::device_control
    lib_src
    lib_sw_pll
)

if(USE_DEV_MODE)
list(APPEND APP_COMPILE_DEFINITIONS
    DEBUG_PRINT_ENABLE=1
    DEBUG_PRINT_ENABLE_DFU_SERVICER=1
    appconfWATCHDOG_ENABLED=0
    BUILTIN_TESTS_SPI_ECHO_SERVICER=1
)
file(GLOB_RECURSE BUILTIN_TESTS_SOURCES
    ${CMAKE_CURRENT_LIST_DIR}/src/builtin_tests/*.c
)
list(APPEND APP_SOURCES
    ${BUILTIN_TESTS_SOURCES}
)
list(APPEND APP_INCLUDES
    ${CMAKE_CURRENT_LIST_DIR}/src/builtin_tests/spi_echo_servicer
)
else()
list(APPEND APP_COMPILE_DEFINITIONS
    DEBUG_PRINT_ENABLE=0
    appconfWATCHDOG_ENABLED=1
    BUILTIN_TESTS_SPI_ECHO_SERVICER=0
)
endif()

#**********************
# Pipeline Options
# By default only these targets are created:
#  example_ffva_int_fixed_delay
#**********************
option(ENABLE_ALL_FFVA_PIPELINES  "Create all FFVA pipeline configurations"  OFF)

if(ENABLE_ALL_FFVA_PIPELINES)
    set(FFVA_PIPELINES_INT
        bypass
        fixed_delay
        adec
        adec_altarch
        empty
    )
else()
    set(FFVA_PIPELINES_INT
        fixed_delay
        empty
    )
endif()

#**********************
# XMOS Firmware Targets
#**********************
include(${CMAKE_CURRENT_LIST_DIR}/satellite1.cmake)
include(${CMAKE_CURRENT_LIST_DIR}/xk-voice-sq66.cmake)
#include(${CMAKE_CURRENT_LIST_DIR}/satellite1-usb.cmake)
#include(${CMAKE_CURRENT_LIST_DIR}/explorer_devboard.cmake)


