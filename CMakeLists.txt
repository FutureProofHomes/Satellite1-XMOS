cmake_minimum_required(VERSION 3.21)

## Disable in-source build.
if("${CMAKE_SOURCE_DIR}" STREQUAL "${CMAKE_BINARY_DIR}")
    message(FATAL_ERROR "In-source build is not allowed! Please specify a build folder.\n\tex:cmake -B build")
endif()

## Project declaration
project(satellite-xmos-firmware)

## Enable languages for project
enable_language(CXX C ASM)

## Setup a root path
set(XMOS_FIRMWARE_ROOT_PATH ${PROJECT_SOURCE_DIR} CACHE STRING "Root folder of xmos_firmware in this cmake project tree")

## Import xmos macros
include(xmos_macros.cmake)

## Add frameworks
option(SATELLITE1_FIXED_DELAY_AEC_4Y2X_MAIN_ONLY
    "Use four microphones and two independent references without a shadow filter" ON)
if(SATELLITE1_FIXED_DELAY_AEC_4Y2X_MAIN_ONLY)
    set(_aec_4y1x_default OFF)
else()
    set(_aec_4y1x_default ON)
endif()
option(SATELLITE1_FIXED_DELAY_AEC_4Y1X
    "Use four microphones and a mixed mono reference with a shadow filter" ${_aec_4y1x_default})
if(SATELLITE1_FIXED_DELAY_AEC_4Y1X AND SATELLITE1_FIXED_DELAY_AEC_4Y2X_MAIN_ONLY)
    message(FATAL_ERROR "Select only one fixed-delay AEC profile")
endif()
if(NOT SATELLITE1_FIXED_DELAY_AEC_4Y1X AND NOT SATELLITE1_FIXED_DELAY_AEC_4Y2X_MAIN_ONLY)
    message(FATAL_ERROR "Select a supported fixed-delay AEC profile")
endif()
add_subdirectory(modules)

## Add top level project targets
if(PROJECT_IS_TOP_LEVEL AND ${CMAKE_SYSTEM_NAME} STREQUAL XCORE_XS3A)
    include(satellite-xmos-firmware/firmware.cmake)
endif()
