"""Merge the cloud's leads.db into the local one.

The cloud keeps leads.db in the GitHub Actions cache, which is a DIFFERENT
database from the local file. That split is why discovery could look productive
while Or's table stayed empty: the night run finds Facebook posts, stores them
in the cloud DB, and nothing ever carries them across. The cloud also cannot
score - runners have no Ollama and the Gemini free tier dies after ~20 calls -
so those leads arrive unscored and are scored here, where Ollama is free and
unlimited.

Merges on url_hash, the same key db.insert_lead dedups on, so re-running is
harmless and rows already known locally are skipped.

Usage:  python -X utf8 sync_cloud.py [--score N]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile

import config
import db

REPO = "orzil/agentlead"


def _newest_artifact(tmp: str) -> str | None:
    """Download the most recent leads.db artifact via gh."""
    try:
        out = subprocess.run(
            ["gh", "run", "list", "--repo", REPO, "--limit", "25",
             "--json", "databaseId,conclusion,name"],
            capture_output=True, text=True, timeout=90).stdout
        runs = [r for r in json.loads(out or "[]") if r.get("conclusion") == "success"]
    except Exception as e:
        print("could not list runs:", e)
        return None
    for r in runs:
        p = subprocess.run(["gh", "run", "download", str(r["databaseId"]),
                            "--repo", REPO, "-D", tmp],
                           capture_output=True, text=True, timeout=180)
        if p.returncode == 0:
            hits = glob.glob(os.path.join(tmp, "**", "leads.db"), recursive=True)
            if hits:
                print(f"using artifact from run {r['databaseId']} ({r['name']})")
                return hits[0]
    return None


def merge(cloud_path: str) -> dict:
    local = db.connect()
    cloud = sqlite3.connect(cloud_path)
    cloud.row_factory = sqlite3.Row
    have = {r[0] for r in local.execute("SELECT url_hash FROM leads")}
    cols = ["url_hash", "url", "source", "author", "lang", "posted_at",
            "fetched_at", "raw_text", "status", "score", "category",
            "work_type", "summary", "budget", "red_flags", "reasoning"]
    added = skipped = 0
    for row in cloud.execute(f"SELECT {','.join(cols)} FROM leads"):
        if row["url_hash"] in have:
            skipped += 1
            continue
        local.execute(
            f"INSERT OR IGNORE INTO leads ({','.join(cols)}) "
            f"VALUES ({','.join('?' * len(cols))})",
            tuple(row[c] for c in cols))
        added += 1
    local.commit()
    # carry the discovered-group table across too, so promotions survive
    groups = 0
    try:
        for row in cloud.execute("SELECT slug,url,name,status,relevance,region,"
                                 "found_via,first_seen,in_rotation FROM facebook_groups"):
            cur = local.execute(
                "INSERT OR IGNORE INTO facebook_groups (slug,url,name,status,"
                "relevance,region,found_via,first_seen,in_rotation)"
                " VALUES (?,?,?,?,?,?,?,?,?)", tuple(row))
            groups += cur.rowcount
        local.commit()
    except Exception as e:
        print("group table merge skipped:", str(e)[:80])
    return {"leads_added": added, "already_had": skipped, "groups_added": groups}


def run_once() -> dict:
    """Scheduler entry point: sync, then score whatever arrived.

    Returns {} rather than raising when gh is missing or no artifact exists -
    this runs every 2 hours and must never be the reason the loop dies.
    """
    tmp = tempfile.mkdtemp(prefix="agentlead_cloud_")
    try:
        path = _newest_artifact(tmp)
        if not path:
            return {}
        stats = merge(path)
    except Exception as e:
        print("cloud sync failed:", str(e)[:120])
        return {}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if stats.get("leads_added"):
        # score them here, where Ollama is free and unlimited - the whole point
        # of bringing them home. Pushes for >=8 fire from score_backlog.
        import main as m
        m.score_backlog(db.connect(), min(stats["leads_added"], 300))
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description="Pull cloud-found leads into the local DB")
    ap.add_argument("--score", nargs="?", const=200, type=int, metavar="N",
                    help="score up to N newly imported leads with the local backend")
    args = ap.parse_args()

    tmp = tempfile.mkdtemp(prefix="agentlead_cloud_")
    try:
        path = _newest_artifact(tmp)
        if not path:
            print("no leads.db artifact found in recent successful runs")
            return
        print(merge(path))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if args.score:
        import main as m
        m.score_backlog(db.connect(), args.score)


if __name__ == "__main__":
    main()
