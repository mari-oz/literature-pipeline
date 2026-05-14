from __future__ import annotations

import re
from typing import Any

import feedparser


DEFAULT_FEED_URL = "https://connect.biorxiv.org/biorxiv_xml.php?subject=neuroscience"
DOI_REGEX = re.compile(r"(10\.\d{4,9}/[-._;()/:A-Z0-9]+)", re.IGNORECASE)


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _extract_doi(entry: dict[str, Any]) -> str | None:
    candidates: list[str] = []

    for key in (
        "dc_identifier",
        "dcidentifier",
        "prism_doi",
        "doi",
        "id",
        "link",
    ):
        value = entry.get(key)
        if value:
            candidates.append(str(value))

    links = entry.get("links", []) or []
    for link_obj in links:
        href = link_obj.get("href")
        if href:
            candidates.append(str(href))

    summary = entry.get("summary")
    if summary:
        candidates.append(str(summary))

    for candidate in candidates:
        match = DOI_REGEX.search(candidate)
        if match:
            return match.group(1).strip()

    return None


def _extract_link(entry: dict[str, Any]) -> str | None:
    link = _clean_text(entry.get("link"))
    if link:
        return link

    links = entry.get("links", []) or []
    for link_obj in links:
        href = _clean_text(link_obj.get("href"))
        rel = _clean_text(link_obj.get("rel"))
        if href and (rel in (None, "alternate") or "biorxiv.org" in href):
            return href

    return None


def _extract_summary(entry: dict[str, Any]) -> str | None:
    summary = _clean_text(entry.get("summary"))
    if summary:
        return summary

    subtitle = _clean_text(entry.get("subtitle"))
    if subtitle:
        return subtitle

    return None


def _extract_published(entry: dict[str, Any]) -> str | None:
    for key in (
        "published",
        "updated",
        "published_parsed",
    ):
        value = entry.get(key)
        if value is None:
            continue
        if key.endswith("_parsed"):
            continue
        cleaned = _clean_text(value)
        if cleaned:
            return cleaned
    return None


def normalize_entry(entry: dict[str, Any]) -> dict[str, Any]:
    title = _clean_text(entry.get("title"))
    link = _extract_link(entry)
    doi = _extract_doi(entry)
    summary = _extract_summary(entry)
    published = _extract_published(entry)

    return {
        "doi": doi,
        "title": title,
        "link": link,
        "summary": summary,
        "published": published,
    }


def fetch_neuroscience_feed(feed_url: str = DEFAULT_FEED_URL) -> list[dict[str, Any]]:
    parsed = feedparser.parse(feed_url)

    if getattr(parsed, "bozo", 0):
        exception = getattr(parsed, "bozo_exception", None)
        if exception:
            raise RuntimeError(f"Failed to parse bioRxiv feed: {exception}")

    papers: list[dict[str, Any]] = []
    for entry in parsed.entries:
        item = normalize_entry(entry)
        if item["title"] and (item["doi"] or item["link"]):
            papers.append(item)

    return papers
