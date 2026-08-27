from __future__ import annotations

import os
import subprocess
import sys
import time


def test_disabled_trader_waits_for_shutdown_signal() -> None:
    env = os.environ.copy()
    env.update({"TRADING_MODE": "demo", "RUN_NAUTILUS_NODE": "false", "PLATFORM_ROOT": os.getcwd()})
    process = subprocess.Popen(
        [sys.executable, "-m", "apps.trader.main"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        time.sleep(0.2)
        assert process.poll() is None
        process.terminate()
        output, _ = process.communicate(timeout=2)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)

    assert process.returncode == 0, output
