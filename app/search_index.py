from __future__ import annotations

import sqlite3


def search_papers(conn: sqlite3.Connection, query: str, limit: int = 20):
    return conn.execute(
        """
        SELECT
            p.id,
            p.title,
            p.doi,
            p.published_date,
            p.category,
            bm25(papers_fts) AS score
        FROM papers_fts
        JOIN papers p ON p.id = papers_fts.rowid
        WHERE papers_fts MATCH ?
        ORDER BY score
        LIMIT ?
        """,
        (query, limit),
    ).fetchall()


def rebuild_fts(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM papers_fts")
    conn.execute("""
        INSERT INTO papers_fts(rowid, title, abstract, summary_text)
        SELECT id, title, abstract, summary_text
        FROM papers
    """)
    conn.commit()
