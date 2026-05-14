from __future__ import annotations

import sqlite3
from typing import Any

import requests


API_URL_TEMPLATE = "https://api.biorxiv.org/details/{server}/{doi}/na/json"


def fetch_paper_details(doi: str, server: str = "biorxiv", timeout: int = 30) -> dict[str, Any] | None:
    url = API_URL_TEMPLATE.format(server=server, doi=doi)
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()

    collection = data.get("collection", [])
    if not collection:
        return None
    return collection[0]


def enrich_paper_row(conn: sqlite3.Connection, paper_id: int, doi: str, server: str = "biorxiv") -> bool:
    details = fetch_paper_details(doi=doi, server=server)
    if not details:
        return False

    conn.execute(
        """
        UPDATE papers
        SET
            title = COALESCE(NULLIF(?, ''), title),
            abstract = ?,
            authors = ?,
            category = ?,
            published_date = ?,
            version = ?,
            license = ?,
            server = ?,
            corresponding_author = ?,
            corresponding_institution = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            details.get("title"),
            details.get("abstract"),
            details.get("authors"),
            details.get("category"),
            details.get("date"),
            str(details.get("version")) if details.get("version") is not None else None,
            details.get("license"),
            details.get("server", server),
            details.get("author_corresponding"),
            details.get("author_corresponding_institution"),
            paper_id,
        ),
    )
    return True


def enrich_unsynced_papers(conn: sqlite3.Connection, server: str = "biorxiv") -> int:
    rows = conn.execute(
        """
        SELECT id, doi
        FROM papers
        WHERE doi IS NOT NULL
          AND doi != ''
          AND (abstract IS NULL OR abstract = '')
        ORDER BY created_at ASC
        """
    ).fetchall()

    enriched = 0
    for paper_id, doi in rows:
        try:
            if enrich_paper_row(conn, paper_id, doi, server=server):
                enriched += 1
        except Exception:
            continue

    conn.commit()
    return enriched
