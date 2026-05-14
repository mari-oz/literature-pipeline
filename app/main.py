from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path

import yaml

from app.fetch_biorxiv import fetch_neuroscience_feed


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")

        conn.execute("""
        CREATE TABLE IF NOT EXISTS app_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS papers (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            link TEXT NOT NULL UNIQUE,
            published TEXT,
            summary TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """)

        conn.commit()
    finally:
        conn.close()


def load_config(config_path: Path) -> dict:
    with config_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def insert_new_papers(db_path: Path, papers: list[dict]) -> int:
    conn = sqlite3.connect(db_path)
    inserted = 0

    try:
        for paper in papers:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO papers (title, link, published, summary)
                VALUES (?, ?, ?, ?)
                """,
                (paper["title"], paper["link"], paper["published"], paper["summary"]),
            )
            if cur.rowcount > 0:
                inserted += 1

        conn.commit()
    finally:
        conn.close()

    return inserted


def write_digest(output_dir: Path, papers: list[dict], inserted: int) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    out_path = output_dir / f"biorxiv_digest_{ts}.md"

    lines = [
        f"# bioRxiv neuroscience digest",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        f"Total feed items seen: {len(papers)}",
        f"New papers inserted: {inserted}",
        "",
    ]

    for paper in papers[:20]:
        lines.extend(
            [
                f"## {paper['title']}",
                f"- Published: {paper['published']}",
                f"- Link: {paper['link']}",
                "",
                paper["summary"],
                "",
            ]
        )

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def main() -> None:
    config_path = Path(os.environ.get("CONFIG_PATH", "/config/config.yaml"))
    db_path = Path(os.environ.get("DB_PATH", "/data/pipeline.db"))

    config = load_config(config_path)
    output_dir = Path(config.get("output", {}).get("dir", "/output"))

    init_db(db_path)

    fetched = fetch_neuroscience_feed()
    papers = [
        {
            "title": p.title,
            "link": p.link,
            "published": p.published,
            "summary": p.summary,
        }
        for p in fetched
    ]

    inserted = insert_new_papers(db_path, papers)
    digest_path = write_digest(output_dir, papers, inserted)

    print(f"Fetched {len(papers)} papers")
    print(f"Inserted {inserted} new papers")
    print(f"Wrote digest to {digest_path}")


if __name__ == "__main__":
    main()
