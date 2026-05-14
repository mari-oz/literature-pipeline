import sqlite3
from pathlib import Path
from typing import Iterable

DB_PATH = Path('/data/pipeline.db')

DEFAULT_SQL = """
SELECT
  p.id,
  p.title,
  p.doi,
  p.category,
  p.published_date,
  bm25(papers_fts, 10.0, 2.0, 5.0) AS rank,
  snippet(papers_fts, 2, '[', ']', ' … ', 18) AS match_snippet
FROM papers_fts
JOIN papers p ON p.id = papers_fts.rowid
WHERE papers_fts MATCH ?
ORDER BY rank
LIMIT ?;
"""


def search(query: str, limit: int = 20, db_path: Path = DB_PATH) -> list[sqlite3.Row]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(DEFAULT_SQL, (query, limit)).fetchall()
        return rows
    finally:
        conn.close()


def rebuild(db_path: Path = DB_PATH) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("INSERT INTO papers_fts(papers_fts) VALUES('rebuild')")
        conn.commit()
    finally:
        conn.close()


def smoke_test(db_path: Path = DB_PATH) -> dict:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        table_count = conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name IN ('papers','papers_fts')"
        ).fetchone()[0]
        fts_rows = conn.execute("SELECT count(*) FROM papers_fts").fetchone()[0]
        sample = conn.execute(
            """
            SELECT p.id, p.title
            FROM papers_fts
            JOIN papers p ON p.id = papers_fts.rowid
            WHERE papers_fts MATCH 'calcium OR hippocampus OR imaging'
            LIMIT 5
            """
        ).fetchall()
        return {
            'has_expected_tables': table_count == 2,
            'fts_row_count': fts_rows,
            'sample_hits': [dict(r) for r in sample],
        }
    finally:
        conn.close()


def _print_rows(rows: Iterable[sqlite3.Row]) -> None:
    for row in rows:
        print(f"[{row['id']}] {row['title']}")
        print(f"  rank={row['rank']:.4f}  doi={row['doi'] or '-'}  category={row['category'] or '-'}  date={row['published_date'] or '-'}")
        print(f"  {row['match_snippet']}")
        print()


if __name__ == '__main__':
    import argparse
    import json

    parser = argparse.ArgumentParser(description='FTS5 search helper for papers/papers_fts')
    parser.add_argument('query', nargs='?', help='FTS5 MATCH query string')
    parser.add_argument('--db', default=str(DB_PATH), help='Path to SQLite database')
    parser.add_argument('--limit', type=int, default=20, help='Max rows to return')
    parser.add_argument('--rebuild', action='store_true', help='Rebuild the FTS5 index')
    parser.add_argument('--smoke-test', action='store_true', help='Run basic FTS checks')
    args = parser.parse_args()

    db_path = Path(args.db)

    if args.rebuild:
        rebuild(db_path)
        print('FTS rebuild complete')
    elif args.smoke_test:
        print(json.dumps(smoke_test(db_path), indent=2))
    elif args.query:
        _print_rows(search(args.query, args.limit, db_path))
    else:
        parser.error('provide a query, or use --rebuild / --smoke-test')
