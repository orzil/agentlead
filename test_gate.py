"""Regression suite for the keyword gate, built from leads Or actually rejected.

Every case here is real. Each one reached his table, he caught it by hand, and a
rule was written afterwards. Until now those checks lived as throwaway strings
inside terminal commands - they protected nothing once the window closed.

Both directions are tested on purpose. A gate that rejects everything would
score 100% on the rejections alone, so the cases Or LIKED are the ones that stop
a fix from quietly destroying recall.

Run:  python -X utf8 test_gate.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone

import config
import prefilter
from models import Lead

NOW = datetime.now(timezone.utc)
EVAL_FILE = config.BASE_DIR / "eval_cases.json"

# (name, source, text, posted_at, expected verdict)
CASES = [
    # --- full-time roles that scored 7-8 because LinkedIn alert emails carry
    # only "<title> <company> - <location>", with no employment type ---
    ("KLA full-time", "linkedin/alert",
     "Computer Vision Algorithm Developer KLA Migdal HaEmeq\n5 days ago | 32 applicants\n"
     "Employment type: Full-time\n\nDeveloping computer vision algorithms for wafer inspection.",
     NOW, "gate_full_time"),
    ("Cybord full-time", "linkedin/alert",
     "Mid-Senior Data Scientist Image Analysis Cybord Israel\n2 weeks ago | 41 applicants\n"
     "Employment type: Full-time\n\nImage analysis, computer vision and text reading.",
     NOW, "gate_full_time"),

    # --- expired / stale: an aijobs listing 28 days dead, and a Facebook post
    # from 2024 that looked fresh because FB gives the fetcher no date ---
    ("aijobs expired", "aijobs",
     "Freelance chatbot developer WhatsApp Telegram Discord, Israel remote. "
     "Contract work with LLM APIs and asynchronous programming.",
     NOW - timedelta(days=75), "gate_stale"),
    ("facebook 2024 post", "facebook/Israel Freelance Developers",
     "Card Williams\nMarch 31, 2024\n.\nHello Guys\nI need a freelancer for my project "
     "retyping document images into PDF file. OCR work available.",
     None, "gate_stale"),
    ("abbreviated old date", "facebook/search",
     "Lior Tal Mar 7, 2022 Do you want a chance to work at Google? apply here for the program",
     NOW, "gate_stale"),
    ("closed posting", "linkedin/alert",
     "[CLOSED - no longer accepting applications]\nSenior CV Engineer\n"
     "Employment type: Contract\n\nComputer vision work.", NOW, "gate_closed"),

    # --- seekers: people advertising themselves, in both languages ---
    # --- WhatsApp group chat (2026-10-09): chat is noisy, so a post needs a domain
    # term AND hiring intent; a freelancer advertising himself must not pass ---
    ("wa hebrew client", "whatsapp/Test Group",
     "דרוש פרילנסר לפרויקט ראייה ממוחשבת - זיהוי פגמים בקו ייצור, תקציב 8000 ש\"ח, מי פנוי?",
     NOW, "pass"),
    ("wa english client", "whatsapp/Test Group",
     "Looking for a freelancer for an OCR project extracting data from scanned invoices. "
     "Budget $1500, DM me.", NOW, "pass"),
    ("wa course chat", "whatsapp/Test Group",
     "Good morning everyone, can anyone recommend a good machine learning course for beginners?",
     NOW, "gate_offtopic"),
    ("wa hebrew seeker", "whatsapp/Test Group",
     "מפתח פרילנסר זמין לפרויקטים בתחום בינה מלאכותית ואוטומציה, פנו אליי בפרטי",
     NOW, "gate_seeker"),
    # --- WhatsApp domain QUESTIONS (2026-10-18): a second kind of lead - Or
    # answers, the asker becomes a client. Learner asks stay offtopic. ---
    ("wa hebrew domain question", "whatsapp/Test Group",
     "מישהו מכיר דרך טובה לעשות OCR על חשבוניות סרוקות בעברית? הטסרקט נותן לנו זבל",
     NOW, "question"),
    ("wa english domain question", "whatsapp/Test Group",
     "Has anyone used YOLO for defect detection on a production line? Our false "
     "positives are killing us", NOW, "question"),
    ("wa offtopic question", "whatsapp/Test Group",
     "Does anyone know a good accountant in Tel Aviv for a small company?",
     NOW, "gate_offtopic"),
    ("wa learner question", "whatsapp/Test Group",
     "איך מתחילים ללמוד למידת מכונה? יש המלצה על קורס טוב?", NOW, "gate_noise"),
    # 2026-10-20: a job-board bot's post. Its '?utm_source=' made it a "question".
    ("wa job-board bot link", "whatsapp/Test Group",
     "Machine learning engineer | computer vision\nAcme\nRamat Gan\n19/10/26\n"
     "Python, Image Processing, Deep Learning\nJunior\n"
     "https://jobs.example.io/jobz/edc067eb26?utm_source=wa_x", NOW, "gate_offtopic"),
    # 2026-10-20: the real card format (ㅤ separators + seniority) is a salaried
    # role: full-time, so an in-domain one becomes an outbound prospect.
    ("wa job card", "whatsapp/Test Group",
     "Machine learning engineer | computer vision Acme Ramat Gan 19/10/26 ㅤ Python, "
     "Image Processing, Deep Learning ㅤ Junior ㅤ https://jobs.example.io/jobz/edc067eb26 "
     "-- Set up a saved search?", NOW, "gate_full_time"),
    ("wa hebrew recommendation ask", "whatsapp/Test Group",
     "מישהו מכיר מפתח שמבין בעיבוד תמונה? יש לנו מצלמה בקו ייצור וצריך לזהות פגמים",
     NOW, "pass"),
    ("wa english recommendation ask", "whatsapp/Test Group",
     "Can anyone recommend a freelance computer vision developer? We need to count "
     "people in store camera footage.", NOW, "pass"),
    ("arbeitnow generic AI role", "arbeitnow",
     "Freelance Data Analyst (m/w/d) - remote. Work with AI tools and dashboards "
     "for our marketing team, contract 6 months.", NOW, "gate_offtopic"),
    ("arbeitnow CV contract", "arbeitnow",
     "Freelance Computer Vision Engineer (m/w/d) - remote contract, 6 months. "
     "Object detection with YOLO and OpenCV.", NOW, "pass"),
    ("wa full-time post", "whatsapp/Test Group",
     "דרוש/ה מפתח/ת Computer Vision למשרה מלאה בחברת סטארטאפ בהרצליה, היברידי",
     NOW, "gate_full_time"),
    ("python dev available", "r/PythonJobs",
     "Python Developer Available - Bots, Automation & Custom Scripts. Hi everyone, I'm a "
     "Python developer currently looking to take on freelance work. I can help with: "
     "Telegram bots, workflow automation, API integrations.", NOW, "gate_seeker"),
    ("hebrew self-intro", "facebook/search",
     "היי לכולם, שמי טל כהן, מהנדס תוכנה ויועץ פיתוח, בעל ניסיון בפיתוח וניהול צוותים "
     "מקצה לקצה, מחפש פרויקטים חדשים.", NOW, "gate_seeker"),

    # --- money floors, including currency conversion ---
    ("$30 project", "r/forhire",
     "Need a Python developer for a small OCR script. Budget: $30 for the whole project, "
     "should take an hour or two.", NOW, "gate_lowbudget"),
    ("rupees per hour", "r/forhire",
     "Looking for a computer vision developer, paying ₹500/hr for object detection work.",
     NOW, "gate_lowbudget"),

    # === MUST PASS - the recall half. Or picked the YOLO one as the best lead
    # of an entire batch, and it had survived only by accidentally containing
    # the word "AI" until the domain vocabulary was widened. ===
    ("YOLO defect POC (Or's pick)", "r/computervision",
     "Defects detection using YOLO but hit a wall. I'm working on a proof of concept for "
     "detecting concrete spalling defects. Looking for someone to help with the model, "
     "budget available for the right freelancer.", NOW - timedelta(days=3), "pass"),
    ("opencv gig, no 'AI' word", "r/computervision",
     "Need help with an OpenCV pipeline for bounding box detection, paid freelance project, "
     "remote, budget $3000.", NOW, "pass"),
    ("hebrew client post", "facebook/דרושים מתכנתים ואנשי פיתוח",
     "דרוש מפתח פרילנסר לפרויקט ראייה ממוחשבת - זיהוי אובייקטים בוידאו. עבודה מרחוק, "
     "תקציב 15000 שח, כחודשיים.", NOW, "pass"),
    ("hourly at target rate", "r/MachineLearningJobs",
     "Hiring a Robotics ML expert for MuJoCo simulation and RL, remote contract, "
     "$100-150/hr, part-time.", NOW, "pass"),
    ("$50/hour is fine", "r/forhire",
     "Looking for a computer vision engineer for an OCR pipeline. Rate is $50/hour, "
     "remote, ongoing contract work.", NOW, "pass"),
]


def _load_user_cases() -> list[tuple]:
    """Cases Or added by replying to a Telegram push (feedback.py)."""
    if not EVAL_FILE.exists():
        return []
    try:
        raw = json.loads(EVAL_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    out = []
    for c in raw:
        posted = None
        if c.get("posted_at"):
            try:
                posted = datetime.fromisoformat(c["posted_at"])
            except ValueError:
                pass
        out.append((f"user:{c['verdict']} {c['url'][:40]}", c["source"],
                    c["text"], posted, c["expect"]))
    return out


def run() -> int:
    cases = CASES + _load_user_cases()
    failed = []
    for name, source, text, posted, expected in cases:
        got = prefilter.classify(Lead(source=source, url="https://example.com/x",
                                      raw_text=text, posted_at=posted))
        ok = got == expected
        if not ok:
            failed.append((name, expected, got))
        print(f"{'PASS' if ok else 'FAIL'}  {expected:16} got={got:16} {name}")
    print()
    print(f"{len(cases) - len(failed)}/{len(cases)} passed"
          f"  ({len(CASES)} built-in, {len(cases) - len(CASES)} from your replies)")
    if failed:
        print("\nFAILURES:")
        for n, e, g in failed:
            print(f"  {n}: expected {e}, got {g}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run())
