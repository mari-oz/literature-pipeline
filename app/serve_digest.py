from __future__ import annotations

import argparse
import html
import json
import sqlite3
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
    text = text.replace("**", "\u0000")
    parts = text.split("\u0000")
    for i in range(1, len(parts), 2):
        parts[i] = f"<strong>{parts[i]}</strong>"
    text = "".join(parts)
    text = text.replace("*", "\u0001")
    parts = text.split("\u0001")
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
    return "\n".join(out)

def authors_text(conn: sqlite3.Connection, paper_id: int, fallback: str | None = None) -> str:
    cols = [row for row in conn.execute("PRAGMA table_info(paper_authors)").fetchall()][1]
    select_cols = ["COALESCE(a.canonical_name, '') AS name"]
    if "author_name" in cols:
        select_cols.insert(0, "pa.author_name")
    if "display_name" in cols:
        select_cols.insert(0, "pa.display_name")
    if "raw_name" in cols:
        select_cols.insert(0, "pa.raw_name")
    query = f"""
        SELECT {', '.join(select_cols)}
        FROM paper_authors pa
        LEFT JOIN authors a ON a.id = pa.author_id
        WHERE pa.paper_id = ?
        ORDER BY pa.author_position ASC
    """
    rows = conn.execute(query, (paper_id,)).fetchall()
    names = []
    for row in rows:
        vals = [str(v) for v in row if v]
        if vals:
            names.append(vals)
    return "; ".join(names) if names else (fallback or "")

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
                vals.append(str(value).replace("\n", " ").replace("|", r"\|"))
        body.append("| " + " | ".join(vals) + " |")
    return "\n".join([header, sep] + body)

def render_recent_structured_summaries(conn, rows):
    if not rows:
        return "_None._"
    parts = []
    for row in rows:
        title = row["title"] or ""
        created_at = row["created_at"] or ""
        try:
            data = json.loads(row["summary_json"] or "{}")
        except json.JSONDecodeError:
            parts.append(f"### {title}\n- Created: {created_at}\n- Structured summary could not be parsed.\n")
            continue
        auth = authors_text(conn, int(row["paper_id"]), row["authors"])
        parts.append(f"### {title}")
        if auth:
            parts.append(f"- Authors: {auth}")
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
    return "\n".join(parts)

def generate_digest(conn):
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
        render_recent_structured_summaries(conn, recent_structured),
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
    parser.add_argument("db", nargs="?", type=Path, default=Path("/data/pipeline.db"), help="Path to SQLite database")
    parser.add_argument("--out", type=Path, default=Path(f"output/digest-{datetime.now().strftime('%Y-%m-%d')}.md"), help="Path to output markdown file")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--dir", dest="directory", default="/data/digests")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        digest = generate_digest(conn)
    finally:
        conn.close()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(digest, encoding="utf-8")

    base_dir = Path(args.directory)
    base_dir.mkdir(parents=True, exist_ok=True)
    if args.out.parent.resolve() != base_dir.resolve():
        target = base_dir / args.out.name
        target.write_text(digest, encoding="utf-8")

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, directory: str | None = None, **kw):
            super().__init__(*a, directory=directory, **kw)

        def do_GET(self):
            path = unquote(urlsplit(self.path).path)
            if path in ("/", ""):
                files = sorted(Path(self.directory).glob("*.md"), reverse=True)
                items = "\n".join(f'<li><a href="/{f.name}">{html.escape(f.name)}</a></li>' for f in files)
                body = f"<html><head><style>{CSS}</style><title>Digests</title></head><body><div class='container'><h1>Digests</h1><ul class='file-list'>{items}</ul></div></body></html>"
                data = body.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            full = (Path(self.directory) / path.lstrip("/")).resolve()
            if full.is_file() and full.suffix.lower() == ".md":
                md = full.read_text(encoding="utf-8")
                body = f"<html><head><style>{CSS}</style><title>{html.escape(full.name)}</title></head><body><div class='container'>{markdown_to_html(md)}</div></body></html>"
                data = body.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            return super().do_GET()

    server = HTTPServer((args.host, args.port), lambda *a, **kw: Handler(*a, directory=str(base_dir), **kw))
    print(f"Serving {base_dir} on http://{args.host}:{args.port}")
    server.serve_forever()

if __name__ == "__main__":
    main()
