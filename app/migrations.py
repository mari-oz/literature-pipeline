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

def ensure_column(conn, table: str, column: str, ddl: str) -> None:
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def migrate(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS papers (
            id INTEGER PRIMARY KEY,
            doi TEXT UNIQUE,
            title TEXT NOT NULL,
            link TEXT,
            published_date TEXT,
            summary TEXT,
            abstract TEXT,
            authors TEXT,
            category TEXT,
            version TEXT,
            license TEXT,
            server TEXT,
            corresponding_author TEXT,
            corresponding_institution TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS summaries (
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

    ensure_column(conn, "papers", "published_doi", "published_doi TEXT")
    ensure_column(conn, "papers", "published_journal", "published_journal TEXT")
    ensure_column(conn, "papers", "published_article_date", "published_article_date TEXT")
    ensure_column(conn, "papers", "preprint_platform", "preprint_platform TEXT")

    conn.commit()
