from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def authors_text(conn: sqlite3.Connection, paper_id: int, fallback: str | None = None) -> str:
    rows = conn.execute(
        """
        SELECT a.canonical_name
        FROM paper_authors pa
        JOIN authors a ON a.id = pa.author_id
        WHERE pa.paper_id = ?
        ORDER BY pa.author_position ASC, a.canonical_name ASC
        """,
        (paper_id,),
    ).fetchall()
    return "; ".join(row[0] for row in rows) if rows else (fallback or "")


def md_table(rows, columns):
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
                vals.append(str(value).replace("\n", " ").replace("|", r"\\|"))
        body.append("| " + " | ".join(vals) + " |")
    return "\n".join([header, sep] + body)


def render_recent_structured_summaries_inline(conn: sqlite3.Connection, rows) -> str:
    if not rows:
        return "_None._"
    parts = []
    for row in rows:
        title = row["title"] or "Untitled"
        authors = authors_text(conn, int(row["paper_id"]), row["authors"])
        try:
            data = json.loads(row["summary_json"] or "{}")
        except json.JSONDecodeError:
            data = {}
        rq = data.get("research_question", "") or ""
        ms = data.get("model_system", "") or ""
        methods = data.get("methods", []) or []
        findings = data.get("main_findings", []) or []
        limitations = data.get("limitations", []) or []
        keywords = data.get("keywords", []) or []
        line = f"**{title}**"
        if authors:
            line += f" — {authors}"
        if rq:
            line += f" — Q: {rq}"
        if ms:
            line += f" — Model: {ms}"
        if methods:
            line += f" — Methods: {', '.join(methods[:3])}"
        if findings:
            line += f" — Findings: {', '.join(findings[:2])}"
        if limitations:
            line += f" — Limits: {', '.join(limitations[:2])}"
        if keywords:
            line += f" — Keywords: {', '.join(keywords[:5])}"
        parts.append(f"- {line}")
    return "\n".join(parts)


def generate_digest(conn: sqlite3.Connection) -> str:
    conn.row_factory = sqlite3.Row
    integrity = conn.execute("PRAGMA integrity_check;").fetchone()[0]
    total_papers = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
    with_doi = conn.execute("SELECT COUNT(*) FROM papers WHERE doi IS NOT NULL AND doi != ''").fetchone()[0]
    with_abstract = conn.execute("SELECT COUNT(*) FROM papers WHERE abstract IS NOT NULL AND abstract != ''").fetchone()[0]
    with_summary = conn.execute("SELECT COUNT(*) FROM papers WHERE summary IS NOT NULL AND summary != ''").fetchone()[0]
    total_summaries = conn.execute("SELECT COUNT(*) FROM summaries").fetchone()[0]
    with_published_version = conn.execute("SELECT COUNT(*) FROM papers WHERE published_doi IS NOT NULL AND published_doi != ''").fetchone()[0]

    last_24h_papers = conn.execute("""
        SELECT id, COALESCE(title, '') AS title, COALESCE(doi, '') AS doi,
               COALESCE(published_date, '') AS published_date, created_at
        FROM papers
        WHERE datetime(created_at) >= datetime('now', '-1 day')
        ORDER BY datetime(created_at) DESC
    """).fetchall()
    last_24h_summaries = conn.execute("""
        SELECT s.id, s.paper_id, COALESCE(p.title, '') AS title,
               s.model_name, s.prompt_version, s.created_at
        FROM summaries s
        LEFT JOIN papers p ON p.id = s.paper_id
        WHERE datetime(s.created_at) >= datetime('now', '-1 day')
        ORDER BY datetime(s.created_at) DESC
    """).fetchall()
    recent_structured = conn.execute("""
        SELECT s.created_at, s.paper_id, COALESCE(p.title, '') AS title,
               COALESCE(p.authors, '') AS authors, s.summary_json
        FROM summaries s
        JOIN papers p ON p.id = s.paper_id
        WHERE datetime(s.created_at) >= datetime('now', '-1 day')
        ORDER BY datetime(s.created_at) DESC
    """).fetchall()
    published_versions = conn.execute("""
        SELECT COALESCE(doi, '') AS preprint_doi, COALESCE(title, '') AS title,
               COALESCE(published_doi, '') AS published_doi,
               COALESCE(published_journal, '') AS published_journal,
               COALESCE(published_article_date, '') AS published_article_date
        FROM papers
        WHERE published_doi IS NOT NULL AND published_doi != ''
        ORDER BY datetime(COALESCE(published_article_date, created_at)) DESC
        LIMIT 30
    """).fetchall()
    duplicate_doi = conn.execute("""
        SELECT doi, COUNT(*) AS n
        FROM papers
        WHERE doi IS NOT NULL AND doi != ''
        GROUP BY doi
        HAVING n > 1
        ORDER BY n DESC, doi
        LIMIT 50
    """).fetchall()
    missing_identity = conn.execute("""
        SELECT id, COALESCE(title, '') AS title
        FROM papers
        WHERE (doi IS NULL OR doi = '') AND (link IS NULL OR link = '')
        ORDER BY id DESC
        LIMIT 50
    """).fetchall()
    unenriched = conn.execute("""
        SELECT id, COALESCE(title, '') AS title
        FROM papers
        WHERE abstract IS NULL OR abstract = ''
        ORDER BY id DESC
        LIMIT 50
    """).fetchall()
    orphan_summaries = conn.execute("""
        SELECT s.id, s.paper_id, s.model_name, s.prompt_version
        FROM summaries s
        LEFT JOIN papers p ON p.id = s.paper_id
        WHERE p.id IS NULL
        ORDER BY s.id DESC
        LIMIT 50
    """).fetchall()

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    parts = [
        f"# Literature pipeline digest\n",
        f"_Generated: {now}_\n",
        f"## Status\n",
        f"- Integrity check: **{integrity}**",
        f"- Total papers: **{total_papers}**",
        f"- Papers with DOI: **{with_doi}**",
        f"- Papers with abstract: **{with_abstract}**",
        f"- Papers with summary: **{with_summary}**",
        f"- Papers with published version: **{with_published_version}**",
        f"- Summary rows: **{total_summaries}**\n",
        f"## Papers added in the last 24 hours\n",
        md_table(last_24h_papers, ["id", "title", "doi", "published_date", "created_at"]),
        f"\n## Summaries created in the last 24 hours\n",
        md_table(last_24h_summaries, ["id", "paper_id", "title", "model_name", "prompt_version", "created_at"]),
        f"\n## Recent structured summaries\n",
        render_recent_structured_summaries_inline(conn, recent_structured),
        f"\n## Published versions found\n",
        md_table(published_versions, ["preprint_doi", "title", "published_doi", "published_journal", "published_article_date"]),
        f"\n## Attention needed\n",
        f"- Duplicate DOI rows: **{len(duplicate_doi)}**",
        f"- Missing identity rows: **{len(missing_identity)}**",
        f"- Unenriched papers: **{len(unenriched)}**",
        f"- Orphan summaries: **{len(orphan_summaries)}**\n",
        f"### Duplicate DOI\n",
        md_table(duplicate_doi, ["doi", "n"]),
        f"\n### Missing identity\n",
        md_table(missing_identity, ["id", "title"]),
        f"\n### Unenriched papers\n",
        md_table(unenriched, ["id", "title"]),
        f"\n### Orphan summaries\n",
        md_table(orphan_summaries, ["id", "paper_id", "model_name", "prompt_version"]),
        f"\n",
    ]
    return "\n".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("db", type=Path, help="Path to SQLite database")
    parser.add_argument("--out", type=Path, default=Path(f"output/digest-{datetime.now().strftime('%Y-%m-%d')}.md"), help="Path to output markdown file")
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
