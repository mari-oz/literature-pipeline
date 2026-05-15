from __future__ import annotations

import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterable

from app.fetch_biorxiv import fetch_neuroscience_feed
from app.migrations import migrate
from app.enrich_biorxiv import enrich_unsynced_papers
from app.enrich_publication import enrich_publication_metadata
from app.generate_digest import generate_digest


def get_connection(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(db_path)
    try:
        migrate(conn)
        conn.commit()
    finally:
        conn.close()


def _normalize_author_name(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip()


def _split_authors(raw: str | None) -> list[str]:
    if not raw:
        return []
    parts = re.split(r"\s*(?:;|,| and | & )\s*", raw)
    return [_normalize_author_name(p) for p in parts if _normalize_author_name(p)]


def _upsert_author(conn: sqlite3.Connection, name: str) -> int:
    canonical_name = _normalize_author_name(name)
    canonical_norm = canonical_name.lower()
    row = conn.execute(
        "SELECT id FROM authors WHERE canonical_name_norm = ?",
        (canonical_norm,),
    ).fetchone()
    if row:
        return int(row[0])
    cur = conn.execute(
        """
        INSERT INTO authors (canonical_name, canonical_name_norm)
        VALUES (?, ?)
        """,
        (canonical_name, canonical_norm),
    )
    return int(cur.lastrowid)


def _store_paper_authors(conn: sqlite3.Connection, paper_id: int, authors: Iterable[str]) -> int:
    inserted = 0
    for pos, author_name in enumerate(authors, start=1):
        if not author_name:
            continue
        author_id = _upsert_author(conn, author_name)
        exists = conn.execute(
            "SELECT 1 FROM paper_authors WHERE paper_id = ? AND author_id = ?",
            (paper_id, author_id),
        ).fetchone()
        if exists:
            continue
        conn.execute(
            """
            INSERT INTO paper_authors (paper_id, author_id, author_position)
            VALUES (?, ?, ?)
            """,
            (paper_id, author_id, pos),
        )
        inserted += 1
    return inserted


def _count_author_links(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) FROM paper_authors").fetchone()
    return int(row[0]) if row else 0


def _count_papers_with_authors(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(DISTINCT paper_id) FROM paper_authors").fetchone()
    return int(row[0]) if row else 0


def insert_new_papers(db_path: Path, papers: list[dict]) -> int:
    conn = get_connection(db_path)
    try:
        inserted = 0
        for paper in papers:
            doi = paper.get("doi")
            title = paper.get("title")
            link = paper.get("link")
            published_date = paper.get("published")
            summary = paper.get("summary")
            authors_raw = paper.get("authors") or paper.get("author") or paper.get("creator")
            authors = _split_authors(authors_raw if isinstance(authors_raw, str) else None)

            if not title:
                continue

            if doi:
                existing = conn.execute(
                    "SELECT id FROM papers WHERE doi = ?",
                    (doi,),
                ).fetchone()
            elif link:
                existing = conn.execute(
                    "SELECT id FROM papers WHERE link = ?",
                    (link,),
                ).fetchone()
            else:
                continue

            if existing:
                paper_id = int(existing[0])
                if authors:
                    _store_paper_authors(conn, paper_id, authors)
                continue

            cur = conn.execute(
                """
                INSERT INTO papers (doi, title, link, published_date, summary, authors)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (doi, title, link, published_date, summary, authors_raw),
            )
            paper_id = int(cur.lastrowid)
            if authors:
                _store_paper_authors(conn, paper_id, authors)
            inserted += 1

        conn.commit()
        return inserted
    finally:
        conn.close()


def run_pipeline(db_path: Path) -> tuple[int, int, int, int, int, int]:
    papers = fetch_neuroscience_feed()
    inserted = insert_new_papers(db_path, papers)

    conn = get_connection(db_path)
    try:
        enriched = enrich_unsynced_papers(conn, server="biorxiv")
        publication_updates = enrich_publication_metadata(conn, server="biorxiv")

        model_path = os.getenv("MODEL_PATH")
        model_name = os.getenv("MODEL_NAME", "local-llama")
        do_summary = os.getenv("ENABLE_SUMMARY", "false").lower() == "true"

        summarized = 0
        if do_summary and model_path:
            try:
                from app.summarize import build_llm, summarize_unsummarized_papers

                llm = build_llm(
                    model_path=model_path,
                    n_ctx=int(os.getenv("N_CTX", "4096")),
                    n_gpu_layers=int(os.getenv("N_GPU_LAYERS", "0")),
                )
                summarized = summarize_unsummarized_papers(
                    conn=conn,
                    llm=llm,
                    model_name=model_name,
                )
            except ImportError as exc:
                print(f"Summarization disabled: missing dependency ({exc})")

        author_links = _count_author_links(conn)
        papers_with_authors = _count_papers_with_authors(conn)
        return inserted, enriched, publication_updates, summarized, author_links, papers_with_authors
    finally:
        conn.close()


def write_digest(db_path: Path) -> Path:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        digest = generate_digest(conn)
    finally:
        conn.close()

    digest_dir = Path(os.getenv("DIGEST_DIR", "/data/digests"))
    digest_dir.mkdir(parents=True, exist_ok=True)

    digest_path = digest_dir / f"digest-{datetime.now().strftime('%Y-%m-%d')}.md"
    digest_path.write_text(digest, encoding="utf-8")
    return digest_path


def main() -> None:
    db_path = Path(os.getenv("DB_PATH", "/data/pipeline.db"))
    init_db(db_path)

    inserted, enriched, publication_updates, summarized, author_links, papers_with_authors = run_pipeline(db_path)
    digest_path = write_digest(db_path)

    print(
        f"Done. inserted={inserted} enriched={enriched} "
        f"publication_updates={publication_updates} "
        f"summarized={summarized} author_links={author_links} "
        f"papers_with_authors={papers_with_authors} digest={digest_path}"
    )


if __name__ == "__main__":
    main()
