file(GLOB_RECURSE LIB_IC_SOURCES
    "${CMAKE_CURRENT_LIST_DIR}/../../voice/modules/lib_ic/src/*.c")

add_library(fph_lib_ic_4y STATIC)
target_sources(fph_lib_ic_4y PRIVATE ${LIB_IC_SOURCES})
target_include_directories(fph_lib_ic_4y
    PUBLIC "${CMAKE_CURRENT_LIST_DIR}/../../voice/modules/lib_ic/api")
target_compile_options(fph_lib_ic_4y PRIVATE -Os -g)
target_link_libraries(fph_lib_ic_4y
    PUBLIC
        lib_xcore_math
        fph::aec_4y
        fwk_voice::vnr::features
        fwk_voice::vnr::inference)

add_library(fph::ic_4y ALIAS fph_lib_ic_4y)
