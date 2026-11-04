#!/usr/bin/env python3
"""Writes the speaker stress signals used for the high-volume amp tests on hardware.

sat1_amp_ladder_48k: one program - pink noise band-limited to 40 Hz - 16 kHz and peak-limited to a
9 dB crest factor, which is about what a loud modern master looks like - played at nine levels 3 dB
apart. The top step peaks at -1 dBFS, the ceiling a mastering limiter leaves, and runs for a
minute; the steps below it run for 20 s. A spoken "Step N" precedes each one.

sat1_bass_ladder_48k: the same ladder confined to 40 - 200 Hz (fourth-order edges), 15 s steps and a
30 s top step. Music carries far more energy down there than pink noise does, and a speaker's
impedance is lowest there, so bass peaks draw the most current per volt.

sat1_bass_bursts_48k: Hann-windowed 6.5-cycle tone bursts, the CEA-2010 shape, at 40 - 160 Hz.
Each spoken "Level N" is followed by every frequency in turn, three bursts each, at one peak level;
the levels climb from -16 to -1 dBFS. The first burst to trip the amp names the frequency with the
least current headroom, and the short duty cycle keeps the driver cool while finding it.

sat1_bass_tones_48k: held sine tones, 1.5 s each with 0.5 s between, at 45 - 160 Hz. Each spoken
"Level N" is followed by every frequency in turn at one peak level; the levels climb 2 dB at a time
from -13 to -1 dBFS. Sub-bass in music is mostly held notes - an 808 is a near-pure tone lasting a
second or more - which at the same peak carry two to three times the power of noise and keep the cone
moving. Neither the noise ladders nor the bursts trip the amp where such music does. Played with the
EQ off, the first tone to trip names the level and frequency this amp and speaker cannot hold,
whatever the EQ.

sat1_mid_tones_48k: the same climb with 0.6 s tones, 0.6 s apart, at 1 - 3.15 kHz in sixth-octave
steps. The crossover's woofer low-pass (series 150 uH, 47 uF across a 4 ohm woofer) resonates near
1.9 kHz with a Q of about 2.2, so the amp sees about 1 ohm there: at amp level 15 dBV, a tone of about
-3 dBFS draws the TAS2780's 5.5 A over-current limit, below the EQ limiter's -1 dBFS ceiling. Played
with the EQ off, the first trip names the frequency and level of that dip.

sat1_mid_pinpoint_48k: the mid ladder's 0.6 s tone at the one level that tripped it, -3 dBFS, at
1.6 - 2.5 kHz, up and then back down, each in a 35 s slot that opens with its spoken frequency. The
amp driver polls for a shutdown once a second, too slowly to tell which of the ladder's tones 1.2 s
apart tripped it; 34 s or more apart, each trip belongs to one tone, and no more than two land in the
driver's 60 s window, which stops re-activating the amp at three. The frequencies that trip, both
ways round, bound the dip.

sat1_kick_ladder_48k: synthetic hip-hop kicks - an attack that starts at full amplitude, a pitch drop
from 150 to 50 Hz over about 30 ms and a 250 ms decay - eight at 0.5 s spacing, then four over a
49 Hz 808 note, after each spoken "Level N"; the peaks climb 2 dB at a time from -13 to -1 dBFS. The
other signals all start smoothly, so the EQ's hard limiter never has to clip them; a kick under a
boosting EQ makes it clip the first milliseconds of every hit. Play it under the boosting profile and
with the EQ off: the levels where one trips and the other doesn't size the protection.

Play them at volume 100 under each EQ condition and note where the TAS2780 reports over-current, if
it does. Songs differ in level, spectrum and crest factor from one to the next, so they cannot tell
an EQ effect from a content effect; these files are the same every time. A JSON timeline beside
each maps playback time to steps (and, for the bursts, to each burst).

Both channels carry the same samples. The TAS2780 plays (L + R) / 2, so the speaker gets exactly
the levels below, and fully correlated channels are the worst case real music approaches.

The levels only hold if nothing between these files and the device rescales them: Music Assistant
normalizes loudness by default, so play them through Home Assistant's media_player.play_media.

Usage: make_amp_ladder.py [OUT_DIR]   (needs numpy; macOS `say` for the labels, else beeps)
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import wave

import numpy as np

FS = 48000
LOOP_S = 10                       # the noise is periodic over this, so steps repeat it seamlessly
CREST_DB = 9.0
PEAKS_DBFS = [-25, -22, -19, -16, -13, -10, -7, -4, -1]
LABEL_PEAK_DBFS = -20
FADE_S = 0.02
SEED = 2780

# name, band (Hz), Butterworth order of each band edge, step length (s), top step length (s)
LADDERS = [
    ("sat1_amp_ladder_48k", (40.0, 16000.0), 2, 20, 60),
    ("sat1_bass_ladder_48k", (40.0, 200.0), 4, 15, 30),
]

BURSTS_NAME = "sat1_bass_bursts_48k"
BURST_HZ = [40, 50, 63, 80, 100, 125, 160]
BURST_PEAKS_DBFS = [-16, -13, -10, -7, -4, -1]
BURST_CYCLES = 6.5
BURST_REPEAT = 3
BURST_EVERY_S = 0.5               # onsets of one frequency's bursts
FREQ_EVERY_S = 3.0                # onsets of successive frequencies: wide enough to tell them apart

TONE_PEAKS_DBFS = [-13, -11, -9, -7, -5, -3, -1]
# name, frequencies (Hz), tone length (s), gap (s), fade (s): two cycles of the lowest tone or more,
# so the edges don't click
TONE_LADDERS = [
    ("sat1_bass_tones_48k", [45, 50, 56, 63, 71, 80, 90, 100, 125, 160], 1.5, 0.5, 0.05),
    ("sat1_mid_tones_48k", [1000, 1120, 1250, 1400, 1600, 1800, 2000, 2240, 2500, 2800, 3150], 0.6, 0.6, 0.01),
]

PIN_NAME = "sat1_mid_pinpoint_48k"
PIN_HZ = [1600, 1800, 2000, 2240, 2500]
PIN_PEAK_DBFS = -3
PIN_TONE_S, PIN_FADE_S = 0.6, 0.01   # the mid ladder's tone, so a trip here is the same event
PIN_EVERY_S = 35.0
PIN_TAIL_S = 5.0                  # after the last tone: the driver's poll and its 2 s re-activation

KICKS_NAME = "sat1_kick_ladder_48k"
KICK_PEAKS_DBFS = [-13, -11, -9, -7, -5, -3, -1]
KICK_COUNT, KICK_EVERY_S = 8, 0.5
COMBO_COUNT, COMBO_EVERY_S = 4, 1.0


def db(x):
    return 20 * np.log10(x)


def program(band, order):
    """One LOOP_S period of the noise, peak 1.0 (0 dBFS), and its RMS."""
    n = FS * LOOP_S
    f = np.fft.rfftfreq(n, 1 / FS)
    mag = np.zeros_like(f)
    lo, hi = band
    fp = f[1:]
    mag[1:] = fp ** -0.5 / np.sqrt(1 + (lo / fp) ** (2 * order)) / np.sqrt(1 + (fp / hi) ** (2 * order))
    spec = mag * np.exp(2j * np.pi * np.random.default_rng(SEED).random(f.size))

    # Clip to the crest factor and restore the spectrum, repeatedly: the peaks converge on the
    # limit while the band shape stays pink. Clipping once would splatter energy out of band.
    limit = 10 ** (CREST_DB / 20)
    for _ in range(40):
        x = np.fft.irfft(spec, n)
        x = np.clip(x / np.sqrt(np.mean(x ** 2)), -limit, limit)
        spec = mag * np.exp(1j * np.angle(np.fft.rfft(x)))
    x = np.fft.irfft(spec, n)
    x = np.clip(x / np.sqrt(np.mean(x ** 2)), -limit, limit)
    x /= np.max(np.abs(x))
    return x, float(np.sqrt(np.mean(x ** 2)))


def label(text, tmp):
    """`text` spoken, peaking at LABEL_PEAK_DBFS; numbered beeps where `say` is missing."""
    if shutil.which("say"):
        path = os.path.join(tmp, "label.wav")
        subprocess.run(["say", "-v", "Samantha", "-o", path, "--file-format=WAVE",
                        "--data-format=LEI16@%d" % FS, text], check=True)
        with wave.open(path) as w:
            v = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(float)
            if w.getnchannels() > 1:
                v = v.reshape(-1, w.getnchannels()).mean(axis=1)
    else:
        count = int(text.split()[-1]) if text.split()[-1].isdigit() else 3
        t = np.arange(int(0.08 * FS)) / FS
        beep = np.sin(2 * np.pi * 1000 * t) * np.hanning(t.size)
        v = np.concatenate([np.concatenate([beep, np.zeros(int(0.12 * FS))]) for _ in range(count)])
    return v / np.max(np.abs(v)) * 10 ** (LABEL_PEAK_DBFS / 20)


def silence(s):
    return np.zeros(int(s * FS))


def ladder(band, order, step_s, hold_s, tmp):
    loop, rms = program(band, order)
    fade = np.sin(np.linspace(0, np.pi / 2, int(FADE_S * FS))) ** 2
    parts, steps, t = [silence(2.0)], [], 2.0
    for i, peak in enumerate(PEAKS_DBFS, 1):
        speech = label("Step %d" % i, tmp)
        parts += [speech, silence(0.6)]
        t += (speech.size + int(0.6 * FS)) / FS
        dur = hold_s if i == len(PEAKS_DBFS) else step_s
        x = np.tile(loop, -(-dur // LOOP_S))[:dur * FS] * 10 ** (peak / 20)
        x[:fade.size] *= fade
        x[-fade.size:] *= fade[::-1]
        parts += [x, silence(1.0)]
        steps.append({"step": i, "start_s": round(t, 3), "end_s": round(t + dur, 3),
                      "peak_dbfs": peak, "rms_dbfs": round(peak + db(rms), 2)})
        t += dur + 1.0
    parts += [label("End of test", tmp), silence(1.0)]
    meta = {"band_hz": band, "edge_order": order, "crest_db": round(-db(rms), 2), "steps": steps}
    return np.concatenate(parts), meta


def bursts(tmp):
    shapes = {}
    for hz in BURST_HZ:
        n = int(round(BURST_CYCLES * FS / hz))
        b = np.sin(2 * np.pi * hz * np.arange(n) / FS) * np.hanning(n)
        shapes[hz] = b / np.max(np.abs(b))
    group = int(FREQ_EVERY_S * FS)
    parts, steps, events, t = [silence(2.0)], [], [], 2.0
    for i, peak in enumerate(BURST_PEAKS_DBFS, 1):
        speech = label("Level %d" % i, tmp)
        parts += [speech, silence(0.6)]
        t += (speech.size + int(0.6 * FS)) / FS
        block = np.zeros(group * len(BURST_HZ))
        for k, hz in enumerate(BURST_HZ):
            for r in range(BURST_REPEAT):
                at = k * group + int(r * BURST_EVERY_S * FS)
                block[at:at + shapes[hz].size] += shapes[hz] * 10 ** (peak / 20)
                events.append({"t_s": round(t + at / FS, 3), "hz": hz, "peak_dbfs": peak})
        parts += [block, silence(1.0)]
        dur = block.size / FS
        steps.append({"step": i, "start_s": round(t, 3), "end_s": round(t + dur, 3),
                      "peak_dbfs": peak, "rms_dbfs": None})
        t += dur + 1.0
    parts += [label("End of test", tmp), silence(1.0)]
    meta = {"burst_hz": BURST_HZ, "cycles": BURST_CYCLES, "repeat": BURST_REPEAT, "steps": steps,
            "bursts": events}
    return np.concatenate(parts), meta


def tone(hz, tone_s, fade_s):
    """A sine of `tone_s`, peak 1.0, with raised-cosine edges of `fade_s`."""
    n = int(tone_s * FS)
    ramp = np.sin(np.linspace(0, np.pi / 2, int(fade_s * FS))) ** 2
    env = np.ones(n)
    env[:ramp.size] = ramp
    env[-ramp.size:] = ramp[::-1]
    return np.sin(2 * np.pi * hz * np.arange(n) / FS) * env


def tones(hz_list, tone_s, gap_s, fade_s, tmp):
    parts, steps, events, t = [silence(2.0)], [], [], 2.0
    for i, peak in enumerate(TONE_PEAKS_DBFS, 1):
        speech = label("Level %d" % i, tmp)
        parts += [speech, silence(0.6)]
        t += (speech.size + int(0.6 * FS)) / FS
        start = t
        for hz in hz_list:
            parts += [tone(hz, tone_s, fade_s) * 10 ** (peak / 20), silence(gap_s)]
            events.append({"t_s": round(t, 3), "end_s": round(t + tone_s, 3), "hz": hz, "peak_dbfs": peak})
            t += tone_s + gap_s
        parts.append(silence(0.5))
        steps.append({"step": i, "start_s": round(start, 3), "end_s": round(t, 3),
                      "peak_dbfs": peak, "rms_dbfs": round(peak - db(np.sqrt(2)), 2)})
        t += 0.5
    parts += [label("End of test", tmp), silence(1.0)]
    meta = {"tone_hz": hz_list, "tone_s": tone_s, "gap_s": gap_s, "steps": steps, "tones": events}
    return np.concatenate(parts), meta


def pinpoint(tmp):
    order = PIN_HZ + PIN_HZ[::-1]
    parts, steps, events, t = [silence(2.0)], [], [], 2.0
    for i, hz in enumerate(order, 1):
        speech = label("%d hertz" % hz, tmp)
        at = speech.size + int(0.6 * FS)
        x = tone(hz, PIN_TONE_S, PIN_FADE_S) * 10 ** (PIN_PEAK_DBFS / 20)
        slot = np.zeros(int(PIN_EVERY_S * FS) if i < len(order) else at + x.size + int(PIN_TAIL_S * FS))
        slot[:speech.size] = speech
        slot[at:at + x.size] = x
        start = t + at / FS
        events.append({"t_s": round(start, 3), "end_s": round(start + PIN_TONE_S, 3), "hz": hz,
                       "peak_dbfs": PIN_PEAK_DBFS})
        steps.append({"step": i, "start_s": round(start, 3), "end_s": round(t + slot.size / FS, 3),
                      "peak_dbfs": PIN_PEAK_DBFS, "rms_dbfs": round(PIN_PEAK_DBFS - db(np.sqrt(2)), 2)})
        parts.append(slot)
        t += slot.size / FS
    parts += [label("End of test", tmp), silence(1.0)]
    meta = {"tone_hz": order, "tone_s": PIN_TONE_S, "every_s": PIN_EVERY_S, "steps": steps, "tones": events}
    return np.concatenate(parts), meta


def swept(f0, f1, tau, length_s, decay_s):
    """A cosine whose pitch falls from f0 to f1 with time constant tau, decaying from full amplitude."""
    t = np.arange(int(length_s * FS)) / FS
    phase = 2 * np.pi * (f1 * t + (f0 - f1) * tau * (1 - np.exp(-t / tau)))
    return np.cos(phase) * np.exp(-t / decay_s)


def kicks(tmp):
    kick = swept(150.0, 50.0, 0.03, 0.45, 0.25)
    bass = swept(60.0, 49.0, 0.03, 0.9, 0.6)
    tail = int(0.02 * FS)
    bass[-tail:] *= np.cos(np.linspace(0, np.pi / 2, tail)) ** 2
    combo = bass.copy()
    combo[:kick.size] += kick
    shapes = {"kick": kick / np.max(np.abs(kick)), "kick+808": combo / np.max(np.abs(combo))}
    pattern = [("kick", k * KICK_EVERY_S) for k in range(KICK_COUNT)]
    pattern += [("kick+808", KICK_COUNT * KICK_EVERY_S + 0.5 + k * COMBO_EVERY_S) for k in range(COMBO_COUNT)]
    span = int((pattern[-1][1] + COMBO_EVERY_S) * FS)
    parts, steps, events, t = [silence(2.0)], [], [], 2.0
    for i, peak in enumerate(KICK_PEAKS_DBFS, 1):
        speech = label("Level %d" % i, tmp)
        parts += [speech, silence(0.6)]
        t += (speech.size + int(0.6 * FS)) / FS
        block = np.zeros(span)
        for kind, at_s in pattern:
            at = int(round(at_s * FS))
            block[at:at + shapes[kind].size] += shapes[kind] * 10 ** (peak / 20)
            events.append({"t_s": round(t + at / FS, 3), "kind": kind, "peak_dbfs": peak})
        parts += [block, silence(1.0)]
        steps.append({"step": i, "start_s": round(t, 3), "end_s": round(t + span / FS, 3),
                      "peak_dbfs": peak, "rms_dbfs": None})
        t += span / FS + 1.0
    parts += [label("End of test", tmp), silence(1.0)]
    meta = {"kick": "150->50 Hz, tau 30 ms, decay 250 ms", "808": "60->49 Hz, decay 600 ms, 0.9 s",
            "steps": steps, "hits": events}
    return np.concatenate(parts), meta


def write(out_dir, name, y, meta):
    pcm = np.round(np.clip(y, -1, 32767 / 32768) * 32768).astype("<i2")
    with wave.open(os.path.join(out_dir, name + ".wav"), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(FS)
        w.writeframes(np.repeat(pcm, 2).tobytes())
    meta = {"file": name + ".wav", "rate": FS, "channels": 2, "bits": 16, "seed": SEED,
            "duration_s": round(y.size / FS, 3), **meta}
    with open(os.path.join(out_dir, name + ".json"), "w") as f:
        json.dump(meta, f, indent=2)
    print("%s.wav  %.1f s" % (os.path.join(out_dir, name), y.size / FS))
    for s in meta["steps"]:
        rms = "" if s["rms_dbfs"] is None else "  rms %6.2f dBFS" % s["rms_dbfs"]
        print("  step %d  %6.1f - %6.1f s  peak %4d dBFS%s" % (s["step"], s["start_s"], s["end_s"], s["peak_dbfs"], rms))


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    os.makedirs(out_dir, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        for name, band, order, step_s, hold_s in LADDERS:
            y, meta = ladder(band, order, step_s, hold_s, tmp)
            write(out_dir, name, y, meta)
        y, meta = bursts(tmp)
        write(out_dir, BURSTS_NAME, y, meta)
        for name, hz_list, tone_s, gap_s, fade_s in TONE_LADDERS:
            y, meta = tones(hz_list, tone_s, gap_s, fade_s, tmp)
            write(out_dir, name, y, meta)
        y, meta = pinpoint(tmp)
        write(out_dir, PIN_NAME, y, meta)
        y, meta = kicks(tmp)
        write(out_dir, KICKS_NAME, y, meta)


if __name__ == "__main__":
    main()
