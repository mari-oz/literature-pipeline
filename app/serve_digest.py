from __future__ import annotations

import argparse
import html
import traceback
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
    text = "".join(parts)

    return text


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
                padded = row + [""] * (len(header) - len(row))
                out.append("<tr>" + "".join(f"<td>{inline_format(c)}</td>" for c in padded[:len(header)]) + "</tr>")
            out.append("</tbody></table>")
        else:
            for line in table_lines:
                out.append(f"<p>{inline_format(line)}</p>")

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
            out.append(f"<h1>{inline_format(stripped[2:])}</h1>")
        elif stripped.startswith("## "):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<h2>{inline_format(stripped[3:])}</h2>")
        elif stripped.startswith("### "):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<h3>{inline_format(stripped[4:])}</h3>")
        elif stripped.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline_format(stripped[2:])}</li>")
        elif stripped.startswith("> "):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<blockquote><p>{inline_format(stripped[2:])}</p></blockquote>")
        elif stripped == "---":
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append("<hr>")
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
                return self._send_bytes(
                    status=204,
                    content_type="image/x-icon",
                    data=b"",
                    head_only=head_only,
                )

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
            error_html = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Server error</title>
<style>body{font-family:system-ui,sans-serif;background:#111;color:#eee;padding:2rem;line-height:1.5}pre{white-space:pre-wrap;background:#1b1b1b;padding:1rem;border-radius:8px}</style>
</head>
<body>
<h1>500 - Server error</h1>
<p>The digest viewer hit an internal error while processing this request.</p>
</body>
</html>"""
            return self._send_bytes(
                status=500,
                content_type="text/html; charset=utf-8",
                data=error_html.encode("utf-8"),
                head_only=head_only,
            )

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

        items = "\n".join(
            f'<li><a href="/{f.name}">{html.escape(f.name)}</a></li>'
            for f in files
        ) or "<li>No digest files found.</li>"

        page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Digest index</title>
<style>{CSS}</style>
</head>
<body>
<div class="container">
  <h1>Digest index</h1>
  <p class="small">Serving markdown digests as HTML.</p>
  <ul class="file-list">
    {items}
  </ul>
</div>
</body>
</html>"""
        return self._send_bytes(
            status=200,
            content_type="text/html; charset=utf-8",
            data=page.encode("utf-8"),
            head_only=head_only,
        )

    def render_markdown(self, file_path: Path, head_only: bool = False):
        md = file_path.read_text(encoding="utf-8")
        body = markdown_to_html(md)

        page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(file_path.name)}</title>
<style>{CSS}</style>
</head>
<body>
<div class="container">
  <p class="small"><a href="/">Back to index</a></p>
  {body}
</div>
</body>
</html>"""
        return self._send_bytes(
            status=200,
            content_type="text/html; charset=utf-8",
            data=page.encode("utf-8"),
            head_only=head_only,
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--dir", default="/data/digests", help="Directory containing digest .md files")
    args = parser.parse_args()

    directory = str(Path(args.dir).resolve())

    class Handler(DigestHandler):
        def __init__(self, *handler_args, **handler_kwargs):
            super().__init__(*handler_args, directory=directory, **handler_kwargs)

    server = HTTPServer((args.host, args.port), Handler)
    print(f"Serving digests from {directory} at http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
