"""Launches one throwaway container per execution and enforces its limits.

Every flag and every step of the control flow below was verified empirically on
Colima/macOS arm64 (Docker Engine 29.5.2, Ubuntu 24.04 kernel, cgroup v2). Where the
obvious implementation was measured to be silently wrong, the comment says so — those
are the parts most likely to be "simplified" back into being broken.

Isolation is infrastructure, not code: nothing in this module inspects or sanitizes the
candidate's source. It sets limits the kernel enforces and reports what happened.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import threading
import time
import uuid
from collections import deque
from typing import Any

from executor.protocol import ExecuteResponse, Outcome

SANDBOX_IMAGE = os.environ.get("EXECUTOR_IMAGE", "python:3.12-slim")
DEFAULT_WALL_MS = int(os.environ.get("EXECUTOR_WALL_MS", "5000"))
DEFAULT_MEMORY_MB = int(os.environ.get("EXECUTOR_MEMORY_MB", "256"))
PIDS_LIMIT = int(os.environ.get("EXECUTOR_PIDS_LIMIT", "64"))
CPUS = os.environ.get("EXECUTOR_CPUS", "0.5")

# Untrusted output is itself a denial-of-service vector: an unbounded stderr fills the
# caller's memory just as effectively as an allocation bomb inside the container.
MAX_OUTPUT_BYTES = 64 * 1024

# What the container is allowed to *produce*, as opposed to what is retained. The cap
# above bounded only the latter: `communicate()` accumulated the whole stream in this
# process first and truncated afterwards, when the memory had already been spent.
# Measured — 500 MB of container output cost ~1.7 GB peak RSS in the executor and still
# returned `outcome="ok"` with a tidy 64 KB detail. Worse, at high throughput it wedged
# the daemon's attach stream, so the wall-clock kill stopped working: a run declaring a
# 5 s wall took 30.4 s of real time and 2.9 GB, with `docker rm -f` blowing its own
# timeout. The container's `--memory` cap is irrelevant here because the memory is spent
# on the *host* side of the pipe.
#
# Generous relative to what is kept, because the point is to stop a bomb rather than to
# police a chatty program: a submission that prints a few MB is merely noisy.
MAX_STREAM_BYTES = 8 * 1024 * 1024

_LABEL = "interview-helper-executor"


def _docker_flags(name: str, memory_mb: int) -> list[str]:
    """The verified invocation. Each flag carries the measurement that justifies it."""
    memory = f"{memory_mb}m"
    return [
        "docker",
        "run",
        "-i",
        "--name",
        name,
        "--label",
        _LABEL,
        # Measured: only `lo`, zero routes. DNS, TCP connect and HTTP all fail with
        # "Network unreachable". socket(AF_INET) itself still SUCCEEDS — only connect
        # fails — so a test that merely opens a socket proves nothing.
        "--network",
        "none",
        # Blocks all writes. Does NOT block reads; see the /etc overlay below.
        "--read-only",
        # uid/gid/mode are load-bearing: --workdir pointed at a tmpfs silently flips it
        # from 1777 to 0755 root:root, and every execution then fails PermissionError on
        # its own scratch dir. noexec means code must be run as `python /scratch/x.py`,
        # never `./x.py` (which exits 126).
        "--tmpfs",
        "/scratch:rw,size=64m,noexec,nosuid,nodev,uid=65534,gid=65534,mode=0700",
        # --read-only leaves /etc readable. Overlaying it with an empty ro tmpfs is what
        # actually denies the reads SECURITY.md's test 2 requires. Python runs fine
        # without a passwd entry because --user is numeric.
        "--tmpfs",
        "/etc:ro,size=1m",
        "--user",
        "65534:65534",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        # Docker's DEFAULT seccomp profile is deliberately left in place rather than
        # replaced. A custom profile REPLACES the default rather than layering on it, so
        # the natural "defaultAction: ALLOW + a few denies" profile would be a net
        # WEAKENING: the default was measured blocking unshare(CLONE_NEWUSER), which
        # such a profile would re-permit. See docs/SECURITY.md for the ptrace gap this
        # leaves open and why closing it is deferred rather than faked.
        f"--pids-limit={PIDS_LIMIT}",
        # --memory alone grants an equal amount of SWAP on top, doubling the real limit.
        # Pinning memory-swap to the same value sets swap.max=0.
        f"--memory={memory}",
        f"--memory-swap={memory}",
        f"--cpus={CPUS}",
        "--workdir",
        "/scratch",
        SANDBOX_IMAGE,
        # Source arrives on stdin. Bind-mounting it instead is a trap: on Colima a bind
        # mount of a path outside the shared mounts silently produces an EMPTY DIRECTORY
        # with no error, so the container runs nothing while CI (real Linux) runs fine.
        "python",
        "-",
    ]


def _run(cmd: list[str], timeout: float = 15.0) -> subprocess.CompletedProcess[str]:
    """Run a docker CLI command. **Never raises**, whatever the daemon does.

    `run_sandboxed` promises the same thing, and this is where that promise was broken.
    Both `docker kill` (from inside the timeout handler) and `docker rm -f` (from the
    `finally`) hit their own timeouts under load and propagated `TimeoutExpired` — the
    second one also masking any result already computed. Measured: a chatty submission
    drove `docker rm -f` past 15 s on three consecutive trials, and the caller saw a 500.

    That matters more than a lost result. The API maps an executor 5xx to
    `ExecutorUnavailableError`, records "executor unavailable", and that path says nothing
    about the submission — so it was a reliable way for a candidate to turn a bad attempt
    into an infrastructure fault.
    """
    try:
        return subprocess.run(  # noqa: S603
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return subprocess.CompletedProcess(cmd, returncode=-1, stdout="", stderr=str(exc))


def _drain(stream: Any, sink: deque[bytes], budget: int) -> None:
    """Read to EOF, keeping only the last `budget` bytes.

    The **tail**, not the head, and that is a fix rather than a detail. The driver prints
    its result marker last and `parse_result` scans backwards for it, so retaining the
    first N bytes meant any submission whose own output exceeded the cap lost its grading
    entirely and came back `harness_error` — a candidate printing debug lines was scored
    as a harness failure.

    Reading continues to EOF rather than stopping early, so a program that is merely
    chatty still delivers its marker. What is bounded is memory, which is what was
    actually unbounded: nothing accumulates beyond `budget`, and the wall clock remains
    the bound on time.
    """
    held = 0
    try:
        while True:
            chunk = stream.read(65536)
            if not chunk:
                return
            sink.append(chunk)
            held += len(chunk)
            while held > budget and len(sink) > 1:
                held -= len(sink.popleft())
    except (OSError, ValueError):
        return
    finally:
        with contextlib.suppress(OSError, ValueError):
            stream.close()


class _BoundedReader:
    """Drains a process's pipes on threads, keeping only the tail of each.

    Replaces `communicate`, which has no bound: it returns the whole stream and any cap is
    applied after the memory has been spent. It also owns both pipes for the process's
    whole lifetime, so the timeout path reads from *this* rather than calling
    `communicate` a second time — doing that raised `ValueError: flush of closed file`,
    because stdin was already closed and these threads already held the pipes.
    """

    def __init__(self, proc: subprocess.Popen[bytes]) -> None:
        self._out: deque[bytes] = deque()
        self._err: deque[bytes] = deque()
        self._threads = [
            threading.Thread(target=_drain, args=(proc.stdout, self._out, MAX_STREAM_BYTES)),
            threading.Thread(target=_drain, args=(proc.stderr, self._err, MAX_STREAM_BYTES)),
        ]
        for thread in self._threads:
            thread.daemon = True
            thread.start()

    def send(self, proc: subprocess.Popen[bytes], payload: bytes) -> None:
        if proc.stdin is None:
            return
        with contextlib.suppress(OSError, ValueError):
            proc.stdin.write(payload)
            proc.stdin.close()

    def result(self) -> tuple[bytes, bytes]:
        for thread in self._threads:
            thread.join(timeout=2.0)
        return (
            b"".join(self._out)[-MAX_STREAM_BYTES:],
            b"".join(self._err)[-MAX_STREAM_BYTES:],
        )


def _inspect(name: str) -> tuple[int, bool]:
    """Exit code and whether the kernel OOM-killed it.

    Required because `docker kill` (wall-clock) and an OOM kill BOTH surface as exit
    137. `--rm` is deliberately not used anywhere in this module: it destroys the
    container before it can be inspected, making the two indistinguishable.
    """
    probe = _run(
        ["docker", "inspect", name, "--format", "{{.State.ExitCode}} {{.State.OOMKilled}}"]
    )
    if probe.returncode != 0:
        return -1, False
    parts = probe.stdout.strip().split()
    if len(parts) != 2:
        return -1, False
    try:
        return int(parts[0]), parts[1] == "true"
    except ValueError:
        return -1, False


def run_sandboxed(
    source: str, wall_ms: int | None = None, memory_mb: int | None = None
) -> ExecuteResponse:
    """Run `source` under every limit above. Never raises, never hangs.

    **This function is the swap point for Phase 6.** Fargate supports neither host bind
    mounts (`sourcePath` is EC2/Managed-Instances only) nor `devices`, so there is no
    Docker socket to reach and no sibling container to launch — there, the task *is* the
    isolation boundary and this Docker path is replaced wholesale rather than adapted.
    See docs/ARCHITECTURE.md, "Where the sandbox actually lives". Keep the signature
    backend-agnostic: source in, `ExecuteResponse` out, no Docker types leaking to callers.
    """
    wall_s = (wall_ms or DEFAULT_WALL_MS) / 1000.0
    name = f"exec-{uuid.uuid4().hex[:16]}"
    timed_out = False
    started = time.monotonic()

    # `replace`, not `surrogateescape`: the latter only round-trips the U+DC80-DCFF range,
    # so a lone `\ud800` — a well-formed JSON escape that reaches here as a `str` — still
    # raised. A mangled character makes the container report a syntax error, which is a
    # grading failure and the correct outcome. What it must not do is raise past this
    # function's "never raises" contract into a 500 the API reads as "executor
    # unavailable", a verdict that says nothing about the submission.
    encoded = source.encode("utf-8", "replace")

    try:
        proc = subprocess.Popen(  # noqa: S603
            _docker_flags(name, memory_mb or DEFAULT_MEMORY_MB),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            # Bytes, not `text=True`. Text mode encodes with the default handler, so a
            # source containing an unpaired surrogate — `"\ud800"` is a well-formed JSON
            # escape and reaches here as a `str` — raised `UnicodeEncodeError` out of
            # `communicate`, past this function's "never raises" contract, and became a
            # 500 that the API reads as "the executor is unavailable". That path says
            # nothing about the submission, so it was a reliable way for a candidate to
            # make their own grading disappear as an infrastructure fault.
        )
    except (OSError, ValueError) as exc:
        return ExecuteResponse(outcome="harness_error", detail=f"could not launch docker: {exc}")

    reader = _BoundedReader(proc)
    try:
        reader.send(proc, encoded)
        try:
            proc.wait(timeout=wall_s)
        except subprocess.TimeoutExpired:
            # THE critical step. Measured: subprocess's own timeout kills only the
            # docker CLI — the daemon keeps running the container, which then also
            # leaks because --rm never fires. A timeout test without this explicit kill
            # passes green while a runaway container burns CPU indefinitely.
            timed_out = True
            _run(["docker", "kill", name], timeout=10)  # measured 0.10s
            # `docker stop` is NOT acceptable here: measured 10.1s against a process
            # that ignores SIGTERM, which is a hang wearing a timeout's clothes.
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=10)
            if proc.poll() is None:
                proc.kill()  # last resort: the caller must never hang either
        raw_out, raw_err = reader.result()

        stdout = raw_out.decode("utf-8", "replace")
        stderr = raw_err.decode("utf-8", "replace")
        wall = int((time.monotonic() - started) * 1000)
        exit_code, oom_killed = _inspect(name)

        outcome: Outcome
        if timed_out:
            outcome = "timeout"
        elif oom_killed or exit_code == 137:
            # `OOMKilled` is the direct signal and the one to prefer. But it is reported by
            # the runtime, and whether it is set for a *child* process killed by the memory
            # cgroup depends on the cgroup version and the runtime — on GitHub's runners
            # this test intermittently came back `harness_error` with no detail at all,
            # which is the least useful answer possible.
            #
            # 137 is SIGKILL. This module sends exactly one `docker kill`, on the
            # wall-clock path, and that branch is above — so a 137 arriving here was not
            # killed by us, and the memory cap is the only other thing that kills a
            # container in this sandbox. Inferring OOM from it is sound rather than a
            # guess, and it fails in the safe direction: mislabelling some other hard kill
            # as OOM still refuses the submission.
            outcome = "out_of_memory"
        elif exit_code == 0:
            outcome = "ok"
        else:
            outcome = "harness_error"

        # The tail, for the same reason `_drain` keeps the tail: the result marker is the
        # last thing printed and `parse_result` scans backwards for it.
        detail = (stdout + stderr)[-MAX_OUTPUT_BYTES:]
        if outcome == "harness_error" and not detail.strip():
            # A `harness_error` with an empty detail is unactionable — it was reported by
            # CI with nothing to say what happened, and there was no way to tell an
            # inspect failure from a container that simply printed nothing. The exit code
            # is not sensitive and it is the whole diagnosis.
            detail = f"container exited {exit_code} with no output"

        return ExecuteResponse(outcome=outcome, wall_ms=wall, detail=detail)
    finally:
        # If the process dies between the kill and here, the container leaks; the
        # label above is what a reaper sweeps on.
        _run(["docker", "rm", "-f", name], timeout=15)


def reap_orphans() -> int:
    """Remove leaked containers. Belt-and-braces for the `finally` above."""
    listing = _run(["docker", "ps", "-aq", "--filter", f"label={_LABEL}"])
    ids = [i for i in listing.stdout.split() if i]
    if ids:
        _run(["docker", "rm", "-f", *ids], timeout=30)
    return len(ids)
