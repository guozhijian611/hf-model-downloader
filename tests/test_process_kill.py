"""Tests for process-tree termination (hfd cancel regression)."""

from __future__ import annotations

import subprocess
import sys
import time

import psutil

from src.utils import kill_process_tree


def test_kill_process_tree_terminates_child():
    """Parent+child both die when killing the parent tree."""
    # Python child that spawns a short-lived grandchild via the shell.
    child_code = (
        "import subprocess, sys, time\n"
        "cmd = [sys.executable, '-c', 'import time; time.sleep(60)']\n"
        "subprocess.Popen(cmd)\n"
        "time.sleep(60)\n"
    )
    popen_kwargs: dict = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if not sys.platform.startswith("win"):
        popen_kwargs["start_new_session"] = True
    parent = subprocess.Popen(
        [sys.executable, "-c", child_code],
        **popen_kwargs,
    )

    time.sleep(0.5)
    assert parent.poll() is None
    try:
        p = psutil.Process(parent.pid)
        children = p.children(recursive=True)
        assert children, "expected at least one child process"
        child_pids = [c.pid for c in children]
    except psutil.Error:
        parent.kill()
        raise

    kill_process_tree(parent.pid, grace_sec=2.0)
    time.sleep(0.3)

    assert parent.poll() is not None
    for cpid in child_pids:
        assert not psutil.pid_exists(cpid), f"child pid {cpid} still alive"
