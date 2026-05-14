from __future__ import annotations

import requests
import sqlite3
from typing import Any


API_BASE = "https://api.biorxiv.org/pubs"


def fetch_publication_details(doi: str, server: str = "biorxiv") -> dict[str, Any] | None:
    doi = doi.strip()
    if not doi:
        return None

    url = f"{API_BASE}/{server}/{doi}/na/json"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    payload = resp.json()

    collection = payload.get("collection") or []
    if not collection:
        return None

    return collection[0]


def enrich_publication_for_doi(conn: sqlite3.Connection, doi: str, server: str = "biorxiv") -> bool:
    record = fetch_publication_details(doi, server=server)
    if not record:
        return False

    biorxiv_doi = record.get("biorxiv_doi") or doi
    published_doi = record.get("published_doi")
    published_journal = record.get("published_journal")
    published_date = record.get("published_date")
    preprint_platform = record.get("preprint_platform")

    conn.execute(
        """
        UPDATE papers
        SET
            published_doi = COALESCE(?, published_doi),
            published_journal = COALESCE(?, published_journal),
            published_article_date = COALESCE(?, published_article_date),
            preprint_platform = COALESCE(?, preprint_platform)
        WHERE doi = ?
        """,
        (
            published_doi,
            published_journal,
            published_date,
            preprint_platform,
            biorxiv_doi,
        ),
    )
    return conn.total_changes > 0


def enrich_publication_metadata(conn: sqlite3.Connection, server: str = "biorxiv") -> int:
    rows = conn.execute(
        """
        SELECT doi
        FROM papers
        WHERE doi IS NOT NULL
          AND doi != ''
          AND (published_doi IS NULL OR published_doi = '')
        """
    ).fetchall()

    updated = 0
    for (doi,) in rows:
        try:
            changed = enrich_publication_for_doi(conn, doi, server=server)
            if changed:
                updated += 1
        except requests.RequestException as exc:
            print(f"Publication enrichment failed for {doi}: {exc}")

    conn.commit()
    return updated
