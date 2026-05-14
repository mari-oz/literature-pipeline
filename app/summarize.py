from __future__ import annotations

import json
import sqlite3
from typing import Any

from llama_cpp import Llama


PROMPT_VERSION = "v1-abstract-neuroscience"
DB_PATH = Path('/data/pipeline.db')

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "research_question": {"type": "string"},
        "model_system": {"type": "string"},
        "methods": {"type": "array", "items": {"type": "string"}},
        "main_findings": {"type": "array", "items": {"type": "string"}},
        "limitations": {"type": "array", "items": {"type": "string"}},
        "keywords": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "research_question",
        "model_system",
        "methods",
        "main_findings",
        "limitations",
        "keywords",
    ],
    "additionalProperties": False,
}


def build_llm(model_path: str, n_ctx: int = 4096, n_gpu_layers: int = 0) -> Llama:
    return Llama(
        model_path=model_path,
        n_ctx=n_ctx,
        n_gpu_layers=n_gpu_layers,
        verbose=False,
    )


def normalize_summary(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "research_question": str(result.get("research_question", "") or ""),
        "model_system": str(result.get("model_system", "") or ""),
        "methods": [str(x) for x in (result.get("methods", []) or [])],
        "main_findings": [str(x) for x in (result.get("main_findings", []) or [])],
        "limitations": [str(x) for x in (result.get("limitations", []) or [])],
        "keywords": [str(x) for x in (result.get("keywords", []) or [])],
    }


def build_summary_text(result: dict[str, Any]) -> str:
    parts: list[str] = []

    if result.get("research_question"):
        parts.append(f"research question: {result['research_question']}")
    if result.get("model_system"):
        parts.append(f"model system: {result['model_system']}")
    if result.get("methods"):
        parts.append("methods: " + "; ".join(result["methods"]))
    if result.get("main_findings"):
        parts.append("main findings: " + "; ".join(result["main_findings"]))
    if result.get("limitations"):
        parts.append("limitations: " + "; ".join(result["limitations"]))
    if result.get("keywords"):
        parts.append("keywords: " + "; ".join(result["keywords"]))

    return "\n".join(parts)


def summarize_abstract(llm: Llama, title: str, abstract: str) -> dict[str, Any]:
    system = (
        "You extract scientific information faithfully from neuroscience abstracts. "
        "Return valid JSON only. Do not invent details not supported by the text. "
        "If a field is unknown, use an empty string or empty list."
    )

    user = f"""Title:
{title}

Abstract:
{abstract}

Extract these fields:
- research_question
- model_system
- methods
- main_findings
- limitations
- keywords
"""

    response = llm.create_chat_completion(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.1,
        max_tokens=700,
        response_format={
            "type": "json_object",
            "schema": SUMMARY_SCHEMA,
        },
    )

    content = response["choices"][0]["message"]["content"]
    return normalize_summary(json.loads(content))


def summarize_unsummarized_papers(
    conn: sqlite3.Connection,
    llm: Llama,
    model_name: str,
    limit: int = 20,
) -> int:
    rows = conn.execute(
        """
        SELECT p.id, p.title, p.abstract
        FROM papers p
        LEFT JOIN summaries s
          ON s.paper_id = p.id
         AND s.model_name = ?
         AND s.prompt_version = ?
        WHERE p.abstract IS NOT NULL
          AND p.abstract != ''
          AND s.id IS NULL
        ORDER BY p.created_at ASC
        LIMIT ?
        """,
        (model_name, PROMPT_VERSION, limit),
    ).fetchall()

    count = 0
    for paper_id, title, abstract in rows:
        try:
            result = summarize_abstract(llm, title, abstract)
            summary_text = build_summary_text(result)

            conn.execute(
                """
                INSERT INTO summaries (paper_id, model_name, prompt_version, summary_json)
                VALUES (?, ?, ?, ?)
                """,
                (paper_id, model_name, PROMPT_VERSION, json.dumps(result, ensure_ascii=False)),
            )

            bullets = result.get("main_findings", [])
            short_summary = " ".join(f"- {x}" for x in bullets[:3]) if bullets else None

            conn.execute(
                """
                UPDATE papers
                SET summary = COALESCE(?, summary),
                    summary_text = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (short_summary, summary_text, paper_id),
            )
            count += 1

        except Exception as exc:
            print(f"Summary failed for paper_id={paper_id}, title={title!r}: {exc}")
            conn.rollback()
            continue

    conn.commit()
    return count


def flatten_summary(summary_json: str | dict | None) -> str:
    if summary_json is None:
        return ''
    if isinstance(summary_json, str):
        try:
            payload = json.loads(summary_json)
        except json.JSONDecodeError:
            return summary_json
    else:
        payload = summary_json

    fields = []
    for key, value in payload.items():
        if value is None:
            continue
        if isinstance(value, list):
            value = '; '.join(str(v) for v in value)
        elif isinstance(value, dict):
            value = '; '.join(f'{k}: {v}' for k, v in value.items())
        fields.append(f'{key}: {value}')
    return ' | '.join(fields)


def update_summary_text(conn: sqlite3.Connection) -> int:
    rows = conn.execute('SELECT id, summary_json FROM summaries').fetchall()
    updated = 0
    for paper_id, summary_json in rows:
        summary_text = flatten_summary(summary_json)
        conn.execute(
            'UPDATE papers SET summary_text = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
            (summary_text, paper_id),
        )
        updated += 1
    conn.commit()
    return updated


if __name__ == '__main__':
    conn = sqlite3.connect(DB_PATH)
    try:
        updated = update_summary_text(conn)
        print(f'updated {updated} rows')
    finally:
        conn.close()
