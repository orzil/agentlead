"""Home Reddit trickle, started from the Startup folder (Task Scheduler is
access-denied on this account, same as wa_loop). One Reddit feed a minute plus
the cloud-lead sync; logs to reddit_loop.log. See config.REDDIT_TRICKLE_SECONDS.

Restarts itself if the loop ever dies: a pythonw process has no console, so a
crash on 2026-11-06 went unnoticed for 2 days."""
import logging
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.chdir(HERE)
sys.path.insert(0, str(HERE))
os.environ.setdefault("AGENT_LOG", str(HERE / "reddit_loop.log"))
sys.argv = ["main.py", "--only", "reddit_trickle,cloud_sync,agency_mail"]

import main  # noqa: E402

while True:
    try:
        main.main()
    except KeyboardInterrupt:
        raise
    except BaseException as e:      # SystemExit included: never stay down
        logging.getLogger("reddit_loop").exception("loop died (%s); restarting in 60s", e)
    time.sleep(60)
