if((${CMAKE_SYSTEM_NAME} STREQUAL XCORE_XS3A) OR (${CMAKE_SYSTEM_NAME} STREQUAL XCORE_XS2A))
    ## Create library target
    add_library(lib_doa INTERFACE)
    target_sources(lib_doa
        INTERFACE
            src/gcc_phat.c
            src/doa_geometry.c
            src/doa_led.c
    )
    target_include_directories(lib_doa
        INTERFACE
            api
    )
    target_link_libraries(lib_doa
        INTERFACE
            lib_xcore_math
    )

    ## Create an alias
    add_library(fph::lib_doa ALIAS lib_doa)
endif()

if(BUILD_TESTING AND (NOT (CMAKE_SYSTEM_NAME STREQUAL XCORE_XS3A)) AND (NOT (CMAKE_SYSTEM_NAME STREQUAL XCORE_XS2A)))
    add_subdirectory(tests)
endif()
