from __future__ import annotations

import sqlite3


def get_user_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def set_user_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(f"PRAGMA user_version = {version}")


def column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row[1] == column for row in rows)


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    if not column_exists(conn, table, column):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def migrate(conn: sqlite3.Connection) -> None:
    version = get_user_version(conn)

    if not table_exists(conn, "papers"):
        conn.execute("""
        CREATE TABLE papers (
            id INTEGER PRIMARY KEY,
            doi TEXT,
            title TEXT NOT NULL,
            link TEXT,
            abstract TEXT,
            authors TEXT,
            category TEXT,
            published_date TEXT,
            version TEXT,
            license TEXT,
            server TEXT DEFAULT 'biorxiv',
            corresponding_author TEXT,
            corresponding_institution TEXT,
            summary TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """)

    add_column_if_missing(conn, "papers", "doi", "TEXT")
    add_column_if_missing(conn, "papers", "link", "TEXT")
    add_column_if_missing(conn, "papers", "abstract", "TEXT")
    add_column_if_missing(conn, "papers", "authors", "TEXT")
    add_column_if_missing(conn, "papers", "category", "TEXT")
    add_column_if_missing(conn, "papers", "published_date", "TEXT")
    add_column_if_missing(conn, "papers", "version", "TEXT")
    add_column_if_missing(conn, "papers", "license", "TEXT")
    add_column_if_missing(conn, "papers", "server", "TEXT DEFAULT 'biorxiv'")
    add_column_if_missing(conn, "papers", "corresponding_author", "TEXT")
    add_column_if_missing(conn, "papers", "corresponding_institution", "TEXT")
    add_column_if_missing(conn, "papers", "summary", "TEXT")
    add_column_if_missing(conn, "papers", "updated_at", "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP")

    if not table_exists(conn, "summaries"):
        conn.execute("""
        CREATE TABLE summaries (
            id INTEGER PRIMARY KEY,
            paper_id INTEGER NOT NULL,
            model_name TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            summary_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(paper_id, model_name, prompt_version),
            FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE
        )
        """)

    conn.execute("CREATE INDEX IF NOT EXISTS idx_papers_doi ON papers(doi)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_papers_link ON papers(link)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_summaries_paper_id ON summaries(paper_id)")

    set_user_version(conn, 2)
