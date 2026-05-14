from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def fetchall(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    cur = conn.execute(sql, params)
    return cur.fetchall()


def scalar(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def md_table(rows: list[sqlite3.Row], columns: list[str]) -> str:
    if not rows:
        return "_None._"

    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join(["---"] * len(columns)) + " |"
    body = []
    for row in rows:
        vals = []
        for col in columns:
            value = row[col]
            if value is None:
                vals.append("")
            else:
                text = str(value).replace("\n", " ").replace("|", "\\|")
                vals.append(text)
        body.append("| " + " | ".join(vals) + " |")
    return "\n".join([header, sep] + body)


def generate_digest(conn: sqlite3.Connection) -> str:
    integrity = conn.execute("PRAGMA integrity_check;").fetchone()[0]

    total_papers = scalar(conn, "SELECT COUNT(*) FROM papers")
    with_doi = scalar(conn, "SELECT COUNT(*) FROM papers WHERE doi IS NOT NULL AND doi != ''")
    with_abstract = scalar(conn, "SELECT COUNT(*) FROM papers WHERE abstract IS NOT NULL AND abstract != ''")
    with_summary = scalar(conn, "SELECT COUNT(*) FROM papers WHERE summary IS NOT NULL AND summary != ''")
    total_summaries = scalar(conn, "SELECT COUNT(*) FROM summaries")

    last_24h_papers = fetchall(
        conn,
        """
        SELECT
            id,
            COALESCE(title, '') AS title,
            substr(COALESCE(doi, ''), 1, 40) AS doi,
            substr(COALESCE(published_date, ''), 1, 19) AS published_date,
            created_at
        FROM papers
        WHERE datetime(created_at) >= datetime('now', '-1 day')
        ORDER BY datetime(created_at) DESC
        """,
    )

    last_24h_summaries = fetchall(
        conn,
        """
        SELECT
            s.id,
            s.paper_id,
            substr(COALESCE(p.title, ''), 1, 100) AS title,
            s.model_name,
            s.prompt_version,
            s.created_at
        FROM summaries s
        LEFT JOIN papers p ON p.id = s.paper_id
        WHERE datetime(s.created_at) >= datetime('now', '-1 day')
        ORDER BY datetime(s.created_at) DESC
        """,
    )

    duplicate_doi = fetchall(
        conn,
        """
        SELECT doi, COUNT(*) AS n
        FROM papers
        WHERE doi IS NOT NULL AND doi != ''
        GROUP BY doi
        HAVING n > 1
        ORDER BY n DESC, doi
        LIMIT 50
        """,
    )

    missing_identity = fetchall(
        conn,
        """
        SELECT id, substr(COALESCE(title, ''), 1, 100) AS title
        FROM papers
        WHERE (doi IS NULL OR doi = '')
          AND (link IS NULL OR link = '')
        ORDER BY id DESC
        LIMIT 50
        """,
    )

    unenriched = fetchall(
        conn,
        """
        SELECT id, substr(COALESCE(title, ''), 1, 100) AS title
        FROM papers
        WHERE abstract IS NULL OR abstract = ''
        ORDER BY id DESC
        LIMIT 50
        """,
    )

    orphan_summaries = fetchall(
        conn,
        """
        SELECT s.id, s.paper_id, s.model_name, s.prompt_version
        FROM summaries s
        LEFT JOIN papers p ON p.id = s.paper_id
        WHERE p.id IS NULL
        ORDER BY s.id DESC
        LIMIT 50
        """,
    )

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    parts: list[str] = []
    parts.append("# Literature pipeline digest\n")
    parts.append(f"_Generated: {now}_\n")

    parts.append("## Status\n")
    parts.append(f"- Integrity check: **{integrity}**")
    parts.append(f"- Total papers: **{total_papers}**")
    parts.append(f"- Papers with DOI: **{with_doi}**")
    parts.append(f"- Papers with abstract: **{with_abstract}**")
    parts.append(f"- Papers with summary: **{with_summary}**")
    parts.append(f"- Summary rows: **{total_summaries}**\n")

    parts.append("## Papers added in the last 24 hours\n")
    parts.append(md_table(last_24h_papers, ["id", "title", "doi", "published_date", "created_at"]))
    parts.append("\n")

    parts.append("## Summaries created in the last 24 hours\n")
    parts.append(md_table(last_24h_summaries, ["id", "paper_id", "title", "model_name", "prompt_version", "created_at"]))
    parts.append("\n")

    parts.append("## Attention needed\n")
    parts.append(f"- Duplicate DOI rows: **{len(duplicate_doi)}**")
    parts.append(f"- Missing identity rows: **{len(missing_identity)}**")
    parts.append(f"- Unenriched papers: **{len(unenriched)}**")
    parts.append(f"- Orphan summaries: **{len(orphan_summaries)}**\n")

    parts.append("### Duplicate DOI\n")
    parts.append(md_table(duplicate_doi, ["doi", "n"]))
    parts.append("\n")

    parts.append("### Missing identity\n")
    parts.append(md_table(missing_identity, ["id", "title"]))
    parts.append("\n")

    parts.append("### Unenriched papers\n")
    parts.append(md_table(unenriched, ["id", "title"]))
    parts.append("\n")

    parts.append("### Orphan summaries\n")
    parts.append(md_table(orphan_summaries, ["id", "paper_id", "model_name", "prompt_version"]))
    parts.append("\n")

    return "\n".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("db", type=Path, help="Path to SQLite database")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(f"output/digest-{datetime.now().strftime('%Y-%m-%d')}.md"),
        help="Path to output markdown file",
    )
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        digest = generate_digest(conn)
    finally:
        conn.close()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(digest, encoding="utf-8")
    print(args.out)


if __name__ == "__main__":
    main()
