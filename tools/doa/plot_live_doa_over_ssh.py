#!/usr/bin/env python3

import argparse
import json
import math
import os
import re
import signal
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path
from collections import deque
from dataclasses import dataclass


DOA_RE = re.compile(r"doa_mrad\s*=\s*(-?\d+)")
SEQ_RE = re.compile(r"seq\s*=\s*(\d+)")
VALID_RE = re.compile(r"valid\s*=\s*(\d+)")
STREAM_MARKER = "sat1_doa_stream_marker_v1"


@dataclass
class DoaReading:
    doa_mrad: int
    seq: int
    valid: int

    @property
    def deg(self) -> float:
        return math.degrees(self.doa_mrad / 1000.0)


@dataclass
class ExpectedWindow:
    start_s: float
    end_s: float
    angle_deg: float


def host_default_from_env(repo_root: Path) -> str:
    host = os.getenv("SAT1_RPI_HOST", "").strip()
    if host:
        return host

    env_path = repo_root / ".env"
    if not env_path.is_file():
        return ""

    try:
        for line in env_path.read_text().splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            if k.strip() == "SAT1_RPI_HOST":
                return v.strip().strip('"').strip("'")
    except Exception:
        return ""

    return ""


def load_expected_windows(path: str | None) -> list[ExpectedWindow]:
    if not path:
        return []
    body = json.loads(Path(path).read_text())
    windows: list[ExpectedWindow] = []
    for row in body:
        windows.append(
            ExpectedWindow(
                start_s=float(row["start_s"]),
                end_s=float(row["end_s"]),
                angle_deg=float(row["angle_deg"]),
            )
        )
    return windows


def expected_angle_at(
    t_s: float,
    windows: list[ExpectedWindow],
    loop: bool,
) -> float | None:
    if not windows:
        return None

    t_eval = t_s
    if loop:
        total = max(w.end_s for w in windows)
        if total > 0:
            t_eval = t_s % total

    for w in windows:
        if w.start_s <= t_eval < w.end_s:
            return w.angle_deg
    return None


def wrap_deg(angle_deg: float) -> float:
    while angle_deg > 180.0:
        angle_deg -= 360.0
    while angle_deg < -180.0:
        angle_deg += 360.0
    return angle_deg


def run_ssh_cmd(
    host: str, remote_cmd: str, timeout: float
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", host, remote_cmd],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def readings_from_body(body: dict) -> tuple[DoaReading, DoaReading]:
    raw = DoaReading(
        doa_mrad=int(body["raw"]["doa_mrad"]),
        seq=int(body["raw"]["seq"]),
        valid=int(body["raw"]["valid"]),
    )
    smooth = DoaReading(
        doa_mrad=int(body["smooth"]["doa_mrad"]),
        seq=int(body["smooth"]["seq"]),
        valid=int(body["smooth"]["valid"]),
    )
    return raw, smooth


def parse_reading(text: str) -> DoaReading | None:
    doa_match = DOA_RE.search(text)
    seq_match = SEQ_RE.search(text)
    valid_match = VALID_RE.search(text)
    if not doa_match or not seq_match or not valid_match:
        return None
    return DoaReading(
        doa_mrad=int(doa_match.group(1)),
        seq=int(seq_match.group(1)),
        valid=int(valid_match.group(1)),
    )


def fetch_raw_smooth(
    host: str,
    sat1_cmd: str,
    board: str | None,
    timeout_s: float,
    ssh_mux: bool,
    ssh_control_path: str,
) -> tuple[DoaReading | None, DoaReading | None]:
    board_arg = ""
    if board:
        board_arg = f" --board {board}"

    remote_cmd = (
        f"{sat1_cmd} xmos{board_arg} get-doa --mode raw && "
        f"{sat1_cmd} xmos{board_arg} get-doa --mode smooth"
    )

    ssh_cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5"]
    if ssh_mux:
        ssh_cmd.extend(
            [
                "-o",
                "ControlMaster=auto",
                "-o",
                "ControlPersist=60",
                "-o",
                f"ControlPath={ssh_control_path}",
            ]
        )
    ssh_cmd.extend([host, remote_cmd])

    try:
        proc = subprocess.run(
            [
                *ssh_cmd,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return None, None

    if proc.returncode != 0:
        return None, None

    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if len(lines) < 2:
        return None, None

    raw = parse_reading(lines[0])
    smooth = parse_reading(lines[1])
    return raw, smooth


def fetch_raw_smooth_python(
    host: str,
    py_cmd: str,
    timeout_s: float,
    ssh_mux: bool,
    ssh_control_path: str,
) -> tuple[DoaReading | None, DoaReading | None]:
    script = (
        "import json;"
        "from satellite1.sat1_hat import XMOS;"
        "x=XMOS();x.setup();"
        "_ = x.read_firmware();"
        "_ = x.wait_until_ready(timeout_s=3.0,poll_interval_s=0.1);"
        "r=x.get_doa_raw();s=x.get_doa_smooth();"
        "print(json.dumps({'raw':{'doa_mrad':int(r.doa_mrad),'seq':int(r.seq),'valid':int(r.valid)},'smooth':{'doa_mrad':int(s.doa_mrad),'seq':int(s.seq),'valid':int(s.valid)}}));"
        "c=getattr(x,'_cntrl',None);"
        "c.close() if c is not None and hasattr(c,'close') else None"
    )
    cmd_tokens = shlex.split(py_cmd)
    if not cmd_tokens:
        return None, None

    remote_cmd = " ".join(shlex.quote(v) for v in cmd_tokens + ["-c", script])
    ssh_cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5"]
    if ssh_mux:
        ssh_cmd.extend(
            [
                "-o",
                "ControlMaster=auto",
                "-o",
                "ControlPersist=60",
                "-o",
                f"ControlPath={ssh_control_path}",
            ]
        )
    ssh_cmd.extend([host, remote_cmd])
    try:
        proc = subprocess.run(
            [*ssh_cmd],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return None, None

    if proc.returncode != 0:
        return None, None

    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if not lines:
        return None, None

    try:
        body = json.loads(lines[-1])
        return readings_from_body(body)
    except Exception:
        return None, None


class RemoteDoaStream:
    def __init__(
        self,
        *,
        host: str,
        py_cmd: str,
        period_s: float,
        ssh_mux: bool,
        ssh_control_path: str,
    ) -> None:
        self.host = host
        self.py_cmd = py_cmd
        self.period_s = max(0.05, period_s)
        self.ssh_mux = ssh_mux
        self.ssh_control_path = ssh_control_path
        self.proc: subprocess.Popen[str] | None = None
        self._latest: tuple[DoaReading, DoaReading] | None = None
        self._latest_monotonic: float = 0.0
        self._latest_lock = threading.Lock()
        self._stderr_tail: deque[str] = deque(maxlen=20)
        self._running = False

    def start(self) -> None:
        cmd_tokens = shlex.split(self.py_cmd)
        if not cmd_tokens:
            raise RuntimeError("--py-cmd resolved to empty command")

        script = f"""
import json
import signal
import time
from satellite1.sat1_hat import XMOS

MARKER = "{STREAM_MARKER}"

period = {self.period_s!r}
running = True

def _handle_stop(_sig, _frm):
    global running
    running = False

signal.signal(signal.SIGTERM, _handle_stop)
signal.signal(signal.SIGINT, _handle_stop)
signal.signal(signal.SIGHUP, _handle_stop)

def open_xmos():
    x = XMOS()
    x.setup()
    _ = x.read_firmware()
    _ = x.wait_until_ready(timeout_s=3.0, poll_interval_s=0.1)
    return x

x = open_xmos()

try:
    while running:
        try:
            r = x.get_doa_raw()
            s = x.get_doa_smooth()
            raw_mrad = int(r.doa_mrad)
            smooth_mrad = int(s.doa_mrad)

            if abs(raw_mrad) > 5000 or abs(smooth_mrad) > 5000:
                time.sleep(period)
                continue

            print(json.dumps({{
                'raw': {{
                    'doa_mrad': raw_mrad,
                    'seq': int(r.seq),
                    'valid': int(r.valid),
                }},
                'smooth': {{
                    'doa_mrad': smooth_mrad,
                    'seq': int(s.seq),
                    'valid': int(s.valid),
                }},
            }}), flush=True)
        except Exception:
            c = getattr(x, '_cntrl', None)
            if c is not None and hasattr(c, 'close'):
                try:
                    c.close()
                except Exception:
                    pass
            if not running:
                break
            time.sleep(period)
            x = open_xmos()
            continue
        time.sleep(period)
finally:
    c = getattr(x, '_cntrl', None)
    if c is not None and hasattr(c, 'close'):
        c.close()
"""
        remote_cmd = " ".join(shlex.quote(v) for v in cmd_tokens + ["-u", "-c", script])

        ssh_cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5"]
        if self.ssh_mux:
            ssh_cmd.extend(
                [
                    "-o",
                    "ControlMaster=auto",
                    "-o",
                    "ControlPersist=60",
                    "-o",
                    f"ControlPath={self.ssh_control_path}",
                ]
            )
        ssh_cmd.extend([self.host, remote_cmd])

        kill_prev_cmd = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=5",
            self.host,
            f"pkill -f {shlex.quote(STREAM_MARKER)} >/dev/null 2>&1 || true",
        ]
        subprocess.run(kill_prev_cmd, check=False, capture_output=True, text=True)

        self.proc = subprocess.Popen(
            ssh_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._running = True
        threading.Thread(target=self._stdout_loop, daemon=True).start()
        threading.Thread(target=self._stderr_loop, daemon=True).start()

    def _stdout_loop(self) -> None:
        assert self.proc is not None
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                body = json.loads(line)
                parsed = readings_from_body(body)
            except Exception:
                continue
            with self._latest_lock:
                self._latest = parsed
                self._latest_monotonic = time.monotonic()
        self._running = False

    def _stderr_loop(self) -> None:
        assert self.proc is not None
        assert self.proc.stderr is not None
        for line in self.proc.stderr:
            line = line.strip()
            if line:
                self._stderr_tail.append(line)

    def latest(self) -> tuple[DoaReading, DoaReading] | None:
        with self._latest_lock:
            return self._latest

    def latest_age_s(self) -> float:
        with self._latest_lock:
            if self._latest is None or self._latest_monotonic <= 0.0:
                return float("inf")
            return max(0.0, time.monotonic() - self._latest_monotonic)

    def is_running(self) -> bool:
        if self.proc is None:
            return False
        return self.proc.poll() is None and self._running

    def stderr_summary(self) -> str:
        if not self._stderr_tail:
            return ""
        return " | ".join(self._stderr_tail)

    def stop(self) -> None:
        if self.proc is None:
            return
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=2)
        self._running = False

        kill_prev_cmd = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=5",
            self.host,
            f"pkill -f {shlex.quote(STREAM_MARKER)} >/dev/null 2>&1 || true",
        ]
        subprocess.run(kill_prev_cmd, check=False, capture_output=True, text=True)

    def restart(self) -> None:
        self.stop()
        self._latest = None
        self._latest_monotonic = 0.0
        self._stderr_tail.clear()
        self.start()


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    default_host = host_default_from_env(repo_root)

    parser = argparse.ArgumentParser(
        description="Live DoA plot from remote sat1 CLI over SSH"
    )
    parser.add_argument(
        "--host",
        default=default_host,
        help="SSH host (default: SAT1_RPI_HOST from env/.env)",
    )
    parser.add_argument(
        "--sat1-cmd",
        default="sat1",
        help="Remote sat1 command (default: sat1)",
    )
    parser.add_argument(
        "--py-cmd",
        default="/opt/satellite1/venv/bin/python",
        help="Remote python command for fast mode (default: /opt/satellite1/venv/bin/python)",
    )
    parser.add_argument(
        "--source",
        choices=["stream", "python", "cli"],
        default="stream",
        help="Data source mode: stream is smoothest, python is single-shot, cli is simplest (default: stream)",
    )
    parser.add_argument(
        "--board",
        choices=["satellite1", "sq66"],
        default=None,
        help="Optional board override passed to sat1 xmos",
    )
    parser.add_argument(
        "--poll-s",
        type=float,
        default=0.2,
        help="Polling interval in seconds (default: 0.2)",
    )
    parser.add_argument(
        "--ssh-timeout-s",
        type=float,
        default=8.0,
        help="Per-poll SSH command timeout in seconds (default: 8)",
    )
    parser.add_argument(
        "--no-ssh-mux",
        action="store_true",
        help="Disable SSH connection multiplexing",
    )
    parser.add_argument(
        "--ssh-control-path",
        default="/tmp/plot_doa_mux_%r_%h_%p",
        help="SSH ControlPath template used when multiplexing is enabled",
    )
    parser.add_argument(
        "--expected-file",
        default=None,
        help="Optional JSON file with expected DoA windows: [{'start_s','end_s','angle_deg'}]",
    )
    parser.add_argument(
        "--expected-offset-deg",
        type=float,
        default=0.0,
        help="Optional expected-angle offset compensation in degrees (default: 0)",
    )
    parser.add_argument(
        "--expected-loop",
        action="store_true",
        help="Loop expected schedule over time",
    )
    parser.add_argument(
        "--no-force-live-mics",
        action="store_true",
        help="Do not force mic_source_mode=0 before plotting",
    )
    args = parser.parse_args()

    if not args.host:
        print(
            "error: --host is required (or set SAT1_RPI_HOST in env/.env)",
            file=sys.stderr,
        )
        return 2

    # Force live microphones (disable packaged injection) unless explicitly disabled.
    original_mic_source_mode: int | None = None
    if not args.no_force_live_mics:
        get_script = (
            "import json;"
            "from satellite1.sat1_hat import XMOS;"
            "x=XMOS();x.setup();"
            "_ = x.read_firmware();"
            "_ = x.wait_until_ready(timeout_s=3.0,poll_interval_s=0.1);"
            "s=x.get_mic_input_settings();"
            "print(json.dumps({'mic_source_mode':int(s.mic_source_mode)}));"
            "c=getattr(x,'_cntrl',None);"
            "c.close() if c is not None and hasattr(c,'close') else None"
        )
        get_cmd = " ".join(
            shlex.quote(v) for v in shlex.split(args.py_cmd) + ["-c", get_script]
        )
        res = run_ssh_cmd(args.host, get_cmd, timeout=args.ssh_timeout_s)
        if res.returncode != 0:
            print(res.stderr or res.stdout, file=sys.stderr)
            return 1
        lines = [ln.strip() for ln in res.stdout.splitlines() if ln.strip()]
        if lines:
            try:
                original_mic_source_mode = int(json.loads(lines[-1])["mic_source_mode"])
            except Exception:
                original_mic_source_mode = None

        set_live_script = (
            "from satellite1.sat1_hat import XMOS;"
            "x=XMOS();x.setup();"
            "_ = x.read_firmware();"
            "_ = x.wait_until_ready(timeout_s=3.0,poll_interval_s=0.1);"
            "_ = x.set_mic_input_source_modes(mic_source_mode=0);"
            "c=getattr(x,'_cntrl',None);"
            "c.close() if c is not None and hasattr(c,'close') else None"
        )
        set_live_cmd = " ".join(
            shlex.quote(v) for v in shlex.split(args.py_cmd) + ["-c", set_live_script]
        )
        res = run_ssh_cmd(args.host, set_live_cmd, timeout=args.ssh_timeout_s)
        if res.returncode != 0:
            print(res.stderr or res.stdout, file=sys.stderr)
            return 1

    expected_windows = load_expected_windows(args.expected_file)

    gui_cmd = [
        sys.executable,
        str(Path(__file__).resolve().parent / "plot_doa_gui_stream.py"),
    ]
    if args.expected_file:
        gui_cmd.extend(["--expected-file", str(args.expected_file)])

    gui_proc = subprocess.Popen(
        gui_cmd,
        stdin=subprocess.PIPE,
        text=True,
    )

    stream: RemoteDoaStream | None = None
    start_t = time.time()
    last_emitted_raw_seq: int | None = None
    last_emitted_smooth_seq: int | None = None

    try:
        if args.source == "stream":
            stream = RemoteDoaStream(
                host=args.host,
                py_cmd=args.py_cmd,
                period_s=args.poll_s,
                ssh_mux=not args.no_ssh_mux,
                ssh_control_path=args.ssh_control_path,
            )
            stream.start()

        while gui_proc.poll() is None:
            if args.source == "stream":
                assert stream is not None
                latest = stream.latest()
                if latest is None:
                    time.sleep(max(args.poll_s, 0.05))
                    continue
                raw, smooth = latest
            elif args.source == "python":
                raw, smooth = fetch_raw_smooth_python(
                    host=args.host,
                    py_cmd=args.py_cmd,
                    timeout_s=args.ssh_timeout_s,
                    ssh_mux=not args.no_ssh_mux,
                    ssh_control_path=args.ssh_control_path,
                )
            else:
                raw, smooth = fetch_raw_smooth(
                    host=args.host,
                    sat1_cmd=args.sat1_cmd,
                    board=args.board,
                    timeout_s=args.ssh_timeout_s,
                    ssh_mux=not args.no_ssh_mux,
                    ssh_control_path=args.ssh_control_path,
                )

            if raw is None or smooth is None or (not raw.valid) or (not smooth.valid):
                time.sleep(max(args.poll_s, 0.05))
                continue

            if args.source == "stream":
                if (
                    last_emitted_raw_seq == raw.seq
                    and last_emitted_smooth_seq == smooth.seq
                ):
                    time.sleep(max(args.poll_s, 0.05))
                    continue
                last_emitted_raw_seq = raw.seq
                last_emitted_smooth_seq = smooth.seq

            t_rel = time.time() - start_t
            expected_deg = expected_angle_at(
                t_rel, expected_windows, args.expected_loop
            )
            if expected_deg is not None:
                expected_deg = wrap_deg(expected_deg + args.expected_offset_deg)

            row = {
                "t_s": t_rel,
                "raw_deg": raw.deg,
                "smooth_deg": smooth.deg,
                "raw_seq": raw.seq,
                "smooth_seq": smooth.seq,
            }
            if expected_deg is not None:
                row["expected_deg"] = expected_deg

            if gui_proc.stdin is None:
                break
            try:
                gui_proc.stdin.write(json.dumps(row) + "\n")
                gui_proc.stdin.flush()
            except BrokenPipeError:
                break

            time.sleep(max(args.poll_s, 0.05))

    except KeyboardInterrupt:
        pass
    finally:
        if stream is not None:
            stream.stop()

        if gui_proc.stdin is not None:
            try:
                gui_proc.stdin.close()
            except Exception:
                pass
        if gui_proc.poll() is None:
            gui_proc.terminate()
            try:
                gui_proc.wait(timeout=3)
            except Exception:
                gui_proc.kill()

        if (not args.no_force_live_mics) and original_mic_source_mode is not None:
            restore_script = (
                "from satellite1.sat1_hat import XMOS;"
                "x=XMOS();x.setup();"
                "_ = x.read_firmware();"
                "_ = x.wait_until_ready(timeout_s=3.0,poll_interval_s=0.1);"
                f"_ = x.set_mic_input_source_modes(mic_source_mode={int(original_mic_source_mode)});"
                "c=getattr(x,'_cntrl',None);"
                "c.close() if c is not None and hasattr(c,'close') else None"
            )
            restore_cmd = " ".join(
                shlex.quote(v)
                for v in shlex.split(args.py_cmd) + ["-c", restore_script]
            )
            run_ssh_cmd(args.host, restore_cmd, timeout=args.ssh_timeout_s)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
