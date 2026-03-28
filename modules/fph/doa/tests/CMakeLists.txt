cmake_minimum_required(VERSION 3.21)

project(doa_unit_tests C)

enable_testing()

add_executable(doa_from_lags_test
    src/test_doa_from_lags.c
    ../src/doa_geometry.c
)

target_include_directories(doa_from_lags_test
    PRIVATE
        ../api
        ../../../../modules/core/modules/xcore_math/lib_xcore_math/lib_xcore_math/api
)

if(PLATFORM_ID STREQUAL Linux OR PLATFORM_ID STREQUAL Darwin OR CMAKE_SYSTEM_NAME MATCHES "Linux|Darwin")
    target_link_libraries(doa_from_lags_test PRIVATE m)
endif()

add_test(NAME doa_from_lags_test COMMAND doa_from_lags_test)
