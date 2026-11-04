"""Home Reddit trickle, started from the Startup folder (Task Scheduler is
access-denied on this account, same as wa_loop). One Reddit feed a minute plus
the cloud-lead sync; logs to reddit_loop.log. See config.REDDIT_TRICKLE_SECONDS."""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.chdir(HERE)
sys.path.insert(0, str(HERE))
os.environ.setdefault("AGENT_LOG", str(HERE / "reddit_loop.log"))
sys.argv = ["main.py", "--only", "reddit_trickle,cloud_sync"]

import main  # noqa: E402

main.main()
