"""Cross-process serialization of the new read-only SolidWorks entry points."""
import os
import subprocess
import sys
import time

import pytest

from scripts.sw_read_guard import SolidWorksReadGuard


@pytest.mark.skipif(os.name != "nt", reason="Windows named mutex behavior")
def test_windows_read_guard_serializes_processes():
    script = (
        "from scripts.sw_read_guard import SolidWorksReadGuard; "
        "print('ready', flush=True); "
        "exec(\"with SolidWorksReadGuard():\\n print('acquired', flush=True)\")"
    )
    with SolidWorksReadGuard():
        child = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True)
        try:
            assert child.stdout.readline().strip() == "ready"
            time.sleep(0.3)
            assert child.poll() is None
        except BaseException:
            child.kill()
            child.communicate(timeout=5)
            raise
    stdout, stderr = child.communicate(timeout=10)
    assert child.returncode == 0, stderr
    assert stdout.strip() == "acquired"
