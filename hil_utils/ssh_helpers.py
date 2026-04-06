from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
import logging
import asyncssh
import asyncio

try:
    from typing import Self
except ImportError:
    # Python < 3.11 compatibility
    from typing_extensions import Self
from typing import Sequence
import shlex

logger = logging.getLogger(__file__)


@dataclass(frozen=True)
class CmdResult:
    exit_status: int
    stdout: str | bytes
    stderr: str | bytes


@dataclass
class ProcHandle:
    proc: asyncssh.SSHClientProcess
    encoding: str | None = None
    out_task: asyncio.Task | None = None
    err_task: asyncio.Task | None = None

    def _empty(self):
        return b"" if self.encoding is None else ""

    async def _gather_output(self, timeout: float | None = None):
        """Await std/err tasks (if present). Returns (stdout, stderr)."""
        stdout = self._empty()
        stderr = self._empty()
        try:
            if self.out_task:
                if timeout is None:
                    stdout = await asyncio.shield(self.out_task)
                else:
                    stdout = await asyncio.wait_for(
                        asyncio.shield(self.out_task), timeout
                    )
        except Exception:
            stdout = self._empty()
        try:
            if self.err_task:
                if timeout is None:
                    stderr = await asyncio.shield(self.err_task)
                else:
                    stderr = await asyncio.wait_for(
                        asyncio.shield(self.err_task), timeout
                    )
        except Exception:
            stderr = self._empty()

        # Clear references to avoid keeping tasks alive
        self.out_task = None
        self.err_task = None
        return stdout, stderr

    @property
    def pid(self) -> int | None:
        try:
            return self.proc.get_pid()
        except Exception:
            return None

    @property
    def running(self) -> bool:
        return (
            self.proc.exit_status is None
            and getattr(self.proc, "exit_signal", None) is None
        )

    async def wait(self) -> CmdResult:
        await self.proc.wait()
        stdout, stderr = await self._gather_output(timeout=None)
        return CmdResult(self.proc.exit_status, stdout=stdout, stderr=stderr)

    async def stop(self, gentle=True, timeout=3.0) -> CmdResult:
        if not self.running:
            stdout, stderr = await self._gather_output(timeout=0.0)
            return CmdResult(self.proc.exit_status, stdout, stderr)

        try:
            self.proc.stdin.write_eof()
        except Exception:
            pass

        try:
            if gentle:
                self.proc.terminate()
            else:
                self.proc.kill()
            await asyncio.wait_for(self.proc.wait(), timeout)
        except asyncio.TimeoutError:
            self.proc.kill()
            await self.proc.wait()

        stdout, stderr = await self._gather_output(timeout=0.5)
        return CmdResult(self.proc.exit_status, stderr=stderr, stdout=stdout)


@dataclass
class SSHSession:
    conn: asyncssh.SSHClientConnection

    @classmethod
    async def connect(cls, host: str, *, username: str | None = "pi", **kwargs):
        return cls(await asyncssh.connect(host, username=username, **kwargs))

    async def close(self):
        self.conn.close()
        try:
            await self.conn.wait_closed()
        except Exception:
            pass

    async def _create_process(
        self, cmd: str | Sequence[str], *, text: bool = True, env: dict | None = None
    ) -> ProcHandle:
        if isinstance(cmd, (list, tuple)):
            cmd = shlex.join(map(str, cmd))

        encoding = "utf-8" if text else None
        proc = await self.conn.create_process(cmd, encoding=encoding, env=env)
        out_task = asyncio.create_task(proc.stdout.read())
        err_task = asyncio.create_task(proc.stderr.read())
        return ProcHandle(proc, encoding=encoding, err_task=err_task, out_task=out_task)

    async def run(
        self,
        cmd: str | Sequence[str],
        *,
        text: bool = True,
        check: bool = True,
        timeout: float | None = None,
        kill_on_timeout: bool = True,
        env: dict | None = None,
    ) -> CmdResult:
        proc = await self._create_process(cmd, text=text, env=env)
        ret: CmdResult | None = None
        try:
            if timeout is None:
                ret = await proc.wait()
            else:
                ret = await asyncio.wait_for(proc.wait(), timeout)

        except asyncio.TimeoutError as te:
            grace = 0.5 if kill_on_timeout else 3.0
            ret = await proc.stop(gentle=True, timeout=grace)

        except asyncio.CancelledError:
            ret = await proc.stop()
            raise

        finally:
            if (
                check
                and ret is not None
                and (ret.exit_status is None or ret.exit_status != 0)
            ):
                raise RuntimeError(f"Command failed ({ret.exit_status}): {cmd}")
        return ret

    async def sftp_put(self, local: Path, remote: str, preserve: bool = True):
        async with self.conn.start_sftp_client() as sftp:
            await sftp.put(str(local), remote, preserve=preserve)

    async def sftp_put_atomic(self, local: Path, remote: str, *, preserve: bool = True):
        tmp = remote + ".part"
        async with self.conn.start_sftp_client() as sftp:
            await sftp.put(str(local), tmp, preserve=preserve)
            await sftp.rename(tmp, remote)

    async def sftp_get(self, remote: str, local: Path, preserve: bool = True):
        async with self.conn.start_sftp_client() as sftp:
            await sftp.get(remote, str(local), preserve=preserve)

    async def sftp_remove(self, remote_path: str) -> None:
        rpath = await self.expand(remote_path)
        async with self.conn.start_sftp_client() as sftp:
            try:
                await sftp.remove(rpath)
            except Exception:
                # ignore if missing or not a file
                pass

    async def expand(self, path: str) -> str:
        if path.startswith("~"):
            home = (await self.run('printf %s "$HOME"')).stdout.strip()
            return (PurePosixPath(home) / path[2:]).as_posix() if path != "~" else home
        return path

    async def sftp_ensure_dir(self, path: str):
        """Ensure the parent directory of `path` exists on the remote."""
        rpath = await self.expand(path)
        parent = PurePosixPath(rpath).parent
        parts = parent.parts
        cur = PurePosixPath("/" if parent.is_absolute() else ".")
        async with self.conn.start_sftp_client() as sftp:
            for part in parts:
                cur = cur / part
                try:
                    await sftp.stat(cur.as_posix())
                except Exception:
                    try:
                        await sftp.mkdir(cur.as_posix())
                    except Exception:
                        pass  # already exists / race


@dataclass
class RecordingTask:
    sess: SSHSession
    remote_path: str = ("~/tmp_rec.wav",)
    num_channels: int = 2
    rate_hz: int = 48000
    fmt: str = "S32_LE"
    arecord_args: Sequence[str] = field(default_factory=tuple)
    handle: ProcHandle | None = None

    async def start(self):
        rpath = await self.sess.expand(self.remote_path)
        args = " ".join(shlex.quote(a) for a in self.arecord_args)
        cmd = f"arecord -q -c {self.num_channels} -r {self.rate_hz} -f {self.fmt} {args} {shlex.quote(rpath)}"
        proc = await self.sess.conn.create_process(cmd)
        self.handle = ProcHandle(proc)

    async def stop(self):
        if self.handle:
            await self.handle.stop(gentle=True)

    async def download(self, to: Path):
        await self.sess.sftp_get(await self.sess.expand(self.remote_path), to)

    async def cleanup(self):
        await self.sess.sftp_remove(self.remote_path)


@dataclass
class PlayingTask:
    sess: SSHSession
    handle: ProcHandle | None = None
    remote_path: str = "~/tmp_play.wav"
    _uploaded_here: bool = field(default=False, init=False, repr=False)  # we created it
    _delete_on_cleanup: bool = field(default=False, init=False, repr=False)
    _pump_task: asyncio.Task | None = field(default=None, init=False, repr=False)

    async def upload(
        self,
        local_path: Path,
        *,
        remote_path: str | None = None,
        ensure_dir: bool = True,
        preserve_times: bool = True,
        delete_on_cleanup: bool = True,
    ) -> str:
        """
        Upload a file to the remote host.
        Returns the resolved remote path and sets `current_remote_path`.
        """
        rpath = await self.sess.expand(remote_path or self.remote_path)
        if ensure_dir:
            await self.sess.sftp_ensure_dir(rpath)

        await self.sess.sftp_put_atomic(local_path, rpath, preserve=preserve_times)
        self.remote_path = rpath
        self._uploaded_here = True
        self._delete_on_cleanup = delete_on_cleanup
        return rpath

    async def start_file(
        self,
        *,
        remote_path: str | None = None,
        num_channels: int = 2,
        aplay_args: Sequence[str] = (),
        quiet: bool = True,
    ) -> None:
        """
        Play an already-present remote file (default: last `upload()` target).
        """
        if self.handle and self.handle.running:
            raise RuntimeError("A play process is already running.")

        rpath = await self.sess.expand(remote_path or self.remote_path or "")
        if not rpath:
            raise RuntimeError("No remote_path provided and nothing uploaded yet.")

        args = " ".join(shlex.quote(str(a)) for a in aplay_args)
        quiet_flag = "-q " if quiet else ""
        cmd = f"aplay {quiet_flag}-c {num_channels} {args} {shlex.quote(rpath)}"

        proc = await self.sess.conn.create_process(
            cmd, encoding=None
        )  # binary I/O is fine
        self.handle = ProcHandle(proc)

    async def start_stream(
        self,
        local_path: Path,
        *,
        num_channels: int = 2,
        aplay_args: Sequence[str] = (),
        quiet: bool = True,
        chunk_size: int = 64_000,
        force_type: str | None = None,  # e.g. 'wav' or 'raw'
    ) -> None:
        """
        Stream a local file to remote `aplay` via stdin.

        For WAV, `aplay` will detect the format. For RAW PCM, set `force_type='raw'`
        and include necessary flags in `aplay_args` (e.g., -f S16_LE -r 16000).
        """
        if self.handle and self.handle.running:
            raise RuntimeError("A play process is already running.")
        if not local_path.exists():
            raise FileNotFoundError(local_path)

        args = " ".join(shlex.quote(str(a)) for a in aplay_args)
        quiet_flag = "-q " if quiet else ""
        type_flag = f"-t {shlex.quote(force_type)} " if force_type else ""
        cmd = f"aplay {quiet_flag}-c {num_channels} {type_flag}{args} -"

        # Start remote aplay that reads from stdin (binary)
        proc = await self.sess.conn.create_process(cmd, encoding=None)
        self.handle = ProcHandle(proc)

        async def _pump():
            try:
                with open(local_path, "rb") as f:
                    while True:
                        data = await asyncio.to_thread(f.read, chunk_size)
                        if not data:
                            break
                        proc.stdin.write(data)
                        await proc.stdin.drain()
                # signal EOF so aplay can exit
                try:
                    proc.stdin.write_eof()
                except Exception:
                    pass
            except asyncio.CancelledError:
                # Try to close stdin so remote can terminate gracefully
                try:
                    proc.stdin.write_eof()
                except Exception:
                    pass
                raise
            except (BrokenPipeError, OSError):
                # Remote exited early — ignore; caller can inspect status
                pass

        self._pump_task = asyncio.create_task(_pump())

    async def stop(self, *, gentle: bool = True, timeout: float = 3.0):
        """
        Stop playback. If streaming, cancels the pump and closes stdin first,
        then sends SIGTERM (or SIGKILL fallback).
        """
        if self._pump_task and not self._pump_task.done():
            self._pump_task.cancel()
            try:
                await self._pump_task
            except Exception:
                pass
            self._pump_task = None

        if self.handle:
            # Close stdin to nudge remote aplay to exit if still waiting
            try:
                self.handle.proc.stdin.write_eof()
            except Exception:
                pass
            await self.handle.stop(gentle=gentle, timeout=timeout)

    async def wait(self) -> int:
        """Wait for current playback to finish; returns remote exit status."""
        if not self.handle:
            raise RuntimeError("No active playback process.")
        return await self.handle.wait()

    async def cleanup(self) -> None:
        """
        Stop playback if running and (optionally) remove the uploaded file.
        Only deletes if this task performed the upload AND delete_on_cleanup=True.
        """
        # ensure process is not running
        if self._pump_task and not self._pump_task.done():
            self._pump_task.cancel()
            try:
                await self._pump_task
            except Exception:
                pass
            self._pump_task = None
        if self.handle and self.handle.running:
            await self.stop()

        # delete the file if we uploaded it and caller opted in
        if self._uploaded_here and self._delete_on_cleanup and self.remote_path:
            await self.sess.sftp_remove(self.remote_path)

        # clear state
        self.remote_path = None
        self._uploaded_here = False
        self._delete_on_cleanup = False
        self.handle = None


@dataclass
class RemoteAudioSession:
    """
    Reusable SSH session for remote aplay/arecord.

    - Create it with `await RemoteAudioSession.connect(host, username=...)`
    - Optionally `await sess.upload(local, remote)` once and reuse the remote path
    - Start a process: `await sess.start_play(remote_path, ...)` or `await sess.start_record(remote_path, ...)`
    - Control it: `sess.is_running`, `await sess.stop()`, `await sess.wait()`
    - Fetch recorded file: `await sess.download(remote_path, local_out)`
    - Clean up: `await sess.close()`  (or use as an async context manager)
    """

    conn: asyncssh.SSHClientConnection
    proc: asyncssh.SSHClientProcess | None = field(default=None, init=False)
    mode: str | None = field(default=None, init=False)  # 'play' | 'record' | None
    current_remote_path: str | None = field(default=None, init=False)

    _closed: bool = field(default=False, init=False, repr=False)
    _bg_cmds: set[asyncio.Task] = field(default_factory=set, init=False, repr=False)
    _stream_task: asyncio.Task | None = field(default=None, init=False, repr=False)

    # ---------- lifecycle ----------

    @classmethod
    async def connect(cls, host: str, *, username: str | None = "pi", **kwargs) -> Self:
        """
        Open an SSH connection you can reuse for multiple plays/records/uploads.
        kwargs are passed to asyncssh.connect (e.g., client_keys=..., known_hosts=...).
        """
        conn = await asyncssh.connect(host, username=username, **kwargs)
        return cls(conn=conn)

    async def close(self) -> None:
        """Close the SSH connection (does not implicitly stop a running process)."""
        if not self._closed:
            self.conn.close()
            try:
                await self.conn.wait_closed()
            except Exception:
                pass
            self._closed = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    # ---------- utilities ----------

    async def upload(
        self,
        local_path: Path,
        *,
        remote_path: str = "~/tmp_play.wav",
        atomic: bool = True,
        ensure_dir: bool = True,
        preserve_times: bool = True,
    ) -> None:
        """
        Upload a file to the remote host via SFTP using the existing SSH connection.
        If `atomic`, uploads to `<remote>.part` then renames to avoid partial reads.
        """
        rpath = await self._resolve_remote_path(remote_path)
        if ensure_dir:
            await self._sftp_ensure_dir(rpath)

        async with self.conn.start_sftp_client() as sftp:
            if atomic:
                tmp = rpath + ".part"
                await sftp.put(str(local_path), tmp, preserve=preserve_times)
                await sftp.rename(tmp, rpath)
            else:
                await sftp.put(str(local_path), rpath, preserve=preserve_times)
            self.current_remote_path = rpath

    async def download(
        self,
        local_path: Path,
        *,
        remote_path: str | None = None,
        preserve_times: bool = True,
    ) -> None:
        """
        Download a remote file to `local_path`. For recordings, you can pass None to
        use `self.current_remote_path` (the last path used by start_record()).
        """
        rpath = await self._resolve_remote_path(remote_path or self.current_remote_path)
        if not rpath:
            raise RuntimeError(
                "No remote_path specified and no active/previous record path."
            )
        async with self.conn.start_sftp_client() as sftp:
            await sftp.get(rpath, str(local_path), preserve=preserve_times)

    async def cleanup(self) -> None:
        # Don’t delete while something may still be writing
        if self.is_running:
            raise RuntimeError("Process still running; stop()/wait() before cleanup.")

        target = self.current_remote_path
        if not target:
            raise RuntimeError("No remote path to clean up.")

        # Resolve ~ to absolute once
        rpath = await self._resolve_remote_path(target)

        # Use SFTP to avoid shell quoting problems
        async with self.conn.start_sftp_client() as sftp:
            # If it’s missing, ignore
            try:
                await sftp.stat(rpath)
            except Exception:
                return

            # Remove the file (will error if it's a dir)
            await sftp.remove(rpath)

        # Clear the session’s pointer if we just deleted it
        self.current_remote_path = None

    async def cmd(
        self,
        cmd: str | Sequence[str | Path],
        *,
        check: bool = True,
        timeout: float | None = None,
        env: dict | None = None,
        text: bool = True,  # True -> str output; False -> bytes
        kill_on_timeout: bool = True,  # attempt to stop remote proc if timed out
        background: bool = False,
    ) -> CmdResult:
        """
        Run a generic command on the remote host and wait for completion.

        - If `cmd` is a *string*, it's executed by the remote shell.
        - If `cmd` is a *sequence*, it is joined with POSIX-safe quoting.
        - If `timeout` is set and `kill_on_timeout` is True, the remote process
          is terminated on timeout (SIGTERM -> SIGKILL).
        - Returns stdout/stderr as text (UTF-8) by default; set `text=False` for bytes.
        """
        # Build a shell command string
        if isinstance(cmd, (list, tuple)):
            # Convert Paths to strings and quote each arg safely
            parts = [str(c) for c in cmd]
            cmd_str = shlex.join(parts)
        else:
            cmd_str = cmd

        encoding = "utf-8" if text else None

        async def _run_proc_with_timeout() -> CmdResult:
            proc = await self.conn.create_process(
                cmd_str,
                env=env,
                encoding=encoding,
            )

            # Read stdout/stderr concurrently
            out_task = asyncio.create_task(proc.stdout.read())
            err_task = asyncio.create_task(proc.stderr.read())

            async def _finalize() -> CmdResult:
                stdout = await out_task
                stderr = await err_task
                if check and proc.exit_status != 0:
                    raise RuntimeError(
                        f"Remote command failed ({proc.exit_status}): {cmd_str}\nSTDERR:\n{stderr}"
                    )
                return CmdResult(proc.exit_status, stdout, stderr)

            try:
                if timeout is None:
                    await proc.wait()
                    return await _finalize()
                else:
                    await asyncio.wait_for(proc.wait(), timeout)
                    return await _finalize()

            except asyncio.TimeoutError as te:
                if kill_on_timeout:
                    try:
                        proc.terminate()
                        await asyncio.wait_for(proc.wait(), 2.0)
                    except asyncio.TimeoutError:
                        proc.kill()
                        await proc.wait()

                # gather partial output best-effort
                try:
                    stdout = await asyncio.wait_for(out_task, 0.5)
                except Exception:
                    stdout = b"" if not text else ""
                try:
                    stderr = await asyncio.wait_for(err_task, 0.5)
                except Exception:
                    stderr = b"" if not text else ""
                raise TimeoutError(f"Remote command timed out: {cmd_str}") from te

            except asyncio.CancelledError:
                # If caller cancels the Task, try to stop the remote proc too.
                try:
                    proc.terminate()
                    await asyncio.wait_for(proc.wait(), 2.0)
                except Exception:
                    try:
                        proc.kill()
                        await proc.wait()
                    except Exception:
                        pass
                raise

        if background:
            task: asyncio.Task[CmdResult] = asyncio.create_task(
                _run_proc_with_timeout()
            )
            self._bg_cmds.add(task)
            task.add_done_callback(lambda t: self._bg_cmds.discard(t))
            return task

        return await _run_proc_with_timeout()

    # ---------- process control ----------

    @property
    def is_running(self) -> bool:
        return self.proc is not None and self.proc.exit_status is None

    async def wait(self) -> int:
        """Wait for the current process to exit; returns the remote exit status."""
        if not self.proc:
            raise RuntimeError("No process has been started.")
        status = await self.proc.wait()
        return status

    async def stop(self, *, gentle: bool = True, timeout: float = 3.0) -> None:
        """
        Stop the running process.
        - For 'record': SIGINT (gentle=True) to finalize WAV headers.
        - For 'play':   SIGTERM (gentle=True).
        Falls back to SIGKILL on timeout.
        """
        if not self.is_running:
            return
        try:
            if gentle:
                try:
                    if self.mode == "record":
                        self.proc.send_signal("INT")  # SIGINT
                    else:
                        self.proc.terminate()  # SIGTERM
                except Exception:
                    # Fallback if signals not supported by transport
                    self.proc.terminate()
            else:
                self.proc.kill()  # SIGKILL

            try:
                await asyncio.wait_for(self.proc.wait(), timeout)
            except asyncio.TimeoutError:
                self.proc.kill()
                await self.proc.wait()
        finally:
            # Do not clear self.proc to keep exit_status inspectable.
            pass

    # ---------- start commands ----------

    async def start_play(
        self,
        *,
        remote_path: str | None = None,
        num_channels: int = 2,
        aplay_args: Sequence[str] = (),
        quiet: bool = True,
    ) -> None:
        """Start a remote 'aplay' on a pre-existing file at `remote_path`."""
        self._ensure_idle()
        rpath = await self._resolve_remote_path(remote_path or self.current_remote_path)

        args = " ".join(shlex.quote(a) for a in aplay_args)
        quiet_flag = "-q " if quiet else ""
        cmd = f"aplay {quiet_flag}-c {num_channels} {args} {shlex.quote(rpath)}"
        logger.info(f"[aplay] $ {cmd}")
        self.proc = await self.conn.create_process(cmd)
        self.mode = "play"
        self.current_remote_path = rpath

    async def start_play_stream(
        self,
        local_path: Path,
        *,
        num_channels: int = 2,
        aplay_args: Sequence[str] = (),
        quiet: bool = True,
        chunk_size: int = 64_000,
        force_type: str | None = None,  # e.g. 'wav', 'raw' (for raw PCM add more args!)
    ) -> None:
        """
        Stream a local file to remote aplay via stdin.

        - If the file is WAV, aplay will detect the format; you may set force_type='wav'.
        - For RAW PCM, set force_type='raw' and include the necessary args in aplay_args
          (e.g., ['-t','raw','-f','S16_LE','-r','16000']).
        """
        self._ensure_idle()
        if not local_path.exists():
            raise FileNotFoundError(local_path)

        args = " ".join(shlex.quote(a) for a in aplay_args)
        quiet_flag = "-q " if quiet else ""
        type_flag = f"-t {shlex.quote(force_type)} " if force_type else ""
        cmd = f"aplay {quiet_flag}-c {num_channels} {type_flag}{args} -"
        logger.info(f"[aplay|stream] $ {cmd}")
        self.proc = await self.conn.create_process(cmd, encoding=None)
        self.mode = "play_stream"
        self.current_remote_path = None

        async def _pump():
            try:
                # blocking file I/O offloaded to thread to avoid blocking the loop
                with open(local_path, "rb") as f:
                    while True:
                        data = await asyncio.to_thread(f.read, chunk_size)
                        if not data:
                            break
                        self.proc.stdin.write(data)
                        await self.proc.stdin.drain()
                try:
                    self.proc.stdin.write_eof()
                except Exception:
                    pass
            except asyncio.CancelledError:
                # stop() cancels this; try to close stdin so remote can exit
                try:
                    self.proc.stdin.write_eof()
                except Exception:
                    pass
                raise
            except (BrokenPipeError, OSError) as e:
                logger.debug(f"Stream pump ended early: {e}")
            except Exception as e:
                logger.exception("Stream pump failed.")

        self._stream_task = asyncio.create_task(_pump())

    async def start_record(
        self,
        *,
        remote_path: str = "~/tmp_rec.wav",
        num_channels: int = 2,
        rate_hz: int = 48000,
        fmt: str = "S32_LE",
        arecord_args: Sequence[str] = (),
        quiet: bool = True,
        ensure_dir: bool = True,
    ) -> None:
        """Start a remote 'arecord' writing to `remote_path` (WAV)."""
        self._ensure_idle()
        rpath = await self._resolve_remote_path(remote_path)
        if ensure_dir:
            await self._sftp_ensure_dir(rpath)

        args = " ".join(shlex.quote(a) for a in arecord_args)
        quiet_flag = "-q " if quiet else ""
        cmd = (
            f"arecord {quiet_flag}-c {num_channels} -r {rate_hz} -f {fmt} "
            f"{args} {shlex.quote(rpath)}"
        )
        logger.info(f"[arecord] $ {cmd}")
        self.proc = await self.conn.create_process(cmd)
        self.mode = "record"
        self.current_remote_path = rpath

    # ---------- internals ----------

    async def _run(
        self, cmd: str, *, check: bool = True
    ) -> asyncssh.SSHCompletedProcess:
        logger.debug(f"[remote] {cmd}")
        return await self.conn.run(cmd, check=check)

    def _ensure_idle(self) -> None:
        if self.is_running:
            raise RuntimeError("A remote process is already running on this session.")

    async def _resolve_remote_path(self, path: str) -> str:
        if path.startswith("~"):
            # Ask the remote for its $HOME once
            home = (await self._run('printf %s "$HOME"', check=True)).stdout.strip()
            if path == "~":
                return home
            if path.startswith("~/"):
                return str(PurePosixPath(home) / path[2:])
        return path  # absolute or relative as-is

    async def _sftp_ensure_dir(self, path: str) -> None:
        path = await self._resolve_remote_path(path)
        p = PurePosixPath(path).parent
        parts = p.parts
        cur = PurePosixPath("/" if p.is_absolute() else ".")
        async with self.conn.start_sftp_client() as sftp:
            for part in parts:
                cur = cur / part
                try:
                    await sftp.stat(cur.as_posix())
                except Exception:
                    try:
                        await sftp.mkdir(cur.as_posix())
                    except Exception:
                        # If it already exists or race: ignore
                        pass
