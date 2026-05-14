from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path

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

            if not title:
                continue

            if doi:
                existing = conn.execute(
                    "SELECT 1 FROM papers WHERE doi = ?",
                    (doi,),
                ).fetchone()
            elif link:
                existing = conn.execute(
                    "SELECT 1 FROM papers WHERE link = ?",
                    (link,),
                ).fetchone()
            else:
                continue

            if existing:
                continue

            conn.execute(
                """
                INSERT INTO papers (doi, title, link, published_date, summary)
                VALUES (?, ?, ?, ?, ?)
                """,
                (doi, title, link, published_date, summary),
            )
            inserted += 1

        conn.commit()
        return inserted
    finally:
        conn.close()


def run_pipeline(db_path: Path) -> tuple[int, int, int, int]:
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

        return inserted, enriched, publication_updates, summarized
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

    inserted, enriched, publication_updates, summarized = run_pipeline(db_path)
    digest_path = write_digest(db_path)

    print(
        f"Done. inserted={inserted} enriched={enriched} "
        f"publication_updates={publication_updates} "
        f"summarized={summarized} digest={digest_path}"
    )


if __name__ == "__main__":
    main()
