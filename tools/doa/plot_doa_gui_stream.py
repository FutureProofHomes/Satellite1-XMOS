#!/usr/bin/env python3

import argparse
import json
import math
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ExpectedWindow:
    start_s: float
    end_s: float
    angle_deg: float


def load_expected_windows(path: str | None) -> list[ExpectedWindow]:
    if not path:
        return []
    body = json.loads(Path(path).read_text())
    return [
        ExpectedWindow(
            start_s=float(row["start_s"]),
            end_s=float(row["end_s"]),
            angle_deg=float(row["angle_deg"]),
        )
        for row in body
    ]


def expected_angle_at(t_s: float, windows: list[ExpectedWindow]) -> float | None:
    for w in windows:
        if w.start_s <= t_s < w.end_s:
            return w.angle_deg
    return None


def wrap_deg(v: float) -> float:
    while v > 180.0:
        v -= 360.0
    while v < -180.0:
        v += 360.0
    return v


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Plot DoA GUI from JSONL samples on stdin"
    )
    parser.add_argument("--expected-file", default="", help="Expected schedule JSON")
    args = parser.parse_args()

    try:
        import matplotlib
        import matplotlib.pyplot as plt
        from matplotlib.animation import FuncAnimation
    except Exception as exc:
        raise SystemExit(f"error: matplotlib is required: {exc}")

    backend = matplotlib.get_backend().lower()
    if "agg" in backend:
        raise SystemExit(
            f"error: matplotlib backend '{matplotlib.get_backend()}' is non-interactive; GUI cannot be shown"
        )

    windows = load_expected_windows(args.expected_file or None)

    q: deque[dict] = deque()
    lock = threading.Lock()
    done = False

    t_vals: list[float] = []
    raw_vals: list[float] = []
    smooth_vals: list[float] = []
    exp_vals: list[float] = []

    def reader() -> None:
        nonlocal done
        try:
            import sys

            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                with lock:
                    q.append(row)
        finally:
            done = True

    th = threading.Thread(target=reader, daemon=True)
    th.start()

    fig = plt.figure(figsize=(10, 6))
    ax_polar = fig.add_subplot(211, projection="polar")
    ax_ts = fig.add_subplot(212)

    ax_polar.set_theta_zero_location("N")
    ax_polar.set_theta_direction(-1)
    ax_polar.set_ylim(0, 1.0)
    ax_polar.set_yticks([])
    ax_polar.set_title("Live DoA")

    (polar_raw_line,) = ax_polar.plot([], [], color="tab:red", linewidth=3, label="raw")
    (polar_smooth_line,) = ax_polar.plot(
        [], [], color="tab:blue", linewidth=3, label="smooth"
    )
    (polar_exp_line,) = ax_polar.plot(
        [], [], color="tab:green", linewidth=2, linestyle="--", label="expected"
    )
    ax_polar.legend(loc="center left", bbox_to_anchor=(1.02, 0.5), borderaxespad=0.0)

    (line_raw,) = ax_ts.plot([], [], label="raw", linewidth=1.0, color="tab:red")
    (line_smooth,) = ax_ts.plot([], [], label="smooth", linewidth=1.8, color="tab:blue")
    (line_exp,) = ax_ts.plot(
        [], [], label="expected", linewidth=1.2, linestyle="--", color="tab:green"
    )
    ax_ts.set_ylim(-190, 190)
    ax_ts.set_xlabel("time (s)")
    ax_ts.set_ylabel("angle (deg)")
    ax_ts.grid(alpha=0.3)
    ax_ts.legend(loc="upper right")

    def update(_frame: int):
        with lock:
            items = list(q)
            q.clear()
        for row in items:
            t = float(row.get("t_s", 0.0))
            raw_deg = wrap_deg(float(row.get("raw_deg", 0.0)))
            smooth_deg = wrap_deg(float(row.get("smooth_deg", 0.0)))
            exp_deg_in = row.get("expected_deg")
            if exp_deg_in is None:
                exp_deg = expected_angle_at(t, windows)
            else:
                exp_deg = wrap_deg(float(exp_deg_in))
            t_vals.append(t)
            raw_vals.append(raw_deg)
            smooth_vals.append(smooth_deg)
            exp_vals.append(float("nan") if exp_deg is None else exp_deg)

        if t_vals:
            line_raw.set_data(t_vals, raw_vals)
            line_smooth.set_data(t_vals, smooth_vals)
            line_exp.set_data(t_vals, exp_vals)
            xmin = max(0.0, t_vals[-1] - 20.0)
            xmax = max(5.0, t_vals[-1] + 1.0)
            ax_ts.set_xlim(xmin, xmax)

            raw_rad = math.radians(raw_vals[-1])
            smooth_rad = math.radians(smooth_vals[-1])
            polar_raw_line.set_data([raw_rad, raw_rad], [0, 1.0])
            polar_smooth_line.set_data([smooth_rad, smooth_rad], [0, 1.0])
            if math.isnan(exp_vals[-1]):
                polar_exp_line.set_data([], [])
            else:
                exp_rad = math.radians(exp_vals[-1])
                polar_exp_line.set_data([exp_rad, exp_rad], [0, 1.0])

            ax_ts.set_title(
                f"latest raw={raw_vals[-1]:.1f} deg | smooth={smooth_vals[-1]:.1f} deg"
            )

        if done and not t_vals:
            plt.close(fig)

        return (
            line_raw,
            line_smooth,
            line_exp,
            polar_raw_line,
            polar_smooth_line,
            polar_exp_line,
        )

    ani = FuncAnimation(fig, update, interval=200, blit=False, cache_frame_data=False)
    _ = ani
    plt.tight_layout()
    plt.show()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
