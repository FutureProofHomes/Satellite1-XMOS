#include <assert.h>
#include <stdio.h>
#include "doa_estimator.h"

int main(void)
{
    int32_t zero[240] = {0};
    doa_estimator_diagnostics_t diagnostics;
    for (unsigned tracking = 0; tracking < 2; ++tracking) {
        doa_estimator_reset();
        if (tracking) doa_estimator_set_tracking_evidence(0, 0);
        doa_estimator_set_control(DOA_ESTIMATOR_CONTROL_PLAYBACK_ACTIVE |
                                  DOA_ESTIMATOR_CONTROL_VOICE_ACTIVE);
        for (unsigned frame = 0; frame < 160; ++frame)
            doa_estimator_process_frame_4(zero, zero, zero, zero, 240);
        doa_estimator_get_diagnostics(&diagnostics);
        assert(diagnostics.control_flags == 9);
        doa_estimator_process_frame_4(zero, zero, zero, zero, 240);
        doa_estimator_get_diagnostics(&diagnostics);
        assert(diagnostics.control_flags == (tracking ? 0 : 9));
        doa_estimator_set_control(9);
        doa_estimator_get_diagnostics(&diagnostics);
        assert(diagnostics.control_flags == 9);
        for (unsigned frame = 0; frame < 500; ++frame) {
            if (frame % 60 == 0) doa_estimator_set_control(9);
            doa_estimator_process_frame_4(zero, zero, zero, zero, 240);
            doa_estimator_get_diagnostics(&diagnostics);
            assert(diagnostics.control_flags == 9);
        }
    }
    doa_estimator_reset();
    doa_estimator_set_tracking_evidence(0, 0);
    doa_estimator_set_control(DOA_ESTIMATOR_CONTROL_FORCE_OMNI | DOA_ESTIMATOR_CONTROL_VOICE_LOCK);
    doa_estimator_set_host_hints(0xff); // The hint command owns only bits 0 and 3.
    doa_estimator_get_diagnostics(&diagnostics);
    assert(diagnostics.control_flags == 15);
    for (unsigned frame = 0; frame < 161; ++frame)
        doa_estimator_process_frame_4(zero, zero, zero, zero, 240);
    doa_estimator_get_diagnostics(&diagnostics);
    assert(diagnostics.control_flags == 6); // Expiry must preserve both manual controls.
    doa_estimator_set_host_hints(9);
    doa_estimator_set_host_hints(0);
    doa_estimator_get_diagnostics(&diagnostics);
    assert(diagnostics.control_flags == 6);
    puts("New host hints expire/recover; legacy controls persist; heartbeat maintains the lease.");
}
