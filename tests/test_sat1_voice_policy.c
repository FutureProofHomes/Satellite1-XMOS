#include <assert.h>
#include <limits.h>
#include <stdio.h>
#include "voice_frontend/sat1_voice_policy.h"

static int32_t source[8192], independent[8192];
static uint32_t random_state = 0x9b174e39;
static int32_t next_sample(void)
{
    random_state ^= random_state << 13;
    random_state ^= random_state >> 17;
    random_state ^= random_state << 5;
    return (int32_t)(random_state & 0x3fffffffU) - 0x20000000;
}

static void test_echo_and_voice(void)
{
    static sat1_voice_policy_t policy;
    int32_t microphone[240], reference[240];
    const unsigned delays[] = {0, 32, 1024};
    for (unsigned case_id = 0; case_id < 3; ++case_id) {
        sat1_voice_policy_reset(&policy);
        uint8_t flags = 0;
        for (unsigned frame = 0; frame < 12; ++frame) {
            for (unsigned i = 0; i < 240; ++i) {
                unsigned n = frame * 240 + i;
                reference[i] = source[n];
                microphone[i] = n >= delays[case_id] ? -source[n - delays[case_id]] / 8 : 0;
            }
            /* Playback can contain vocals: a high VNR alone must not steer. */
            flags = sat1_voice_policy_analyze(&policy, microphone, reference, 30000, true);
        }
        assert(flags & SAT1_VOICE_ECHO_ONLY);
        assert(!(flags & SAT1_VOICE_NEAR_SPEECH));
        assert(policy.echo_q15 > 32000);
        assert(policy.echo_lag_samples == delays[case_id]);
    }
    sat1_voice_policy_reset(&policy);
    uint8_t flags = 0;
    for (unsigned frame = 0; frame < 12; ++frame) {
        for (unsigned i = 0; i < 240; ++i) {
            reference[i] = source[frame * 240 + i];
            microphone[i] = independent[frame * 240 + i];
        }
        flags = sat1_voice_policy_analyze(&policy, microphone, reference, 30000, true);
    }
    assert(flags & SAT1_VOICE_NEAR_SPEECH);
    assert(!(flags & SAT1_VOICE_ECHO_ONLY));
    for (unsigned frame = 0; frame < 7; ++frame)
        flags = sat1_voice_policy_analyze(&policy, microphone, reference, 0, false);
    assert(!(flags & SAT1_VOICE_NEAR_SPEECH));

    /* Full-scale arithmetic, including polarity inversion and DC. */
    for (unsigned frame = 0; frame < 8; ++frame) {
        for (unsigned i = 0; i < 240; ++i) {
            microphone[i] = ((i / 4) & 1) ? INT32_MIN : INT32_MAX;
            reference[i] = microphone[i];
        }
        (void)sat1_voice_policy_analyze(&policy, microphone, reference, 0, true);
    }
    assert(policy.echo_q15 <= 32768);

    /* Large unrelated offsets must not suppress independent near-end speech. */
    sat1_voice_policy_reset(&policy);
    for (unsigned frame = 0; frame < 12; ++frame) {
        for (unsigned i = 0; i < 240; ++i) {
            reference[i] = (1 << 28) + source[frame * 240 + i] / 64;
            microphone[i] = (1 << 29) + independent[frame * 240 + i] / 64;
        }
        flags = sat1_voice_policy_analyze(&policy, microphone, reference, 30000, true);
    }
    assert(flags & SAT1_VOICE_NEAR_SPEECH);
    assert(!(flags & SAT1_VOICE_ECHO_ONLY));
    /* Correlated echo remains detectable with different offsets and gains. */
    for (unsigned frame = 0; frame < 12; ++frame) {
        for (unsigned i = 0; i < 240; ++i) {
            reference[i] = (1 << 28) + source[frame * 240 + i] / 64;
            microphone[i] = (1 << 29) - source[frame * 240 + i] / 128;
        }
        flags = sat1_voice_policy_analyze(&policy, microphone, reference, 30000, true);
    }
    assert(flags & SAT1_VOICE_ECHO_ONLY);
    assert(!(flags & SAT1_VOICE_NEAR_SPEECH));
    for (unsigned frame = 0; frame < 8; ++frame) {
        for (unsigned i = 0; i < 240; ++i) {
            reference[i] = INT32_MAX;
            microphone[i] = INT32_MIN;
        }
        flags = sat1_voice_policy_analyze(&policy, microphone, reference, 30000, true);
    }
    assert(policy.echo_q15 == 0);
    assert(flags & SAT1_VOICE_NEAR_SPEECH);
}

static void test_protected_cleanup(void)
{
    int32_t primary[240], cancelled[240], output[240];
    uint16_t gain = 32768;
    for (unsigned i = 0; i < 240; ++i) {
        primary[i] = 1 << 24;
        cancelled[i] = 0; /* Worst-case IC cancelled the entire target. */
    }
    sat1_voice_protected_cleanup(primary, cancelled, output, SAT1_VOICE_NEAR_SPEECH, &gain);
    for (unsigned i = 0; i < 240; ++i) assert(output[i] >= primary[i] * 3 / 4);
    sat1_voice_protected_cleanup(primary, cancelled, output, SAT1_VOICE_UNSETTLED, &gain);
    for (unsigned i = 0; i < 240; ++i) assert(output[i] == primary[i]);
    for (unsigned i = 0; i < 240; ++i) cancelled[i] = primary[i];
    for (unsigned frame = 0; frame < 24; ++frame)
        sat1_voice_protected_cleanup(primary, cancelled, output, SAT1_VOICE_ECHO_ONLY, &gain);
    assert(gain >= 16384 && gain < 18000);
    sat1_voice_protected_cleanup(primary, cancelled, output, SAT1_VOICE_NEAR_SPEECH, &gain);
    assert(gain == 32768 && output[239] == primary[239]);
    for (unsigned i = 0; i < 240; ++i) {
        primary[i] = i & 1 ? INT32_MIN : INT32_MAX;
        cancelled[i] = i & 1 ? INT32_MAX : INT32_MIN;
    }
    sat1_voice_protected_cleanup(primary, cancelled, output, SAT1_VOICE_NEAR_SPEECH, &gain);
    for (unsigned i = 0; i < 240; ++i)
        assert(i & 1 ? output[i] < 0 : output[i] > 0);
}

int main(void)
{
    for (unsigned i = 0; i < 8192; ++i) {
        source[i] = next_sample();
        independent[i] = next_sample();
    }
    test_echo_and_voice();
    test_protected_cleanup();
    puts("Voice policy echo lag/gain, independent speech, full-scale and cancellation guards passed");
    return 0;
}
