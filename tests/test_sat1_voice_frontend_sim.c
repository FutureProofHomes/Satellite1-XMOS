#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <xcore/hwtimer.h>
#include "aec.h"
#include "aec_schedule_4y.h"
#include "agc.h"
#include "ns.h"
#include "ic.h"
#include "voice_frontend/sat1_voice_frontend.h"

/* The latency reference and AEC never run concurrently; share their storage. */
static union { ic_state_t ic; aec_state_t aec; } harness;
static ns_state_t ns;
static agc_state_t agc;
static sat1_beamformer_t raw_calibration;
static int32_t source[8192], voice[8192];
static int32_t raw[4][240], residual[4][240], reference[1][240];
static int32_t temporary[240], output[240], reference_output[240];

static void test_latency(void)
{
    sat1_voice_frontend_init();
    assert(ic_init(&harness.ic) == 0);
    sat1_voice_frame_t metadata;
    memset(&metadata, 0, sizeof(metadata));
    metadata.flags = SAT1_VOICE_NEAR_SPEECH | SAT1_VOICE_UNSETTLED;
    metadata.speech_q15 = 30000;
    unsigned max_difference = 0;
    for (unsigned frame = 0; frame < 8; ++frame) {
        memset(reference, 0, sizeof(reference));
        memset(residual, 0, sizeof(residual));
        for (unsigned i = 0; i < 240; ++i)
            temporary[i] = residual[0][i] = source[frame * 240 + i];
        ic_filter(&harness.ic, temporary, reference[0], reference_output);
        sat1_voice_frontend_cleanup(residual, &metadata);
        for (unsigned i = 0; i < 240; ++i) {
            int64_t difference = (int64_t)residual[0][i] - reference_output[i];
            unsigned magnitude = difference < 0 ? -difference : difference;
            if (magnitude > max_difference) max_difference = magnitude;
            assert(magnitude < 4096); /* FFT/WOLA rounding; no sample shift. */
        }
    }
    printf("IC protected bypass matches actual IC delay; maximum difference=%u LSB\n",
           max_difference);
}

int main(void)
{
    uint32_t random = 0x7d2ac419;
    for (unsigned i = 0; i < 8192; ++i) {
        random = random * 1664525U + 1013904223U;
        source[i] = ((int32_t)(random & 0xffffU) - 32768) * 1024;
        random = random * 1664525U + 1013904223U;
        voice[i] = ((int32_t)(random & 0xffffU) - 32768) * 512;
    }
    test_latency();
    unsigned max_aec = 0, max_analysis = 0, max_cleanup = 0, max_post = 0;
    for (unsigned boot = 0; boot < 2; ++boot) {
        memset(&harness, 0, sizeof(harness));
        aec_init(&harness.aec, 4, 1, 10, 5, &aec_tdist_chans4_threads1);
        sat1_voice_frontend_init();
        sat1_beamformer_reset(&raw_calibration);
        ns_init(&ns);
        agc_init(&agc, &AGC_PROFILE_ASR);
        for (unsigned frame = 0; frame < 12; ++frame) {
            for (unsigned i = 0; i < 240; ++i) {
                unsigned n = frame * 240 + i + 32;
                reference[0][i] = frame < 2 ? 0 : source[n];
                for (unsigned mic = 0; mic < 4; ++mic)
                    raw[mic][i] = source[n - 8 - mic] / 2 + voice[n - mic];
            }
            const int32_t *mics[4] = {raw[0], raw[1], raw[2], raw[3]};
            sat1_beamformer_analyze_frame(&raw_calibration, mics, 240);
            sat1_voice_frame_t metadata;
            memset(&metadata, 0, sizeof(metadata));
            sat1_beamformer_get_diagnostics(&metadata.calibration);
            unsigned start = get_reference_time();
            aec_process_frame(&harness.aec, residual, NULL, raw, reference);
            unsigned ticks = get_reference_time() - start;
            if (ticks > max_aec) max_aec = ticks;
            float_s32_t correlation = aec_calc_corr_factor(&harness.aec.main_state, 0);
            doa_estimator_set_control(frame >= 2 ? DOA_ESTIMATOR_CONTROL_PLAYBACK_ACTIVE : 0);
            start = get_reference_time();
            sat1_voice_frontend_analyze(residual, reference[0], correlation, frame >= 2, &metadata);
            ticks = get_reference_time() - start;
            if (ticks > max_analysis) max_analysis = ticks;
            printf("frontend boot=%u frame=%u analysis_ticks=%u speech=%u echo=%u flags=%u\n",
                   boot, frame, ticks, metadata.speech_q15, metadata.echo_q15, metadata.flags);
            assert(ticks < 1500000);
            unsigned post_start = start;
            start = get_reference_time();
            sat1_voice_frontend_cleanup(residual, &metadata);
            ticks = get_reference_time() - start;
            if (ticks > max_cleanup) max_cleanup = ticks;
            ns_process_frame(&ns, temporary, residual[0]);
            agc_meta_data_t md;
            memset(&md, 0, sizeof(md));
            md.vnr_flag = f32_to_float_s32((metadata.flags & SAT1_VOICE_NEAR_SPEECH) != 0);
            md.aec_ref_power = aec_calc_max_input_energy(reference, 1);
            md.aec_corr_factor = correlation;
            md.ref_active_flag = frame >= 2;
            agc_process_frame(&agc, output, temporary, &md);
            ticks = get_reference_time() - post_start;
            if (ticks > max_post) max_post = ticks;
            assert(ticks < 1500000);
            doa_estimator_state_t observation;
            doa_estimator_get_observation(&observation);
            assert(observation.frame_counter == frame + 1);
            assert(metadata.calibration.active_mic_mask != 0);
        }
    }
    printf("Real 4Y1X AEC + VNR/DoA/beam + protected IC/echo + NS/AGC passed24frames/2initializations; max ticks AEC=%u analysis=%u cleanup=%u all_post=%u\n",
           max_aec, max_analysis, max_cleanup, max_post);
    return 0;
}
