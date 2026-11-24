"""Execute production channel arithmetic with host-side driver boundaries stubbed."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
FIRMWARE = ROOT / "satellite-xmos-firmware"
FIXED = FIRMWARE / "audio_pipelines/reference/fixed_delay"


def function(path, name):
    source = path.read_text()
    start = re.search(r"^(?:static )?(?:void \*?|int |int32_t )" + name + r"\(", source, re.M).start()
    opening = source.index("{", start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


@pytest.mark.parametrize("channels", [2, 4])
@pytest.mark.parametrize("sample_rate", [16000, 48000])
@pytest.mark.parametrize("backend", ["host", "xcore"])
def test_production_channel_arithmetic(tmp_path, channels, sample_rate, backend):
    compiler = shutil.which("xcc" if backend == "xcore" else "cc")
    if not compiler:
        pytest.skip(f"The {backend} compiler is required")
    if backend == "xcore" and not shutil.which("xsim"):
        pytest.skip("The XMOS simulator is required")
    config = re.sub(r'^#include .*$', '', (FIRMWARE / "src/app_conf.h").read_text(), flags=re.M)
    layout = (FIXED / "audio_pipeline_dsp.h").read_text()
    frame = layout[layout.index("typedef struct {"):layout.index("typedef struct stage_delay_ctx")]
    legacy_frame = r'''
typedef struct {
    _Alignas(8) int32_t samples[CHANNELS][240];
    int32_t aec_reference_audio_samples[2][240];
    int32_t mic_samples_passthrough[CHANNELS][240];
    int32_t vnr_pred_flag;
    float_s32_t max_ref_energy;
    float_s32_t aec_corr_factor;
    int32_t ref_active_flag;
} legacy_frame_t;
'''
    stages = ""
    if channels == 4:
        stages = function(FIXED / "audio_pipeline_t0.c", "stage_average_aec_residuals")
        stages += function(FIXED / "audio_pipeline_t1.c", "mix_stereo_reference_to_mono")
        stages += function(FIXED / "audio_pipeline_t1.c", "audio_pipeline_input_i").replace(
            "audio_pipeline_input_i", "tile1_input")
        stages += function(FIXED / "audio_pipeline_t1.c", "audio_pipeline_output_i").replace(
            "audio_pipeline_output_i", "tile1_output")
        stages += function(FIXED / "audio_pipeline_t0.c", "audio_pipeline_input_i").replace(
            "audio_pipeline_input_i", "tile0_input")
        stages += function(FIXED / "audio_pipeline_t0.c", "audio_pipeline_output_i").replace(
            "audio_pipeline_output_i", "tile0_output")
    source = r'''
#include <assert.h>
#include <limits.h>
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#define MIC_ARRAY_CONFIG_MIC_COUNT CHANNELS
#define MIC_ARRAY_CONFIG_SAMPLES_PER_FRAME 240
#define appconfMIC_PIPELINE_PROC_CHANNELS CHANNELS
#define appconfI2S_AUDIO_SAMPLE_RATE SAMPLE_RATE
#define appconfAUDIO_SPK_PL_SR_FACTOR (SAMPLE_RATE / 16000)
#define ON_TILE(x) 1
#define portMAX_DELAY (-1)
#define portBYTE_ALIGNMENT 8
#define RTOS_OSAL_WAIT_FOREVER (-1)
#define AUDIO_PIPELINE_FREE_FRAME 1
#define xassert assert
#define configASSERT assert
#define AP_MAX_Y_CHANNELS CHANNELS
#define DWORD_ALIGNED
#define NS_FRAME_ADVANCE 240
typedef struct { int32_t mant; int exp; } float_s32_t;
''' + config + r'''
static void *mic_array_ctx, *i2s_ctx, *ref_input_queue, *intertile_ctx;
static void *expected_mic;
static unsigned input_step, frame_index;
static int32_t mic_input[CHANNELS][240], reference_input[240][2];
static int32_t transmitted[720][2];
static size_t transmitted_frames;
static struct { int state; } ns_stage_state;

/* Startup drains one stale frame, waits for the first fresh frame, then
 * receives reference audio before reading the frame to be processed.
 */
static size_t rtos_mic_array_rx(void *ctx, int32_t **p, size_t frames, int wait) {
    assert((void *)p == expected_mic);
    assert((uintptr_t)p % portBYTE_ALIGNMENT == 0 && frames == 240);
    switch (input_step++) {
        case 0:
            assert(frame_index == 0 && wait == 0);
            memset(p, 0x55, sizeof(mic_input));
            return frames;
        case 1:
            assert(frame_index == 0 && wait == 0);
            return 0;
        case 2:
            assert(frame_index == 0 && wait == portMAX_DELAY);
            memset(p, 0xaa, sizeof(mic_input));
            return frames;
        case 5:
            assert(wait == portMAX_DELAY);
            memcpy(p, mic_input, sizeof(mic_input));
            return frames;
        default:
            assert(0 && "Unexpected microphone read");
            return 0;
    }
}
static int rtos_osal_queue_receive(void *ctx, void *out, int wait) {
    assert(input_step++ == 3 && wait == RTOS_OSAL_WAIT_FOREVER);
    *(void **)out = reference_input;
    return 0;
}
static void rtos_osal_free(void *p) {
    assert(input_step++ == 4 && p == reference_input);
}
static void rtos_i2s_tx(void *ctx, int32_t *p, size_t frames, int wait) {
    assert(frames == 240 * (SAMPLE_RATE / 16000) && wait == portMAX_DELAY);
    transmitted_frames = frames;
    memcpy(transmitted, p, frames * 2 * sizeof(int32_t));
}
static void ns_process_frame(int *state, int32_t *out, const int32_t *in) {
    for (unsigned i = 0; i < 240; ++i) out[i] = in[i] / 2;
}

#if CHANNELS == 4
static unsigned char *frame_storage[2];
static unsigned allocations;
static void *pvPortMalloc(size_t bytes) {
    assert(bytes == 5784 && allocations < 2);
    unsigned char *storage = malloc(bytes + 16);
    assert(storage != NULL);
    memset(storage, 0x5a, bytes + 16);
    if (allocations == 0) expected_mic = storage + 8;
    frame_storage[allocations++] = storage;
    return storage + 8;
}
static unsigned char intertile_payload[5784];
static size_t payload_size;
static void rtos_intertile_tx(void *ctx, unsigned port, void *p, size_t bytes) {
    assert(port == appconfAUDIOPIPELINE_PORT && bytes == sizeof(intertile_payload));
    memcpy(intertile_payload, p, bytes);
    payload_size = bytes;
}
static size_t rtos_intertile_rx_len(void *ctx, unsigned port, int wait) {
    assert(port == appconfAUDIOPIPELINE_PORT && wait == portMAX_DELAY);
    return payload_size;
}
static void rtos_intertile_rx_data(void *ctx, void *p, size_t bytes) {
    assert(bytes == payload_size);
    memcpy(p, intertile_payload, bytes);
    payload_size = 0;
}
#endif
'''
    source += legacy_frame
    if channels == 4:
        source += frame
    else:
        source += "typedef legacy_frame_t frame_data_t;\n"
    for name in ("mic_gain_10x", "audio_pipeline_capture", "audio_pipeline_input",
                 "audio_pipeline_output_channels", "audio_pipeline_output"):
        source += function(FIRMWARE / "src/main.c", name)
    source += stages + function(FIXED / "audio_pipeline_t0.c", "stage_ns")
    source += r'''
static int32_t expected_gain(int32_t sample) {
    int64_t scaled = (int64_t)sample * 10;
    return scaled > INT32_MAX ? INT32_MAX : scaled < INT32_MIN ? INT32_MIN : (int32_t)scaled;
}

int main(void) {
#if CHANNELS == 4
    _Static_assert(sizeof(legacy_frame_t) == 9624 && sizeof(frame_data_t) == 5784, "Frame size");
#endif
    struct { uint64_t before; frame_data_t data; uint64_t after; } guarded = {0};
    guarded.before = guarded.after = 0x12345678abcdefULL;
    frame_data_t *f = &guarded.data;
    for (frame_index = 0; frame_index < 8; ++frame_index) {
        for (unsigned i = 0; i < 240; ++i) {
            reference_input[i][0] = frame_index == 0 ? 0 : (int32_t)i + (int32_t)frame_index - 300;
            reference_input[i][1] = frame_index == 0 ? 0 : 2 * (int32_t)i + 101;
            for (unsigned ch = 0; ch < CHANNELS; ++ch) {
                mic_input[ch][i] = frame_index == 0 ? 0 :
                    (int32_t)(frame_index * 10000 + ch * 1000 + i) - 40000;
            }
        }
        if (frame_index > 0) {
            mic_input[0][0] = INT32_MAX;
            mic_input[1][1] = INT32_MIN;
            mic_input[0][2] = INT32_MAX / 10;
            mic_input[1][3] = INT32_MIN / 10;
            mic_input[0][4] = INT32_MAX / 10 + 1;
            mic_input[1][5] = INT32_MIN / 10 - 1;
            reference_input[0][0] = reference_input[0][1] = INT32_MAX;
            reference_input[1][0] = reference_input[1][1] = INT32_MIN;
            reference_input[2][0] = INT32_MAX;
            reference_input[2][1] = INT32_MIN;
        }

        input_step = frame_index == 0 ? 0 : 3;
#if CHANNELS == 4
        allocations = 0;
        frame_data_t *captured = tile1_input(NULL);
        assert((void *)captured->samples == expected_mic);
        assert(captured->vnr_pred_flag == 0 && captured->ref_active_flag == 0);
        assert(captured->max_ref_energy.mant == 0 && captured->max_ref_energy.exp == 0);
        assert(captured->aec_corr_factor.mant == 0 && captured->aec_corr_factor.exp == 0);
        captured->vnr_pred_flag = 1;
        captured->max_ref_energy = (float_s32_t){(int32_t)frame_index, -4};
        captured->aec_corr_factor = (float_s32_t){42, -6};
        captured->ref_active_flag = frame_index % 2;
        assert(tile1_output(captured, NULL) == AUDIO_PIPELINE_FREE_FRAME);
        frame_data_t *received = tile0_input(NULL);
        assert(allocations == 2 && payload_size == 0);
        assert(memcmp(received, captured, sizeof(*received)) == 0);
#else
        expected_mic = f->mic_samples_passthrough;
        audio_pipeline_input(NULL, (int32_t **)f->aec_reference_audio_samples, 2 + CHANNELS, 240);
#endif
        assert(input_step == 6);
        for (unsigned i = 0; i < 240; ++i) {
#if CHANNELS == 4
            int64_t sum = (int64_t)reference_input[i][0] + reference_input[i][1];
            assert(received->aec_reference_audio_samples[0][i] == sum / 2);
            assert(received->aec_reference_audio_samples[1][i] == reference_input[i][1]);
            for (unsigned ch = 0; ch < CHANNELS; ++ch)
                assert(received->samples[ch][i] == expected_gain(mic_input[ch][i]));
#else
            assert(f->aec_reference_audio_samples[0][i] == reference_input[i][0]);
            assert(f->aec_reference_audio_samples[1][i] == reference_input[i][1]);
            for (unsigned ch = 0; ch < CHANNELS; ++ch)
                assert(f->mic_samples_passthrough[ch][i] == expected_gain(mic_input[ch][i]));
#endif
        }
#if CHANNELS == 4
        /* Use captured samples as stand-ins for AEC residuals; AEC is not linked
         * by this harness. A post-NS offset distinguishes the two ESP outputs.
         */
        stage_average_aec_residuals(received);
        stage_ns(received);
        for (unsigned i = 0; i < 240; ++i) received->samples[0][i] += 17;
        transmitted_frames = 0;
        assert(tile0_output(received, NULL) == AUDIO_PIPELINE_FREE_FRAME);
        unsigned factor = SAMPLE_RATE / 16000;
        assert(transmitted_frames == 240 * factor);
        for (unsigned i = 0; i < 240 * factor; ++i) {
            int64_t sum = 0;
            for (unsigned ch = 0; ch < CHANNELS; ++ch)
                sum += expected_gain(mic_input[ch][i / factor]);
            int32_t ns = (int32_t)(sum / 4) / 2;
            assert(transmitted[i][0] == ns + 17 && transmitted[i][1] == ns);
        }
        for (unsigned frame = 0; frame < 2; ++frame) {
            for (unsigned i = 0; i < 8; ++i) {
                assert(frame_storage[frame][i] == 0x5a);
                assert(frame_storage[frame][5784 + 8 + i] == 0x5a);
            }
            free(frame_storage[frame]);
        }
#endif
    }
#if CHANNELS == 4
    const int32_t cases[][4] = {
        {INT32_MAX, INT32_MAX, INT32_MAX, INT32_MAX},
        {INT32_MIN, INT32_MIN, INT32_MIN, INT32_MIN},
        {INT32_MAX, INT32_MIN, INT32_MAX, INT32_MIN},
        {-1, -2, -3, -1}, {1, 2, 3, 1}, {0, 0, 0, 0},
        {0, 0, 0, 400}, {400, 0, 0, 0}};
    for (unsigned n = 0; n < sizeof(cases) / sizeof(cases[0]); ++n) {
        int64_t sum = 0;
        for (unsigned ch = 0; ch < 4; ++ch) {
            sum += cases[n][ch];
            for (unsigned i = 0; i < 240; ++i) f->samples[ch][i] = cases[n][ch];
        }
        stage_average_aec_residuals(f);
        for (unsigned i = 0; i < 240; ++i) {
            assert(f->samples[0][i] == sum / 4);
            for (unsigned ch = 1; ch < 4; ++ch) assert(f->samples[ch][i] == cases[n][ch]);
        }
    }
    const int32_t pairs[][2] = {{INT32_MAX, INT32_MAX}, {INT32_MIN, INT32_MIN},
        {INT32_MAX, INT32_MIN}, {-2, -1}, {100, 300}};
    for (unsigned n = 0; n < sizeof(pairs) / sizeof(pairs[0]); ++n) {
        for (unsigned i = 0; i < 240; ++i) {
            f->aec_reference_audio_samples[0][i] = pairs[n][0];
            f->aec_reference_audio_samples[1][i] = pairs[n][1];
        }
        mix_stereo_reference_to_mono(f);
        for (unsigned i = 0; i < 240; ++i) {
            assert(f->aec_reference_audio_samples[0][i] == ((int64_t)pairs[n][0] + pairs[n][1]) / 2);
            assert(f->aec_reference_audio_samples[1][i] == pairs[n][1]);
        }
    }
#endif
    for (unsigned i = 0; i < 240; ++i) f->samples[0][i] = 2000 + 2 * i;
    stage_ns(f);
    for (unsigned i = 0; i < 240; ++i) {
        assert(f->samples[0][i] == 1000 + i);
        assert(f->aec_reference_audio_samples[1][i] == 1000 + i);
        f->samples[0][i] += 10000;
    }
#if CHANNELS == 4
    assert(tile0_output(f, NULL) == AUDIO_PIPELINE_FREE_FRAME);
#else
    assert(audio_pipeline_output(NULL, (int32_t **)f->samples, CHANNELS * 2 + 2, 240) == 1);
#endif
    unsigned factor = SAMPLE_RATE / 16000;
    for (unsigned i = 0; i < 240 * factor; ++i) {
        assert(transmitted[i][0] == 11000 + i / factor);
        assert(transmitted[i][1] == 1000 + i / factor);
    }
    assert(guarded.before == 0x12345678abcdefULL && guarded.after == guarded.before);
    return 0;
}
'''
    harness = tmp_path / "pipeline_contract.c"
    harness.write_text(source)
    binary = tmp_path / ("pipeline_contract.xe" if backend == "xcore" else "pipeline_contract")
    flags = (["-target=XCORE-AI-EXPLORER", "-mcmodel=large", "-Os"]
        if backend == "xcore" else ["-fsanitize=undefined,address", "-fno-sanitize-recover=all"])
    subprocess.run([compiler, "-std=c11", "-Werror=implicit-function-declaration", *flags,
        f"-DCHANNELS={channels}", f"-DSAMPLE_RATE={sample_rate}",
        str(harness), "-o", str(binary)], check=True)
    subprocess.run((["xsim"] if backend == "xcore" else []) + [str(binary)], check=True)


def test_averaging_precedes_ns_and_agc():
    source = (FIXED / "audio_pipeline_t0.c").read_text()
    stages = re.search(r"const pipeline_stage_t stages\[\] = \{(.*?)\};", source, re.S)[1]
    assert re.findall(r"\(pipeline_stage_t\)(\w+)", stages) == [
        "stage_average_aec_residuals", "stage_vnr_and_ic", "stage_ns", "stage_agc"]
    assert "voice_ic_calc_vnr_pred" in source
    assert "f32_to_float_s32(frame_data->vnr_pred_flag)" in source


def test_bypass_preserves_raw_microphone(tmp_path):
    compiler = shutil.which("cc")
    if not compiler:
        pytest.skip("A host C compiler is required")
    source = """
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#define appconfPIPELINE_BYPASS 1
#define appconfAUDIO_PIPELINE_FRAME_ADVANCE 240
#define AP_MAX_Y_CHANNELS 4
typedef struct { int32_t samples[4][240]; } frame_data_t;
"""
    source += function(FIXED / "audio_pipeline_t0.c", "stage_average_aec_residuals")
    source += """
int main(void) {
    frame_data_t f = {0};
    f.samples[0][0] = 400;
    stage_average_aec_residuals(&f);
    assert(f.samples[0][0] == 400);
    return 0;
}
"""
    harness = tmp_path / "bypass.c"
    harness.write_text(source)
    binary = tmp_path / "bypass"
    subprocess.run([compiler, "-std=c11", str(harness), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)


def test_cmake_target_isolation():
    source = (FIRMWARE / "audio_pipelines/reference/CMakeLists.txt").read_text()
    assert "appconfAUDIO_PIPELINE_SKIP_IC_AND_VNR=1" in source
    assert "INTERFACE_FPH_MIC_CHANNELS 4" in source
    for name in ("adec_aec_ic_ns_agc_2mic_2ref", "adec_altarch_aec_ic_ns_agc_2mic_2ref"):
        links = re.search(r"target_link_libraries\(" + name + r"(.*?)\)", source, re.S)[1]
        assert "voice_compat" in links and "fwk_voice::aec" in links
        assert "fwk_voice::ic" in links and "fph::aec_4y" not in links
    assert "FIXED_DELAY_ONLY" not in (FIRMWARE / "firmware.cmake").read_text()
