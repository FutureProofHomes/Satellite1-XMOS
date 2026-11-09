
if(${CMAKE_SYSTEM_NAME} STREQUAL XCORE_XS3A)
    set(LIB_AUDIO_DSP_ROOT ${CMAKE_CURRENT_LIST_DIR}/lib_audio_dsp/lib_audio_dsp)

    ## Only the C/asm DSP and control layers; the stages layer needs codegen
    file(GLOB LIB_C_SOURCES
        ${LIB_AUDIO_DSP_ROOT}/src/dsp/*.c
        ${LIB_AUDIO_DSP_ROOT}/src/control/*.c
    )
    file(GLOB LIB_ASM_SOURCES
        ${LIB_AUDIO_DSP_ROOT}/src/dsp/*.S
        ${LIB_AUDIO_DSP_ROOT}/src/control/*.S
    )

    ## cmake doesn't recognize .S files as assembly by default
    set_source_files_properties(${LIB_ASM_SOURCES} PROPERTIES LANGUAGE ASM)

    add_library(lib_audio_dsp STATIC)
    target_sources(lib_audio_dsp
        PRIVATE
            ${LIB_C_SOURCES}
            ${LIB_ASM_SOURCES}
    )
    target_include_directories(lib_audio_dsp
        PUBLIC
            ${LIB_AUDIO_DSP_ROOT}/api
    )
    target_link_libraries(lib_audio_dsp
        PUBLIC
            lib_xcore_math
    )
    target_compile_options(lib_audio_dsp
        PRIVATE
            -O3
    )

    add_library(fph::audio_dsp ALIAS lib_audio_dsp)
endif()
