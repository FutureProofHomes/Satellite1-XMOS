#**********************
# Gather Sources
#**********************

option(SATELLITE1_SPEAKER_EQ "Enable the resource-231 stereo speaker EQ pipeline" ON)
file(GLOB_RECURSE APP_SOURCES   ${CMAKE_CURRENT_LIST_DIR}/src/*.c)
if(NOT SATELLITE1_SPEAKER_EQ)
    list(FILTER APP_SOURCES EXCLUDE REGEX "/speaker_eq/")
endif()

set(APP_INCLUDES
    ${CMAKE_CURRENT_LIST_DIR}/src
    ${CMAKE_CURRENT_LIST_DIR}/src/control
    ${CMAKE_CURRENT_LIST_DIR}/src/dfu_int
)

include(${CMAKE_CURRENT_LIST_DIR}/bsp_config/bsp_config.cmake)
option(FIXED_DELAY_ONLY "Configure only the migrated fixed-delay pipeline" ON)
add_subdirectory(${CMAKE_CURRENT_LIST_DIR}/audio_pipelines)

set(VERSIONING_SCRIPT ${CMAKE_CURRENT_LIST_DIR}/versioning.py)
option(USE_DEV_TRACKING "Enable dev-build tracking" OFF)
option(ALLOW_DIRTY_VERSIONING "Allow versioning.py to run from a dirty workspace for controlled CI inputs or local throwaway builds" OFF)

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
    DEBUG_PRINT_ENABLE=0
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


#**********************
# Pipeline Options
# Only fixed_delay has migrated to the v0.9.0 APIs.
#**********************
option(ENABLE_ALL_FFVA_PIPELINES  "Create all FFVA pipeline configurations"  OFF)
if(ENABLE_ALL_FFVA_PIPELINES)
    message(FATAL_ERROR "Legacy FFVA pipelines have not migrated to fwk_voice v0.9.0")
endif()

if(FIXED_DELAY_ONLY)
    set(FFVA_PIPELINES_INT fixed_delay)
    set(FFVA_PIPELINES_UA "")
else()
    message(FATAL_ERROR "Only FIXED_DELAY_ONLY=ON is supported with fwk_voice v0.9.0")
endif()

#**********************
# XMOS Firmware Targets
#**********************
include(${CMAKE_CURRENT_LIST_DIR}/satellite1.cmake)
