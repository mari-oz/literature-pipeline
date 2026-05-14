import sqlite3


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row[1] == column for row in rows)


def migrate(conn: sqlite3.Connection) -> None:
    if not _column_exists(conn, 'papers', 'summary_text'):
        conn.execute('ALTER TABLE papers ADD COLUMN summary_text TEXT')

    conn.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS papers_fts USING fts5(
            title,
            abstract,
            summary_text,
            content='papers',
            content_rowid='id'
        )
        """
    )

    conn.executescript(
        """
        CREATE TRIGGER IF NOT EXISTS papers_ai AFTER INSERT ON papers BEGIN
            INSERT INTO papers_fts(rowid, title, abstract, summary_text)
            VALUES (new.id, new.title, new.abstract, new.summary_text);
        END;

        CREATE TRIGGER IF NOT EXISTS papers_ad AFTER DELETE ON papers BEGIN
            INSERT INTO papers_fts(papers_fts, rowid, title, abstract, summary_text)
            VALUES('delete', old.id, old.title, old.abstract, old.summary_text);
        END;

        CREATE TRIGGER IF NOT EXISTS papers_au AFTER UPDATE ON papers BEGIN
            INSERT INTO papers_fts(papers_fts, rowid, title, abstract, summary_text)
            VALUES('delete', old.id, old.title, old.abstract, old.summary_text);
            INSERT INTO papers_fts(rowid, title, abstract, summary_text)
            VALUES (new.id, new.title, new.abstract, new.summary_text);
        END;
        """
    )

    fts_count = conn.execute('SELECT count(*) FROM papers_fts').fetchone()[0]
    if fts_count == 0:
        conn.execute(
            """
            INSERT INTO papers_fts(rowid, title, abstract, summary_text)
            SELECT id, title, abstract, summary_text
            FROM papers
            """
        )

    conn.commit()


if __name__ == '__main__':
    conn = sqlite3.connect('/data/pipeline.db')
    try:
        migrate(conn)
        print('FTS5 migration complete')
    finally:
        conn.close()
