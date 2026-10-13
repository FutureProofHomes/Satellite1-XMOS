#!/usr/bin/env python3
"""Checks xsim output of test_speaker_eq.xe against a double-precision model."""

import cmath
import math
import sys

FS = 48000.0
CAP_DB = 18.0
BOOST_MAG2 = 1.0001

PEAK, LOW_SHELF, HIGH_SHELF, HP_Q, LP_Q = 1, 2, 3, 4, 5
HP_BW12, HP_BW24, HP_LR12, HP_LR24 = 6, 7, 8, 9
LP_BW12, LP_BW24, LP_LR12, LP_LR24 = 10, 11, 12, 13
Q_BW = 1 / math.sqrt(2)
Q_BW24 = (0.54119610, 1.30656296)


def rbj(kind, fc, q, gain_db=0.0):
    w0 = 2 * math.pi * fc / FS
    cw, sw = math.cos(w0), math.sin(w0)
    alpha = sw / (2 * q)
    a = 10 ** (gain_db / 40)
    k = 2 * math.sqrt(a) * alpha
    if kind == "lp":
        b = [(1 - cw) / 2, 1 - cw, (1 - cw) / 2]
        den = [1 + alpha, -2 * cw, 1 - alpha]
    elif kind == "hp":
        b = [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2]
        den = [1 + alpha, -2 * cw, 1 - alpha]
    elif kind == "peak":
        b = [1 + alpha * a, -2 * cw, 1 - alpha * a]
        den = [1 + alpha / a, -2 * cw, 1 - alpha / a]
    elif kind == "ls":
        b = [a * ((a + 1) - (a - 1) * cw + k), 2 * a * ((a - 1) - (a + 1) * cw),
             a * ((a + 1) - (a - 1) * cw - k)]
        den = [(a + 1) + (a - 1) * cw + k, -2 * ((a - 1) + (a + 1) * cw),
               (a + 1) + (a - 1) * cw - k]
    else:
        b = [a * ((a + 1) + (a - 1) * cw + k), -2 * a * ((a - 1) + (a + 1) * cw),
             a * ((a + 1) + (a - 1) * cw - k)]
        den = [(a + 1) - (a - 1) * cw + k, 2 * ((a - 1) - (a + 1) * cw),
               (a + 1) - (a - 1) * cw - k]
    return [b[0] / den[0], b[1] / den[0], b[2] / den[0], den[1] / den[0], den[2] / den[0]]


def design(f):
    t, enabled, fc, g, q = f
    if not enabled:
        return []
    if t in (PEAK, LOW_SHELF, HIGH_SHELF) and abs(g) < 0.01:
        return []
    table = {
        PEAK: [("peak", q, g)], LOW_SHELF: [("ls", q, g)], HIGH_SHELF: [("hs", q, g)],
        HP_Q: [("hp", q, 0)], LP_Q: [("lp", q, 0)],
        HP_BW12: [("hp", Q_BW, 0)], HP_LR12: [("hp", 0.5, 0)],
        HP_BW24: [("hp", Q_BW24[0], 0), ("hp", Q_BW24[1], 0)],
        HP_LR24: [("hp", Q_BW, 0), ("hp", Q_BW, 0)],
        LP_BW12: [("lp", Q_BW, 0)], LP_LR12: [("lp", 0.5, 0)],
        LP_BW24: [("lp", Q_BW24[0], 0), ("lp", Q_BW24[1], 0)],
        LP_LR24: [("lp", Q_BW, 0), ("lp", Q_BW, 0)],
    }
    return [rbj(kind, fc, qq, gg) for kind, qq, gg in table[t]]


def quantize(s):
    m = max(abs(x) for x in s[:3])
    lsh = 0
    while m >= 2.0 and lsh < 8:
        m /= 2
        lsh += 1
    sc = 2.0 ** (30 - lsh)
    return lsh, [round(s[0] * sc), round(s[1] * sc), round(s[2] * sc),
                 round(-s[3] * 2 ** 30), round(-s[4] * 2 ** 30)]


def from_fixed(lsh, c):
    sc = 2.0 ** (lsh - 30)
    return [c[0] * sc, c[1] * sc, c[2] * sc, -c[3] / 2 ** 30, -c[4] / 2 ** 30]


def mag2(s, hz):
    z = cmath.exp(-1j * 2 * math.pi * hz / FS)
    num = s[0] + s[1] * z + s[2] * z * z
    den = 1 + s[3] * z + s[4] * z * z
    return abs(num) ** 2 / max(abs(den) ** 2, 1e-30)


def db(m2):
    return 10 * math.log10(max(m2, 1e-30))


def grid(lo, hi, n):
    r = (hi / lo) ** (1 / (n - 1))
    return [lo * r ** i for i in range(n)]


DENSE = grid(10.0, 0.49 * FS, 4000)
AUDIBLE = grid(20.0, 20000.0, 1500)


def parse(path):
    cases, tones, misc = {}, [], []
    cur = None
    for line in open(path):
        w = line.split()
        if not w:
            continue
        if w[0] == "CASE":
            cur = {"name": w[1], "filters": [], "sections": []}
        elif w[0] == "PARAMS":
            cur["preamp"], cur["limiter"] = float(w[1]), float(w[2])
        elif w[0] == "FILTER":
            cur["filters"].append((int(w[1]), int(w[2]) & 1, float(w[3]), float(w[4]), float(w[5])))
        elif w[0] == "RESULT":
            cur["ok"], cur["max"], cur["peak"], cur["n"] = int(w[1]), float(w[2]), float(w[3]), int(w[4])
        elif w[0] == "BANK":
            cur["active"], cur["reason"], cur["lim"] = int(w[1]), int(w[2]), int(w[3])
            cur["pre"], cur["post"] = int(w[4]), int(w[5])
        elif w[0] == "SECTION":
            cur["sections"].append((int(w[1]), [int(x) for x in w[2:7]]))
        elif w[0] == "END":
            cases[cur["name"]] = cur
        elif w[0] == "TONE":
            tones.append((w[1], float(w[2]), float(w[3])))
        elif w[0] in ("FAIL", "DONE", "LIMIT", "GLIDE", "BENCH", "INFO"):
            misc.append(line.rstrip())
    return cases, tones, misc


errors = []


def err(msg):
    errors.append(msg)
    print("ERROR", msg)


def check_case(c):
    name = c["name"]
    ideal = [s for f in c["filters"] for s in design(f)]
    if not c["ok"]:
        return
    if len(ideal) != len(c["sections"]):
        err(f"{name}: {len(c['sections'])} sections, expected {len(ideal)}")
        return

    boosts = [max(mag2(s, f) for f in DENSE) > BOOST_MAG2 for s in ideal]
    order = [i for i, b in enumerate(boosts) if not b] + [i for i, b in enumerate(boosts) if b]
    worst_coeff = 0
    for pos, idx in enumerate(order):
        lsh, want = quantize(ideal[idx])
        got_lsh, got = c["sections"][pos]
        if got_lsh != lsh:
            err(f"{name}: section {pos} lsh {got_lsh}, expected {lsh}")
        worst_coeff = max(worst_coeff, max(abs(a - b) for a, b in zip(got, want)))
    tol = 2 ** 30 * 3e-6
    if worst_coeff > tol:
        err(f"{name}: coefficient error {worst_coeff} LSB > {tol:.0f}")

    pre_db, post_db = min(c["preamp"], 0.0), max(c["preamp"], 0.0)
    if abs(c["pre"] - 10 ** (pre_db / 20) * 2 ** 27) > 2 ** 27 * 1e-5:
        err(f"{name}: pre_gain {c['pre']}")
    if abs(c["post"] - 10 ** (post_db / 20) * 2 ** 27) > 2 ** 27 * 1e-5:
        err(f"{name}: post_gain {c['post']}")

    fixed = [from_fixed(l, s) for l, s in c["sections"]]
    gains2 = (c["pre"] / 2 ** 27) ** 2 * (c["post"] / 2 ** 27) ** 2
    # Gate B's 0.1 dB down to -6 dB. float32 rounds cos(w0) near 1, moving
    # 20-40 Hz cutoffs by up to ~1-2%, which shows on steep stopband skirts.
    resp_err = 0.0
    for f in AUDIBLE:
        want = db(math.prod(mag2(s, f) for s in ideal) * 10 ** (c["preamp"] / 10))
        if want < -60:
            continue
        got = db(math.prod(mag2(s, f) for s in fixed) * gains2)
        rel = want - c["preamp"]
        tol = 0.1 + 0.01 * max(0.0, -6.0 - rel)
        if abs(got - want) > tol:
            err(f"{name}: quantised response off by {abs(got - want):.4f} dB "
                f"at {f:.1f} Hz where the ideal level is {want:+.1f} dB")
            break
        if rel > -3.0:
            resp_err = max(resp_err, abs(got - want))

    net, worst = 0.0, 0.0
    for f in DENSE:
        level = (c["pre"] / 2 ** 27) ** 2
        worst = max(worst, level)
        for s in fixed:
            level *= mag2(s, f)
            worst = max(worst, level)
        level *= (c["post"] / 2 ** 27) ** 2
        worst, net = max(worst, level), max(net, level)
    if not (db(net) - 0.1 <= c["max"] <= db(net) + 0.01):
        err(f"{name}: max_gain {c['max']:.3f} vs model {db(net):.3f}")
    if not (db(worst) - 0.1 <= c["peak"] <= db(worst) + 0.01):
        err(f"{name}: peak_gain {c['peak']:.3f} vs model {db(worst):.3f}")
    if c["peak"] > CAP_DB:
        err(f"{name}: accepted above the headroom cap")
    if c["lim"] != int(c["max"] > c["limiter"] + 0.01):
        err(f"{name}: limiter_required {c['lim']} for max {c['max']:.3f}")
    print(f"ok   {name}: {len(fixed)} sections, max {c['max']:+.2f} dB, "
          f"peak {c['peak']:+.2f} dB, coeff err {worst_coeff} LSB, passband err {resp_err:.4f} dB")


def predicted(c, hz):
    fixed = [from_fixed(l, s) for l, s in c["sections"]]
    gains2 = (c["pre"] / 2 ** 27) ** 2 * (c["post"] / 2 ** 27) ** 2
    return db(math.prod(mag2(s, hz) for s in fixed) * gains2)


def main():
    cases, tones, misc = parse(sys.argv[1])
    for line in misc:
        print(line)
    for c in cases.values():
        check_case(c)
    for case, hz, got in tones:
        want = predicted(cases[case], hz)
        status = "ok  " if abs(got - want) <= 0.05 else "BAD "
        if status == "BAD ":
            err(f"tone {case} {hz} Hz measured {got:.3f} dB, model {want:.3f} dB")
        print(f"{status} tone {case} {hz:7.1f} Hz: measured {got:+8.3f} dB, model {want:+8.3f} dB")
    if not any(l.startswith("DONE failures=0") for l in misc):
        err("xsim run reported failures")
    print("PASS" if not errors else f"{len(errors)} ERRORS")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
