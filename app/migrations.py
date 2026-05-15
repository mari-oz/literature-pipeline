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


def ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def migrate(conn: sqlite3.Connection) -> None:
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
        published_doi TEXT,
        published_journal TEXT,
        published_article_date TEXT,
        preprint_platform TEXT,
        summary_text TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
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

    ensure_column(conn, "papers", "published_doi", "TEXT")
    ensure_column(conn, "papers", "published_journal", "TEXT")
    ensure_column(conn, "papers", "published_article_date", "TEXT")
    ensure_column(conn, "papers", "preprint_platform", "TEXT")
    ensure_column(conn, "papers", "summary_text", "TEXT")
    ensure_column(conn, "papers", "updated_at", "TEXT DEFAULT CURRENT_TIMESTAMP")

    conn.execute("""
    CREATE TABLE IF NOT EXISTS authors (
        id INTEGER PRIMARY KEY,
        canonical_name TEXT NOT NULL,
        canonical_name_norm TEXT NOT NULL,
        family_name TEXT,
        given_names TEXT,
        initials TEXT,
        orcid TEXT,
        primary_affiliation TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(orcid)
    )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_authors_name_norm ON authors(canonical_name_norm)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_authors_orcid ON authors(orcid)")

    conn.execute("""
    CREATE TABLE IF NOT EXISTS author_names (
        id INTEGER PRIMARY KEY,
        author_id INTEGER NOT NULL REFERENCES authors(id) ON DELETE CASCADE,
        display_name TEXT NOT NULL,
        normalized_name TEXT NOT NULL,
        name_type TEXT NOT NULL,
        source TEXT,
        is_preferred INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(author_id, normalized_name, name_type)
    )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_author_names_norm ON author_names(normalized_name)")

    conn.execute("""
    CREATE TABLE IF NOT EXISTS paper_authors (
        paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
        author_id INTEGER NOT NULL REFERENCES authors(id) ON DELETE CASCADE,
        author_position INTEGER NOT NULL,
        is_corresponding INTEGER NOT NULL DEFAULT 0,
        affiliation_text TEXT,
        author_role TEXT,
        source_confidence REAL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (paper_id, author_id),
        UNIQUE(paper_id, author_position)
    )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_authors_author ON paper_authors(author_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_authors_paper ON paper_authors(paper_id)")

    conn.execute("""
    CREATE TABLE IF NOT EXISTS author_external_ids (
        id INTEGER PRIMARY KEY,
        author_id INTEGER NOT NULL REFERENCES authors(id) ON DELETE CASCADE,
        source TEXT NOT NULL,
        external_id TEXT NOT NULL,
        id_type TEXT NOT NULL,
        is_verified INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(source, external_id),
        UNIQUE(author_id, source, id_type, external_id)
    )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_author_external_ids_author ON author_external_ids(author_id)")

    conn.execute("""
    CREATE TABLE IF NOT EXISTS author_expansion_jobs (
        id INTEGER PRIMARY KEY,
        author_id INTEGER NOT NULL REFERENCES authors(id),
        source TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'queued',
        started_at TEXT,
        finished_at TEXT,
        query_text TEXT,
        result_count INTEGER DEFAULT 0,
        papers_inserted INTEGER DEFAULT 0,
        papers_updated INTEGER DEFAULT 0,
        error_text TEXT
    )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_author_expansion_jobs_author ON author_expansion_jobs(author_id)")

    conn.execute("""
    CREATE TABLE IF NOT EXISTS external_records (
        id INTEGER PRIMARY KEY,
        source TEXT NOT NULL,
        source_record_id TEXT NOT NULL,
        author_id INTEGER REFERENCES authors(id),
        raw_json_path TEXT NOT NULL,
        title TEXT,
        doi TEXT,
        pmid TEXT,
        published_at TEXT,
        journal TEXT,
        import_status TEXT NOT NULL DEFAULT 'staged',
        matched_paper_id INTEGER REFERENCES papers(id),
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(source, source_record_id)
    )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_external_records_author ON external_records(author_id)")

    conn.execute("""
    CREATE VIRTUAL TABLE IF NOT EXISTS papers_fts USING fts5(
        title,
        abstract,
        summary_text,
        content='papers',
        content_rowid='id'
    )
    """)

    conn.execute("DROP TRIGGER IF EXISTS papers_ai")
    conn.execute("DROP TRIGGER IF EXISTS papers_ad")
    conn.execute("DROP TRIGGER IF EXISTS papers_au")
    conn.execute("""
    CREATE TRIGGER IF NOT EXISTS papers_ai AFTER INSERT ON papers BEGIN
        INSERT INTO papers_fts(rowid, title, abstract, summary_text)
        VALUES (new.id, new.title, new.abstract, new.summary_text);
    END;
    """)
    conn.execute("""
    CREATE TRIGGER IF NOT EXISTS papers_ad AFTER DELETE ON papers BEGIN
        INSERT INTO papers_fts(papers_fts, rowid, title, abstract, summary_text)
        VALUES ('delete', old.id, old.title, old.abstract, old.summary_text);
    END;
    """)
    conn.execute("""
    CREATE TRIGGER IF NOT EXISTS papers_au AFTER UPDATE ON papers BEGIN
        INSERT INTO papers_fts(papers_fts, rowid, title, abstract, summary_text)
        VALUES ('delete', old.id, old.title, old.abstract, old.summary_text);
        INSERT INTO papers_fts(rowid, title, abstract, summary_text)
        VALUES (new.id, new.title, new.abstract, new.summary_text);
    END;
    """)

    count = conn.execute("SELECT COUNT(*) FROM papers_fts").fetchone()[0]
    if count == 0:
        conn.execute("""
        INSERT INTO papers_fts(rowid, title, abstract, summary_text)
        SELECT id, title, abstract, summary_text
        FROM papers
        """)

    conn.commit()
