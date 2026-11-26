"""Execute actual telemetry/capability serialization for legacy and new profiles."""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "satellite-xmos-firmware/src"


def function(source, signature):
    start = source.index(signature)
    opening = source.index("{", start)
    depth, end = 1, opening + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


@pytest.mark.parametrize("frontend", [0, 1])
def test_compatible_packets_and_explicit_capability(tmp_path, frontend):
    source = (SRC / "doa/doa_servicer.c").read_text()
    harness = r'''
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include "doa/doa_cmds.h"
#include "doa/doa_estimator.h"
#include "beamforming/sat1_beamformer.h"
typedef uint8_t control_ret_t, control_resid_t, control_cmd_t;
typedef struct { int ignored; } servicer_t, control_resource_info_t, control_cmd_info_t;
#define CONTROL_SUCCESS 0
#define CONTROL_BAD_COMMAND 9
#define CONTROL_BAD_RESOURCE 8
#define CONTROL_CMD_CLEAR_READ(x) ((x) & 0x7f)
#define xassert assert
static control_resource_info_t resource;
static control_resource_info_t *get_res_info(control_resid_t id, servicer_t *s) { return &resource; }
static control_ret_t validate_cmd(control_cmd_info_t **i, control_resource_info_t *r,
    control_cmd_t c, const uint8_t *p, size_t n) { return 0; }
static unsigned control_writes, hint_writes;
void doa_estimator_set_control(uint8_t flags) { assert(flags == 9); ++control_writes; }
void doa_estimator_set_host_hints(uint8_t flags) { assert(flags == 9); ++hint_writes; }
void doa_estimator_get_state(doa_estimator_state_t *s) {
    memset(s, 0, sizeof(*s)); s->angle_index = 6; s->flags = 2; s->frame_counter = 0x12345678;
}
void doa_estimator_get_observation(doa_estimator_state_t *s) {
    doa_estimator_get_state(s); s->angle_index = 0; s->flags = 3; s->confidence = 40;
}
void doa_estimator_get_diagnostics(doa_estimator_diagnostics_t *d) { memset(d,0,sizeof(*d)); }
void sat1_beamformer_get_diagnostics(sat1_beamformer_diagnostics_t *d) { memset(d,0,sizeof(*d)); }
'''
    harness += function(source, "static void store_u16_le(")
    harness += function(source, "static void store_u32_le(")
    harness += function(source, "static control_ret_t doa_servicer_read_cmd(")
    harness += function(source, "static control_ret_t doa_servicer_write_cmd(")
    harness += r'''
int main(void) {
    uint8_t packet[64];
    servicer_t s = {0};
    memset(packet, 0x5a, sizeof(packet));
    assert(DOA_SERVICER_STATE_NUM_VALUES == 32 && DOA_SERVICER_DIAGNOSTICS_NUM_VALUES == 48);
    assert(doa_servicer_read_cmd(233, 0x83, packet, 9, &s) == 0);
    assert(memcmp(packet + 1, "S1D\1", 4) == 0);
    assert(packet[5] == appconfSAT1_SPEECH_FRONTEND && packet[6] == 0 && packet[7] == 0 && packet[8] == 0);
    assert(packet[9] == 0x5a);
    assert(doa_servicer_read_cmd(233, 0x80, packet, 33, &s) == 0);
    assert(packet[4] == (appconfSAT1_SPEECH_FRONTEND ? 3 : 2));
    assert(packet[15] == (appconfSAT1_SPEECH_FRONTEND ? 0 : 6));
    assert(packet[9] == 0x78 && packet[10] == 0x56 && packet[11] == 0x34 && packet[12] == 0x12);
    assert(packet[16] == 0); // Reserved byte remains reserved.
    uint8_t flags = 9;
    assert(doa_servicer_write_cmd(233, 2, &flags, 1, &s) == 0);
    assert(control_writes == 1 && hint_writes == 0);
    assert(doa_servicer_write_cmd(233, 4, &flags, 1, &s) == (appconfSAT1_SPEECH_FRONTEND ? 0 : 9));
    assert(control_writes == 1 && hint_writes == appconfSAT1_SPEECH_FRONTEND);
}
'''
    path = tmp_path / "packet.c"
    path.write_text(harness)
    binary = tmp_path / "packet"
    subprocess.run([shutil.which("cc"), "-std=c11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter",
                    f"-DappconfSAT1_SPEECH_FRONTEND={frontend}", "-I", str(SRC), str(path), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
