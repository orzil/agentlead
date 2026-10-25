"""Run `main.py --wa-pass` every 2 hours, forever - the WhatsApp phone schedule.

Windows Task Scheduler refuses task creation on this account ("Access is
denied", 2026-10-18), so this loop is started hidden (pythonw) from the user's
Startup folder instead and survives reboots that way. Each pass runs in a fresh
subprocess, so a `git pull` of new code takes effect on the next pass and a
crash in one pass never kills the loop.

A localhost socket is the single-instance lock: a second copy (double login,
manual start) exits immediately instead of driving the phone in parallel.
"""
from __future__ import annotations

import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
INTERVAL = 2 * 3600
LOCK_PORT = 47361
LOG = HERE / "wa_pass.log"


LOG_MAX_BYTES = 5 * 1024 * 1024


def _rotate_log() -> None:
    """Keep wa_pass.log bounded: past LOG_MAX_BYTES it becomes wa_pass.log.1
    (one old copy kept). Runs between passes, when nothing holds the file."""
    try:
        if LOG.exists() and LOG.stat().st_size > LOG_MAX_BYTES:
            LOG.replace(LOG.with_name(LOG.name + ".1"))
    except OSError:
        pass                        # never let housekeeping stop a pass


def _log(msg: str) -> None:
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} [wa_loop] {msg}\n")


def main() -> None:
    lock = socket.socket()
    try:
        lock.bind(("127.0.0.1", LOCK_PORT))
    except OSError:
        return                      # another loop is already running
    python = Path(sys.executable).with_name("python.exe")   # console-less parent is fine
    _log(f"started (pid via {python.name}), every {INTERVAL // 3600}h")
    while True:
        started = time.time()
        _rotate_log()
        try:
            with LOG.open("a", encoding="utf-8") as out:
                r = subprocess.run([str(python), "-X", "utf8", "main.py", "--wa-pass"],
                                   cwd=HERE, stdout=out, stderr=subprocess.STDOUT,
                                   timeout=90 * 60,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            _log(f"pass exit {r.returncode} in {time.time() - started:.0f}s")
        except subprocess.TimeoutExpired:
            _log("pass timed out after 90 min")
        except Exception as e:      # never let the scheduler itself die
            _log(f"pass failed to start: {e}")
        time.sleep(_next_sleep(started))


def _next_sleep(started: float) -> float:
    """Every 2h normally. While join-all has a join left today, come back when
    wa_phone says the next one is due (its random gap / break / sheet-rate
    schedule) - sooner than 2h, never a fixed 5-min poll: those only woke the
    screen (measured 2026-10-23: a 107s pass every 7 min until 23:00). Nothing
    left today (capped, throttled, night, no targets) falls back to 2h."""
    try:
        import db
        from wa_phone import next_join_at
        conn = db.connect()
        at = next_join_at(conn)
        if at is not None:
            return max(60, min(INTERVAL - (time.time() - started), at - time.time()))
    except Exception as e:
        _log(f"kv read failed: {e}")
    return max(60, INTERVAL - (time.time() - started))


if __name__ == "__main__":
    main()
