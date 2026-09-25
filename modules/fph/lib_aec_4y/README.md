# FPH 4Y AEC Variant

This module provides the FPH-owned `4Y x 1X` AEC ABI without modifying the
upstream `modules/voice/modules/lib_aec` module.

The public API headers and `aec_impl.c` are derived from XMOS `lib_aec` under
the XMOS Public Licence. The unchanged low-level implementation sources are
compiled from the upstream module. Consumers must link only `fph::aec_4y` and
use this module's public headers; it must not be linked with upstream
`fwk_voice_module_lib_aec` in the same executable because both export the AEC
API symbols.
