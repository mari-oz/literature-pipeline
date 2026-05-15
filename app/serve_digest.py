from __future__ import annotations

import argparse
import html
import json
import sqlite3
import traceback
from datetime import datetime, timezone
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote, urlsplit

CSS = """
:root {
  --bg: #0f1115;
  --panel: #171a21;
  --text: #e8ecf1;
  --muted: #9aa4b2;
  --border: #313845;
  --accent: #58a6ff;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: Inter, system-ui, sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.6;
}
.container {
  max-width: 980px;
  margin: 0 auto;
  padding: 32px 20px 48px;
}
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
h1, h2, h3 { line-height: 1.2; margin-top: 1.6em; }
h1 { margin-top: 0; }
p, li { color: var(--text); }
code, pre {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
code {
  background: #1f2430;
  padding: 0.15em 0.35em;
  border-radius: 6px;
}
pre {
  background: #11161d;
  border: 1px solid var(--border);
  padding: 14px;
  border-radius: 10px;
  overflow-x: auto;
}
table {
  width: 100%;
  border-collapse: collapse;
  margin: 1rem 0 1.5rem;
  background: var(--panel);
}
th, td {
  border: 1px solid var(--border);
  padding: 10px 12px;
  text-align: left;
  vertical-align: top;
}
th { background: #1f2430; }
blockquote {
  border-left: 4px solid var(--accent);
  margin: 1rem 0;
  padding: 0.2rem 1rem;
  color: var(--muted);
}
hr {
  border: none;
  border-top: 1px solid var(--border);
  margin: 2rem 0;
}
.small { color: var(--muted); font-size: 0.95rem; }
ul.file-list { padding-left: 1.2rem; }
"""

def inline_format(text: str) -> str:
    text = html.escape(text)
    text = text.replace("**", "�")
    parts = text.split("�")
    for i in range(1, len(parts), 2):
        parts[i] = f"<strong>{parts[i]}</strong>"
    text = "".join(parts)
    text = text.replace("*", "")
    parts = text.split("")
    for i in range(1, len(parts), 2):
        parts[i] = f"<em>{parts[i]}</em>"
    return "".join(parts)


def markdown_to_html(md: str) -> str:
    lines = md.splitlines()
    out: list[str] = []
    in_list = False
    in_code = False
    in_table = False
    table_lines: list[str] = []

    def flush_table() -> None:
        nonlocal in_table, table_lines
        if not table_lines:
            return
        rows = []
        for line in table_lines:
            parts = [p.strip() for p in line.strip().strip("|").split("|")]
            rows.append(parts)
        if len(rows) >= 2:
            header = rows[0]
            body = rows[2:] if len(rows) > 2 else []
            out.append("<table>")
            out.append("<thead><tr>" + "".join(f"<th>{inline_format(c)}</th>" for c in header) + "</tr></thead>")
            out.append("<tbody>")
            for row in body:
                out.append("<tr>" + "".join(f"<td>{inline_format(c)}</td>" for c in row) + "</tr>")
            out.append("</tbody></table>")
        table_lines = []
        in_table = False

    for line in lines:
        stripped = line.rstrip()
        if stripped.startswith("```"):
            if in_table:
                flush_table()
            if in_list:
                out.append("</ul>")
                in_list = False
            if not in_code:
                out.append("<pre><code>")
                in_code = True
            else:
                out.append("</code></pre>")
                in_code = False
            continue
        if in_code:
            out.append(html.escape(line))
            continue
        if stripped.startswith("|") and stripped.endswith("|"):
            if in_list:
                out.append("</ul>")
                in_list = False
            in_table = True
            table_lines.append(stripped)
            continue
        elif in_table:
            flush_table()
        if not stripped:
            if in_list:
                out.append("</ul>")
                in_list = False
            continue
        if stripped.startswith("# "):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<h1>{inline_format(stripped[2:].strip())}</h1>")
        elif stripped.startswith("## "):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<h2>{inline_format(stripped[3:].strip())}</h2>")
        elif stripped.startswith("### "):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<h3>{inline_format(stripped[4:].strip())}</h3>")
        elif stripped == "---":
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append("<hr>")
        elif stripped.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline_format(stripped[2:].strip())}</li>")
        else:
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<p>{inline_format(stripped)}</p>")
    if in_table:
        flush_table()
    if in_list:
        out.append("</ul>")
    if in_code:
        out.append("</code></pre>")
    return "
".join(out)


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
    if rows:
        return "; ".join(row[0] for row in rows)
    return fallback or ""


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
            vals.append("") if value is None else vals.append(str(value).replace("
", " ").replace("|", "\|"))
        body.append("| " + " | ".join(vals) + " |")
    return "
".join([header, sep] + body)


def fetchall(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    return conn.execute(sql, params).fetchall()


def scalar(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def render_recent_structured_summaries(conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> str:
    if not rows:
        return "_None._"
    parts: list[str] = []
    for row in rows:
        title = row["title"] or ""
        created_at = row["created_at"] or ""
        raw = row["summary_json"] or "{}"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            parts.append(f"### {title}
- Created: {created_at}
- Structured summary could not be parsed.
")
            continue
        authors = authors_text(conn, int(row["paper_id"]), row["authors"])
        parts.append(f"### {title}")
        if authors:
            parts.append(f"- Authors: {authors}")
        parts.append(f"- Created: {created_at}")
        rq = data.get("research_question", "") or ""
        ms = data.get("model_system", "") or ""
        methods = data.get("methods", []) or []
        findings = data.get("main_findings", []) or []
        limitations = data.get("limitations", []) or []
        keywords = data.get("keywords", []) or []
        if rq:
            parts.append(f"- Research question: {rq}")
        if ms:
            parts.append(f"- Model system: {ms}")
        if methods:
            parts.append(f"- Methods: {', '.join(methods[:5])}")
        if findings:
            parts.append("- Main findings:")
            parts.extend(f"  - {item}" for item in findings[:3])
        if limitations:
            parts.append("- Limitations:")
            parts.extend(f"  - {item}" for item in limitations[:2])
        if keywords:
            parts.append(f"- Keywords: {', '.join(keywords[:8])}")
        parts.append("")
    return "
".join(parts)


def generate_digest(conn: sqlite3.Connection) -> str:
    conn.row_factory = sqlite3.Row
    integrity = conn.execute("PRAGMA integrity_check;").fetchone()[0]
    total_papers = scalar(conn, "SELECT COUNT(*) FROM papers")
    with_doi = scalar(conn, "SELECT COUNT(*) FROM papers WHERE doi IS NOT NULL AND doi != ''")
    with_abstract = scalar(conn, "SELECT COUNT(*) FROM papers WHERE abstract IS NOT NULL AND abstract != ''")
    with_summary = scalar(conn, "SELECT COUNT(*) FROM papers WHERE summary IS NOT NULL AND summary != ''")
    total_summaries = scalar(conn, "SELECT COUNT(*) FROM summaries")
    with_published_version = scalar(conn, "SELECT COUNT(*) FROM papers WHERE published_doi IS NOT NULL AND published_doi != ''")

    last_24h_papers = fetchall(conn, """
        SELECT id, COALESCE(title, '') AS title, COALESCE(doi, '') AS doi,
               COALESCE(published_date, '') AS published_date, created_at
        FROM papers
        WHERE datetime(created_at) >= datetime('now', '-1 day')
        ORDER BY datetime(created_at) DESC
    """)
    last_24h_summaries = fetchall(conn, """
        SELECT s.id, s.paper_id, COALESCE(p.title, '') AS title,
               s.model_name, s.prompt_version, s.created_at
        FROM summaries s
        LEFT JOIN papers p ON p.id = s.paper_id
        WHERE datetime(s.created_at) >= datetime('now', '-1 day')
        ORDER BY datetime(s.created_at) DESC
    """)
    recent_structured = fetchall(conn, """
        SELECT s.created_at, s.paper_id, COALESCE(p.title, '') AS title,
               COALESCE(p.authors, '') AS authors, s.summary_json
        FROM summaries s
        JOIN papers p ON p.id = s.paper_id
        WHERE datetime(s.created_at) >= datetime('now', '-1 day')
        ORDER BY datetime(s.created_at) DESC
    """)
    published_versions = fetchall(conn, """
        SELECT COALESCE(doi, '') AS preprint_doi, COALESCE(title, '') AS title,
               COALESCE(published_doi, '') AS published_doi,
               COALESCE(published_journal, '') AS published_journal,
               COALESCE(published_article_date, '') AS published_article_date
        FROM papers
        WHERE published_doi IS NOT NULL AND published_doi != ''
        ORDER BY datetime(COALESCE(published_article_date, created_at)) DESC
        LIMIT 30
    """)
    duplicate_doi = fetchall(conn, """
        SELECT doi, COUNT(*) AS n
        FROM papers
        WHERE doi IS NOT NULL AND doi != ''
        GROUP BY doi
        HAVING n > 1
        ORDER BY n DESC, doi
        LIMIT 50
    """)
    missing_identity = fetchall(conn, """
        SELECT id, COALESCE(title, '') AS title
        FROM papers
        WHERE (doi IS NULL OR doi = '') AND (link IS NULL OR link = '')
        ORDER BY id DESC
        LIMIT 50
    """)
    unenriched = fetchall(conn, """
        SELECT id, COALESCE(title, '') AS title
        FROM papers
        WHERE abstract IS NULL OR abstract = ''
        ORDER BY id DESC
        LIMIT 50
    """)
    orphan_summaries = fetchall(conn, """
        SELECT s.id, s.paper_id, s.model_name, s.prompt_version
        FROM summaries s
        LEFT JOIN papers p ON p.id = s.paper_id
        WHERE p.id IS NULL
        ORDER BY s.id DESC
        LIMIT 50
    """)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    parts: list[str] = []
    parts.append("# Literature pipeline digest
")
    parts.append(f"_Generated: {now}_
")
    parts.append("## Status
")
    parts.append(f"- Integrity check: **{integrity}**")
    parts.append(f"- Total papers: **{total_papers}**")
    parts.append(f"- Papers with DOI: **{with_doi}**")
    parts.append(f"- Papers with abstract: **{with_abstract}**")
    parts.append(f"- Papers with summary: **{with_summary}**")
    parts.append(f"- Papers with published version: **{with_published_version}**")
    parts.append(f"- Summary rows: **{total_summaries}**
")
    parts.append("## Papers added in the last 24 hours
")
    parts.append(md_table(last_24h_papers, ["id", "title", "doi", "published_date", "created_at"]))
    parts.append("
## Summaries created in the last 24 hours
")
    parts.append(md_table(last_24h_summaries, ["id", "paper_id", "title", "model_name", "prompt_version", "created_at"]))
    parts.append("
## Recent structured summaries
")
    parts.append(render_recent_structured_summaries(conn, recent_structured))
    parts.append("
## Published versions found
")
    parts.append(md_table(published_versions, ["preprint_doi", "title", "published_doi", "published_journal", "published_article_date"]))
    parts.append("
## Attention needed
")
    parts.append(f"- Duplicate DOI rows: **{len(duplicate_doi)}**")
    parts.append(f"- Missing identity rows: **{len(missing_identity)}**")
    parts.append(f"- Unenriched papers: **{len(unenriched)}**")
    parts.append(f"- Orphan summaries: **{len(orphan_summaries)}**
")
    parts.append("### Duplicate DOI
")
    parts.append(md_table(duplicate_doi, ["doi", "n"]))
    parts.append("
### Missing identity
")
    parts.append(md_table(missing_identity, ["id", "title"]))
    parts.append("
### Unenriched papers
")
    parts.append(md_table(unenriched, ["id", "title"]))
    parts.append("
### Orphan summaries
")
    parts.append(md_table(orphan_summaries, ["id", "paper_id", "model_name", "prompt_version"]))
    parts.append("
")
    return "
".join(parts)


class DigestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory: str | None = None, **kwargs):
        super().__init__(*args, directory=directory, **kwargs)

    def do_HEAD(self):
        self._dispatch(head_only=True)

    def do_GET(self):
        self._dispatch(head_only=False)

    def _dispatch(self, head_only: bool = False):
        try:
            path = unquote(urlsplit(self.path).path)
            if path == "/favicon.ico":
                return self._send_bytes(204, "image/x-icon", b"", head_only)
            if path in ("/", ""):
                return self.render_index(head_only=head_only)
            full = (Path(self.directory) / path.lstrip("/")).resolve()
            base = Path(self.directory).resolve()
            if not str(full).startswith(str(base)):
                return self.send_error(403, "Forbidden")
            if full.is_file() and full.suffix.lower() == ".md":
                return self.render_markdown(full, head_only=head_only)
            return super().do_HEAD() if head_only else super().do_GET()
        except Exception:
            traceback.print_exc()
            return self._send_bytes(500, "text/html; charset=utf-8", b"<html><body><h1>Error</h1></body></html>", head_only)

    def _send_bytes(self, status: int, content_type: str, data: bytes, head_only: bool = False):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if not head_only:
            self.wfile.write(data)

    def render_index(self, head_only: bool = False):
        base = Path(self.directory)
        files = sorted(base.glob("*.md"), reverse=True)
        items = "
".join(f'<li><a href="/{f.name}">{html.escape(f.name)}</a></li>' for f in files)
        html_doc = f"<html><head><style>{CSS}</style><title>Digests</title></head><body><div class='container'><h1>Digests</h1><ul class='file-list'>{items}</ul></div></body></html>"
        return self._send_bytes(200, "text/html; charset=utf-8", html_doc.encode("utf-8"), head_only)

    def render_markdown(self, full: Path, head_only: bool = False):
        md = full.read_text(encoding="utf-8")
        body = markdown_to_html(md)
        html_doc = f"<html><head><style>{CSS}</style><title>{html.escape(full.name)}</title></head><body><div class='container'><p class='small'><a href='/'>â† index</a></p>{body}</div></body></html>"
        return self._send_bytes(200, "text/html; charset=utf-8", html_doc.encode("utf-8"), head_only)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", default="/data/digests")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    server = HTTPServer(("0.0.0.0", args.port), lambda *a, **kw: DigestHandler(*a, directory=args.directory, **kw))
    server.serve_forever()


if __name__ == "__main__":
    main()
