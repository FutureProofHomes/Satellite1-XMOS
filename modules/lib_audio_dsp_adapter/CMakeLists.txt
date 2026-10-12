set(LIB_AUDIO_DSP_ROOT ${CMAKE_CURRENT_LIST_DIR}/lib_audio_dsp/lib_audio_dsp)

file(GLOB_RECURSE LIB_AUDIO_DSP_C_SOURCES CONFIGURE_DEPENDS
    ${LIB_AUDIO_DSP_ROOT}/src/dsp/*.c
    ${LIB_AUDIO_DSP_ROOT}/src/control/*.c
)
file(GLOB_RECURSE LIB_AUDIO_DSP_ASM_SOURCES CONFIGURE_DEPENDS
    ${LIB_AUDIO_DSP_ROOT}/src/dsp/*.S
    ${LIB_AUDIO_DSP_ROOT}/src/control/*.S
)

set_source_files_properties(${LIB_AUDIO_DSP_ASM_SOURCES} PROPERTIES LANGUAGE ASM)

add_library(lib_audio_dsp STATIC
    ${LIB_AUDIO_DSP_C_SOURCES}
    ${LIB_AUDIO_DSP_ASM_SOURCES}
)
add_library(audio_dsp::lib_audio_dsp ALIAS lib_audio_dsp)

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
        -Wall
        -Werror
        -g
)
