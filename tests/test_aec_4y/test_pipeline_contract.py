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
    start = re.search(r"^(?:static )?(?:void|int|int32_t) " + name + r"\(", source, re.M).start()
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
    frame = re.search(r"typedef struct \{.*?\} frame_data_t;", (FIXED / "audio_pipeline_dsp.h").read_text(), re.S)[0]
    stages = ""
    if channels == 4:
        stages = function(FIXED / "audio_pipeline_t0.c", "stage_average_aec_residuals")
        stages += function(FIXED / "audio_pipeline_t1.c", "mix_stereo_reference_to_mono")
    source = r'''
#include <assert.h>
#include <limits.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#define MIC_ARRAY_CONFIG_MIC_COUNT CHANNELS
#define MIC_ARRAY_CONFIG_SAMPLES_PER_FRAME 240
#define appconfMIC_PIPELINE_PROC_CHANNELS CHANNELS
#define appconfI2S_AUDIO_SAMPLE_RATE SAMPLE_RATE
#define ON_TILE(x) 0
#define portMAX_DELAY (-1)
#define AUDIO_PIPELINE_FREE_FRAME 1
#define xassert assert
#define configASSERT assert
#define AP_MAX_Y_CHANNELS CHANNELS
#define DWORD_ALIGNED
#define NS_FRAME_ADVANCE 240
typedef struct { int32_t mant; int exp; } float_s32_t;
static void *mic_array_ctx, *i2s_ctx;
static int32_t *expected_mic;
static int32_t transmitted[720][2];
static struct { int state; } ns_stage_state;
static size_t rtos_mic_array_rx(void *ctx, int32_t **p, size_t frames, int wait) {
    assert((int32_t *)p == expected_mic);
    if (wait == 0) return 0;
    for (size_t i = 0; i < CHANNELS * frames; ++i) ((int32_t *)p)[i] = (int32_t)i;
    return frames;
}
static void rtos_i2s_tx(void *ctx, int32_t *p, size_t frames, int wait) {
    memcpy(transmitted, p, frames * 2 * sizeof(int32_t));
}
static void ns_process_frame(int *state, int32_t *out, const int32_t *in) {
    for (unsigned i = 0; i < 240; ++i) out[i] = in[i] / 2;
}
'''
    source += config + frame + stages
    source += function(FIXED / "audio_pipeline_t0.c", "stage_ns")
    for name in ("mic_gain_10x", "audio_pipeline_input", "audio_pipeline_output"):
        source += function(FIRMWARE / "src/main.c", name)
    source += r'''
int main(void) {
    struct { uint64_t before; frame_data_t data; uint64_t after; } guarded = {0};
    guarded.before = guarded.after = 0x12345678abcdefULL;
    frame_data_t *f = &guarded.data;
    for (unsigned i = 0; i < 240; ++i) {
        f->aec_reference_audio_samples[0][i] = 123;
        f->aec_reference_audio_samples[1][i] = 456;
    }
    expected_mic = f->mic_samples_passthrough[0];
    audio_pipeline_input(NULL, (int32_t **)f->aec_reference_audio_samples,
        2 + CHANNELS, 240);
    for (unsigned i = 0; i < 240; ++i) {
        assert(f->aec_reference_audio_samples[0][i] == 123);
        assert(f->aec_reference_audio_samples[1][i] == 456);
        for (unsigned ch = 0; ch < CHANNELS; ++ch)
            assert(f->mic_samples_passthrough[ch][i] == mic_gain_10x(ch * 240 + i));
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
    assert(audio_pipeline_output(NULL, (int32_t **)f->samples, CHANNELS * 2 + 2, 240) == 1);
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
