"""The escape tests from docs/SECURITY.md. Every one must fail closed: the attempt
fails, the service survives, and the failure is reported rather than crashing.

Marked `sandbox` — excluded from the default run, executed by `make test-sandbox` and
in CI. They need a working Docker daemon and the sandbox image.

Two rules these tests are written to respect, both learned by measurement:

- **Never infer success from exit 0 alone.** A recursive fork bomb was measured exiting
  0 with empty output, because PID 1 backgrounded its children and returned. Assert on
  observed output, not just the return code.
- **Never expect the sandboxed process to report why it died.** At the PID cap it cannot
  fork enough to print, and an OOM kill gives it no chance. The evidence comes from
  outside the container.
"""

from __future__ import annotations

import subprocess

import pytest

from executor.sandbox import run_sandboxed

pytestmark = pytest.mark.sandbox


def _docker_alive() -> bool:
    """The service surviving is half of every 'fail closed' requirement."""
    probe = subprocess.run(
        ["docker", "version", "--format", "{{.Server.Version}}"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return probe.returncode == 0


def test_sanity_a_normal_program_runs():
    """A control. If this fails, the other tests prove nothing — they would all
    'pass' against a sandbox that simply cannot run anything at all."""
    result = run_sandboxed("print('hello from the sandbox')")
    assert result.outcome == "ok", result.detail
    assert "hello from the sandbox" in result.detail


def test_no_network_egress():
    """DNS, a raw TCP connect, and an HTTP GET must all fail.

    Note it attempts a CONNECT, not merely socket() — an AF_INET socket is still
    created successfully under `--network none`; only reaching anything fails.
    """
    result = run_sandboxed(
        "import socket\n"
        "for label, fn in (\n"
        "    ('dns', lambda: socket.gethostbyname('example.com')),\n"
        "    ('tcp', lambda: socket.create_connection(('1.1.1.1', 80), timeout=3)),\n"
        "):\n"
        "    try:\n"
        "        fn()\n"
        "        print(f'{label}:REACHED')\n"
        "    except Exception as exc:\n"
        "        print(f'{label}:blocked:{type(exc).__name__}')\n"
    )
    assert "REACHED" not in result.detail, f"egress succeeded: {result.detail}"
    assert "dns:blocked" in result.detail
    assert "tcp:blocked" in result.detail


def test_no_filesystem_escape():
    """Reads outside scratch denied, writes outside denied, scratch itself writable."""
    result = run_sandboxed(
        "import pathlib\n"
        "for p in ('/etc/passwd', '/etc/shadow', '/root/.bashrc', '/scratch/../etc/passwd'):\n"
        "    try:\n"
        "        pathlib.Path(p).read_text()\n"
        "        print(f'READ_OK:{p}')\n"
        "    except Exception as exc:\n"
        "        print(f'read_denied:{p}:{type(exc).__name__}')\n"
        "for p in ('/tmp/x', '/etc/x', '/root/x', '/x'):\n"
        "    try:\n"
        "        pathlib.Path(p).write_text('x')\n"
        "        print(f'WRITE_OK:{p}')\n"
        "    except Exception as exc:\n"
        "        print(f'write_denied:{p}:{type(exc).__name__}')\n"
        "pathlib.Path('/scratch/mine').write_text('ok')\n"
        "print('scratch_writable:' + pathlib.Path('/scratch/mine').read_text())\n"
    )
    assert "READ_OK" not in result.detail, f"read escaped: {result.detail}"
    assert "WRITE_OK" not in result.detail, f"write escaped: {result.detail}"
    assert "scratch_writable:ok" in result.detail, result.detail


def test_pid_exhaustion():
    """A fork bomb is capped and the daemon survives.

    The container's own exit code is deliberately not asserted: measured, a recursive
    fork bomb can exit 0 with empty output. What must hold is that the host survives.
    """
    run_sandboxed(
        "import os\n"
        "for _ in range(10000):\n"
        "    try:\n"
        "        os.fork()\n"
        "    except OSError:\n"
        "        pass\n",
        wall_ms=8000,
    )
    assert _docker_alive(), "the docker daemon did not survive a fork bomb"


def test_memory_bomb():
    """Allocating past the cap is OOM-killed, and the result says so."""
    result = run_sandboxed("x = bytearray(2_000_000_000)\nprint('ALLOCATED')", memory_mb=256)
    assert result.outcome == "out_of_memory", f"got {result.outcome}: {result.detail}"
    assert "ALLOCATED" not in result.detail
    assert _docker_alive()


def test_wall_clock_timeout():
    """An infinite loop is hard-killed at the deadline — and the container is really
    gone afterwards.

    The second assertion is the one that matters. Measured: relying on subprocess's own
    timeout kills the docker CLI while the daemon keeps running the container forever.
    That failure is invisible to a test that only checks the outcome field, which would
    report `timeout` perfectly correctly while the runaway container burns CPU.
    """
    result = run_sandboxed("while True:\n    pass\n", wall_ms=2000)
    assert result.outcome == "timeout", f"got {result.outcome}: {result.detail}"
    assert result.wall_ms < 15_000, f"took {result.wall_ms}ms — did it actually get killed?"

    survivors = subprocess.run(
        ["docker", "ps", "-q", "--filter", "label=interview-helper-executor"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert survivors.stdout.strip() == "", "a container outlived its own timeout"


def test_no_cross_execution_contamination():
    """The scratch tmpfs is destroyed between runs.

    Ranked alongside the escapes because it is the one most likely to produce silently
    *wrong grades* rather than a visible failure — one candidate's leftover file
    satisfying the next execution's test.
    """
    first = run_sandboxed("open('/scratch/leaked', 'w').write('secret')\nprint('wrote')")
    assert first.outcome == "ok", first.detail

    second = run_sandboxed("import os\nprint('scratch:' + str(sorted(os.listdir('/scratch'))))")
    assert second.outcome == "ok", second.detail
    assert "leaked" not in second.detail, f"contamination: {second.detail}"
    assert "scratch:[]" in second.detail
