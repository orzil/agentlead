from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Lead:
    source: str                 # "facebook", "r/forhire", "hn/whoishiring", "xplace", ...
    url: str                    # direct link to the post
    raw_text: str               # title + body, untruncated
    author: str | None = None
    posted_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.posted_at is None:
            self.posted_at = datetime.now(timezone.utc)
        self.raw_text = (self.raw_text or "").strip()
        self.url = (self.url or "").strip()

    @property
    def lang(self) -> str:
        """Cheap Hebrew/English detection: any Hebrew letters -> 'he'."""
        return "he" if any("֐" <= c <= "ת" for c in self.raw_text[:800]) else "en"


@dataclass
class LeadScore:
    score: int
    category: str = "other"      # cv_image | ocr | ml_general | algorithms | data_viz | ai_web | other
    work_type: str = "unclear"   # poc | contract | part_time | full_time | one_off_project | unclear
    summary: str = ""
    budget_mentioned: str | None = None
    red_flags: list[str] = field(default_factory=list)
    reasoning: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "LeadScore":
        red = d.get("red_flags") or []
        if isinstance(red, str):
            red = [red]
        return cls(
            score=max(1, min(10, int(d.get("score", 1)))),
            category=str(d.get("category", "other")),
            work_type=str(d.get("work_type", "unclear")),
            summary=str(d.get("summary", ""))[:600],
            budget_mentioned=(str(d["budget_mentioned"])[:120]
                              if d.get("budget_mentioned") else None),
            red_flags=[str(r)[:80] for r in red][:6],
            reasoning=str(d.get("reasoning", ""))[:300],
        )
