from __future__ import annotations

import argparse
import html
import sqlite3
import traceback
from pathlib import Path
from flask import Flask, jsonify, request, render_template_string

DB_PATH = Path("/data/pipeline.db")
app = Flask(__name__)

SEARCH_SQL = """
SELECT
    p.id,
    p.title,
    p.doi,
    p.category,
    p.published_date,
    bm25(papers_fts, 10.0, 2.0, 5.0) AS rank,
    snippet(papers_fts, 2, '<mark>', '</mark>', ' … ', 18) AS snippet
FROM papers_fts
JOIN papers p ON p.id = papers_fts.rowid
WHERE papers_fts MATCH ?
ORDER BY rank
LIMIT ?
"""

PAGE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Literature Search</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 980px; margin: 2rem auto; padding: 0 1rem; line-height: 1.45; }
    form { display:flex; gap:.75rem; margin-bottom:1.25rem; }
    input { flex:1; padding:.8rem; font-size:1rem; }
    button { padding:.8rem 1rem; }
    .toolbar { display:flex; gap:1rem; align-items:center; flex-wrap:wrap; margin-bottom:1rem; }
    .panel { border:1px solid #ddd; border-radius:12px; padding:1rem; margin-bottom:1rem; }
    .meta { color:#666; font-size:.95rem; margin:.35rem 0 .5rem; }
    .rankbar { height:10px; background:#eee; border-radius:999px; overflow:hidden; margin-top:.5rem; }
    .rankfill { height:100%; background:#2f6fed; }
    mark { background:#fff2a8; }
    .muted { color:#666; }
  </style>
</head>
<body>
  <h1>Literature search</h1>
  <p class="muted">FTS5 + BM25 ranking over title, abstract, and summary text.</p>
  <form id="search-form">
    <input id="q" placeholder="calcium AND hippocampus" autocomplete="off">
    <button type="submit">Search</button>
  </form>
  <div class="toolbar">
    <button id="rebuild-btn" type="button">Rebuild index</button>
    <span id="status" class="muted"></span>
  </div>
  <div id="results"></div>

  <script>
    const form = document.getElementById('search-form');
    const q = document.getElementById('q');
    const results = document.getElementById('results');
    const rebuildBtn = document.getElementById('rebuild-btn');
    const status = document.getElementById('status');

    function normalizeRanks(items) {
      if (!items.length) return items;
      const vals = items.map(x => Number(x.rank));
      const min = Math.min(...vals);
      const max = Math.max(...vals);
      return items.map(item => {
        const rank = Number(item.rank);
        const pct = max === min ? 100 : Math.max(5, Math.round((max - rank) / (max - min) * 100));
        return {...item, rank_pct: pct};
      });
    }

    function render(items) {
      results.innerHTML = '';
      if (!items.length) {
        results.innerHTML = '<p class="muted">No results.</p>';
        return;
      }
      for (const item of normalizeRanks(items)) {
        const el = document.createElement('article');
        el.className = 'panel';
        el.innerHTML = `
          <h2>${item.title}</h2>
          <div class="meta">DOI: ${item.doi || '-'} | Category: ${item.category || '-'} | Date: ${item.published_date || '-'} | BM25: ${Number(item.rank).toFixed(4)}</div>
          <p>${item.snippet || ''}</p>
          <div class="rankbar"><div class="rankfill" style="width:${item.rank_pct}%"></div></div>
        `;
        results.appendChild(el);
      }
    }

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const query = q.value.trim();
      if (!query) return;
      status.textContent = 'Searching...';
      const res = await fetch(`/api/search?q=${encodeURIComponent(query)}`);
      const data = await res.json();
      render(data.results || []);
      status.textContent = `${data.count || 0} result(s)`;
    });

    rebuildBtn.addEventListener('click', async () => {
      status.textContent = 'Rebuilding index...';
      const res = await fetch('/api/admin/rebuild-fts', {method: 'POST'});
      const data = await res.json();
      status.textContent = data.message || 'Done';
    });
  </script>
</body>
</html>
"""


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@app.get("/")
def home():
    return render_template_string(PAGE)


@app.get("/api/search")
def api_search():
    q = (request.args.get("q") or "").strip()
    limit = min(max(int(request.args.get("limit", 20)), 1), 100)
    if not q:
        return jsonify({"query": q, "count": 0, "results": []})

    conn = get_conn()
    try:
        rows = conn.execute(SEARCH_SQL, (q, limit)).fetchall()
        return jsonify({"query": q, "count": len(rows), "results": [dict(r) for r in rows]})
    except sqlite3.OperationalError as exc:
        return jsonify({"query": q, "count": 0, "results": [], "error": str(exc)}), 400
    finally:
        conn.close()


@app.post("/api/admin/rebuild-fts")
def rebuild_fts():
    conn = get_conn()
    try:
        conn.execute("INSERT INTO papers_fts(papers_fts) VALUES('rebuild')")
        conn.commit()
        return jsonify({"status": "ok", "message": "FTS rebuild complete"})
    finally:
        conn.close()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
