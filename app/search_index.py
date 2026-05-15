from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

DB_PATH = Path("/data/pipeline.db")


def build_fts_query(q: str, mode: str) -> str:
    q = (q or "").strip()
    mode = (mode or "match").lower()
    if not q:
        return q
    if mode == "phrase":
        return f'"{q}"'
    if mode == "prefix":
        return " ".join(token + "*" for token in q.split())
    if mode == "near":
        parts = q.rsplit(" ", 1)
        if len(parts) == 2 and parts[1].isdigit():
            return f"NEAR({parts[0]}, {parts[1]})"
        return f"NEAR({q}, 5)"
    return q


SEARCH_SQL = """
SELECT
    p.id,
    p.title,
    p.doi,
    p.published_date,
    p.category,
    bm25(papers_fts, 10.0, 3.0, 1.0) AS score,
    snippet(papers_fts, 2, '<mark>', '</mark>', ' … ', 18) AS snippet
FROM papers_fts
JOIN papers p ON p.id = papers_fts.rowid
WHERE papers_fts MATCH ?
  AND (? = '' OR p.category = ?)
  AND (? = '' OR p.published_date >= ?)
  AND (? = '' OR p.published_date <= ?)
ORDER BY score
LIMIT ?
"""


def _conn(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def search_papers(
    conn: sqlite3.Connection,
    query: str,
    mode: str = "match",
    category: str = "",
    start_date: str = "",
    end_date: str = "",
    limit: int = 20,
):
    fts_query = build_fts_query(query, mode)
    return conn.execute(
        SEARCH_SQL,
        (
            fts_query,
            category, category,
            start_date, start_date,
            end_date, end_date,
            limit,
        ),
    ).fetchall()


def rebuild_fts(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO papers_fts(papers_fts) VALUES('rebuild')")
    conn.commit()


def smoke_test(conn: sqlite3.Connection) -> dict:
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    count = conn.execute("SELECT COUNT(*) FROM papers_fts").fetchone()[0]
    sample = conn.execute(
        """
        SELECT p.id, p.title, bm25(papers_fts, 10.0, 3.0, 1.0) AS score
        FROM papers_fts
        JOIN papers p ON p.id = papers_fts.rowid
        WHERE papers_fts MATCH 'calcium OR hippocampus OR imaging'
        ORDER BY score
        LIMIT 5
        """
    ).fetchall()
    return {
        "tables": [row["name"] for row in tables],
        "papers_fts_count": count,
        "sample_hits": [dict(row) for row in sample],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="FTS5 search helper")
    parser.add_argument("query", nargs="?", help="FTS5 MATCH query")
    parser.add_argument("--db", default=str(DB_PATH), help="Path to SQLite DB")
    parser.add_argument("--mode", default="match", choices=["match", "phrase", "prefix", "near"])
    parser.add_argument("--category", default="")
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args()

    conn = _conn(Path(args.db))
    try:
        if args.rebuild:
            rebuild_fts(conn)
            print("rebuild complete")
        elif args.smoke_test:
            print(json.dumps(smoke_test(conn), indent=2))
        elif args.query:
            rows = search_papers(
                conn,
                args.query,
                mode=args.mode,
                category=args.category,
                start_date=args.start_date,
                end_date=args.end_date,
                limit=args.limit,
            )
            print(json.dumps([dict(r) for r in rows], indent=2))
        else:
            parser.error("provide a query or use --rebuild / --smoke-test")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
