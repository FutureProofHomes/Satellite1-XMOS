"""Host-only contract checks for the minimal SQ66 firmware target."""

from pathlib import Path
import re

from tests.conftest import PROJ_ROOT


SQ66_FIRMWARE = PROJ_ROOT / "satellite-xmos-firmware"
SQ66_CMAKE = SQ66_FIRMWARE / "xk-voice-sq66.cmake"
SQ66_BSP_CMAKE = SQ66_FIRMWARE / "bsp_config/XK-VOICE-SQ66/XK-VOICE-SQ66.cmake"
SQ66_PLATFORM_INIT = SQ66_FIRMWARE / "bsp_config/XK-VOICE-SQ66/platform/platform_init.c"
MAIN_C = SQ66_FIRMWARE / "src/main.c"


def _contents(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_sq66_cmake_registers_the_fixed_delay_firmware_target() -> None:
    cmake = _contents(SQ66_CMAKE)

    assert "appconfLED_RING=0" in cmake
    assert "set(TARGET_NAME tile0_sq66_firmware_${FFVA_AP})" in cmake
    assert "set(TARGET_NAME tile1_sq66_firmware_${FFVA_AP})" in cmake
    assert "merge_binaries(sq66_firmware_${FFVA_AP}" in cmake
    assert "create_run_target(sq66_firmware_${FFVA_AP})" in cmake


def test_sq66_bsp_uses_the_two_microphone_mapping() -> None:
    bsp_cmake = _contents(SQ66_BSP_CMAKE)

    assert "MIC_ARRAY_CONFIG_MIC_COUNT=2" in bsp_cmake
    assert re.search(r'set\(MIC_MAPPING\s+"4, 5"\)', bsp_cmake)
    assert "MIC_ARRAY_CONFIG_INPUT_MAPPING={${MIC_MAPPING}}" in bsp_cmake


def test_sq66_device_control_registers_gpio_and_dfu_only() -> None:
    platform_init = _contents(SQ66_PLATFORM_INIT)
    main_c = _contents(MAIN_C)

    # SQ66 has no LED ring, so its host accepts exactly GPIO and DFU servicers.
    assert re.search(
        r"device_control_init\(device_control_spi_ctx,\s*"
        r"DEVICE_CONTROL_HOST_MODE,\s*2,\s*"
        r"// GPIO \+ DFU servicers; LED ring is disabled on SQ66",
        platform_init,
    )
    assert "gpio_servicer_start(device_control_gpio_ctx, device_control_ctx, 1 );" in main_c
    assert "dfu_servicer_init(&dfu_servicer_ctx);" in main_c
    assert "#if appconfLED_RING && ON_TILE(WS2812_TILE_NO)" in main_c
