from __future__ import annotations

from dataclasses import dataclass
from typing import List
import feedparser


NEUROSCIENCE_RSS = "http://connect.biorxiv.org/biorxiv_xml.php?subject=neuroscience"


@dataclass
class Paper:
    title: str
    link: str
    published: str
    summary: str


def fetch_neuroscience_feed(url: str = NEUROSCIENCE_RSS) -> List[Paper]:
    feed = feedparser.parse(url)
    papers: List[Paper] = []

    for entry in feed.entries:
        papers.append(
            Paper(
                title=entry.get("title", "").strip(),
                link=entry.get("link", "").strip(),
                published=entry.get("published", "").strip(),
                summary=entry.get("summary", "").strip(),
            )
        )

    return papers
