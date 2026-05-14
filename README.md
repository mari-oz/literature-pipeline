# Literature Digest Pipeline

A local, containerized neuroscience literature pipeline for ingesting new preprints, enriching metadata, generating structured summaries with a local GGUF model via `llama-cpp-python`, rendering Markdown digests, and serving them through a lightweight browser viewer.

## Overview

This project is designed to automate literature triage for neuroscience papers while remaining lightweight enough to run on homelab hardware. It currently targets a TrueNAS Scale deployment using Docker/Portainer, SQLite for persistence, local GGUF inference through `llama-cpp-python`, and generated Markdown digests for human review.

The current workflow is:

1. Fetch new neuroscience preprints from bioRxiv-related sources.
2. Insert or update paper records in SQLite.
3. Enrich each paper with metadata such as abstract, authors, category, version, and corresponding author information using the bioRxiv details API.
4. Enrich publication linkage using the bioRxiv publications endpoint so preprints can be tied to published articles where available.
5. Summarize abstracts into a structured JSON schema using a local GGUF model with `llama-cpp-python`.
6. Flatten structured summary fields into searchable text for downstream indexing and retrieval.
7. Generate a Markdown digest for browser-based review.
8. Serve the digest through a lightweight viewer inside the container stack.

## Current status

The pipeline has already been validated end-to-end on a local TrueNAS-based container deployment. A CPU-only configuration using an i7-4790 with 16 GB RAM and the `Qwen2.5-3B-Instruct-Q4_K_M.gguf` model has been tested successfully, and roughly 20 papers have already been summarized and reviewed through the digest viewer.

The system has also progressed beyond simple ingestion. It now includes metadata enrichment, publication-link enrichment, structured summaries, digest rendering, browser viewing, and a planned FTS5 search layer for full-text retrieval across titles, abstracts, and LLM-generated summary text.

## Architecture

The project follows a staged document-processing pipeline rather than a single monolithic script. SQLite acts as the core system of record, while enrichment and summarization add progressively richer derived data on top of feed-level paper metadata.

### Processing flow

```text
bioRxiv feed/email source
        ↓
  fetch_biorxiv.py
        ↓
      papers table
        ↓
 enrich_biorxiv.py
        ↓
 enrich_publication.py
        ↓
    summarize.py
        ↓
  summaries table + summary_text
        ↓
 generate_digest.py
        ↓
   Markdown digest files
        ↓
  serve_digest.py viewer
```

### Runtime components

| Component | Function |
|---|---|
| SQLite database | Stores paper records, enrichment metadata, publication linkage, and structured summaries. |
| `llama-cpp-python` + GGUF model | Runs local abstract summarization without requiring a cloud API. |
| Docker container | Packages the application and dependencies in a reproducible deployment unit. |
| TrueNAS dataset mounts | Persist the database, digests, and model files outside the container image. |
| Digest viewer | Exposes generated reports in a browser for daily review. |
| Planned FTS5 index | Adds full-text retrieval across titles, abstracts, and summary text.|

## Database schema

The database is centered on a `papers` table that holds the canonical record for each manuscript, and a `summaries` table that stores versioned LLM outputs. A future `papers_fts` FTS5 virtual table is intended to index selected text fields for fast and ranked retrieval.

### `papers`

| Column | Purpose |
|---|---|
| `id` | Primary key for each paper record. |
| `doi` | Unique manuscript DOI or preprint DOI.|
| `title` | Paper title used for display, digesting, and search. |
| `link` | Source URL for the paper or preprint entry. |
| `published_date` | Preprint-side publication date from source metadata. |
| `summary` | Optional short human-readable summary or bullet rollup derived from structured findings. |
| `abstract` | Paper abstract from metadata enrichment. |
| `authors` | Author string or serialized author information from the bioRxiv details API.|
| `category` | Subject/category classification from bioRxiv metadata. |
| `version` | Preprint version field from source metadata. |
| `license` | License metadata returned by the API when available. |
| `server` | Source server, typically `biorxiv` or similar preprint server metadata. |
| `corresponding_author` | Corresponding author metadata returned by the details endpoint. |
| `corresponding_institution` | Institution metadata associated with the corresponding author. |
| `published_doi` | DOI of the published journal article, if linked by the publications endpoint. |
| `published_journal` | Journal name for the published article, if available. |
| `published_article_date` | Journal publication date linked to the preprint. |
| `preprint_platform` | Source preprint platform metadata for downstream display. |
| `summary_text` | Flattened searchable text assembled from structured summary fields for FTS indexing. |
| `created_at` | Record creation timestamp. |
| `updated_at` | Record update timestamp for enrichment/summarization refreshes. |

### `summaries`

| Column | Purpose |
|---|---|
| `id` | Primary key for summary records. |
| `paper_id` | Foreign key linking to `papers.id`. |
| `model_name` | Summary model identifier, allowing side-by-side comparisons across models. |
| `prompt_version` | Version tag for the extraction schema/prompt design. |
| `summary_json` | Structured summary payload containing fields such as research question, methods, findings, limitations, and keywords. |
| `created_at` | Timestamp indicating when the summary was produced. |

### Planned `papers_fts`

The intended search index is an FTS5 virtual table using SQLite’s external-content pattern.[cite:1228][cite:1235] In practice, it is expected to index `title`, `abstract`, and `summary_text`, while linking rows back to `papers.id` through `content='papers'` and `content_rowid='id'`.

## Repository layout

The repository is structured like a compact Python application packaged for container deployment. The exact filenames may continue to evolve, but the current or intended project layout is organized around an `app/` package plus deployment files at the repository root.

```text
.
├── Dockerfile
├── requirements.txt
├── docker_compose.yml
└── app/
    ├── main.py
    ├── migrations.py
    ├── fetch_biorxiv.py
    ├── enrich_biorxiv.py
    ├── enrich_publication.py
    ├── summarize.py
    ├── generate_digest.py
    ├── serve_digest.py
    └── search_index.py
```

## File-by-file function

### Root-level files

| File | Function |
|---|---|
| `Dockerfile` | Builds the container image and installs all Python dependencies, including `llama-cpp-python`.|
| `requirements.txt` | Declares Python packages required by the application runtime.|
| `docker_compose.yml` | Defines the service, environment variables, and mounted datasets for deployment via Portainer/TrueNAS. |

### Application files

| File | Function |
|---|---|
| `app/main.py` | Main pipeline orchestrator that applies migrations, ingests papers, enriches metadata, runs summarization, and generates digests.|
| `app/migrations.py` | Creates and updates database schema, including future FTS5 table and trigger support. |
| `app/fetch_biorxiv.py` | Fetches new neuroscience preprints from source feeds or related upstream inputs. |
| `app/enrich_biorxiv.py` | Calls the bioRxiv details API to fill in abstract, author, category, version, and related manuscript metadata. |
| `app/enrich_publication.py` | Uses the bioRxiv `pubs` endpoint to link preprints to published journal articles. |
| `app/summarize.py` | Loads the local GGUF model and produces structured JSON summaries from abstracts using `llama-cpp-python`. |
| `app/generate_digest.py` | Converts recent database contents into a Markdown digest for reading and review. |
| `app/serve_digest.py` | Serves rendered digest output through a lightweight browser-accessible HTTP view. |
| `app/search_index.py` | Planned or newly added helper for querying the FTS5 index and returning ranked search results. |

## Runtime folders and mounted paths

The container image is intentionally stateless, while persistent data is stored in mounted datasets on the TrueNAS host. This separation keeps rebuilds safe and makes the application portable across deployments.

| Runtime path | Purpose |
|---|---|
| `/data/pipeline.db` | Main SQLite database used by the pipeline. |
| `/data/digests/` | Directory containing generated Markdown digest files. |
| `/models/` | Mounted directory containing one or more `.gguf` model files. |
| `/models/Qwen2.5-3B-Instruct-Q4_K_M.gguf` | Current validated local summary model for CPU-only execution. |

Typical host-side equivalents are dataset paths such as `/mnt/tank/literature-data` and `/mnt/tank/models`, mounted into the container through Docker/Compose bind mounts.

## Deployment notes

The project is intended to run in a container on TrueNAS Scale rather than directly on the host OS. This approach avoids modifying the appliance base system and keeps Python dependencies, the inference runtime, and the pipeline application bundled inside a reproducible image.

A typical deployment includes:

- a Docker image built from the repository root,
- a mounted data dataset for SQLite and digest output,
- a mounted model dataset for `.gguf` files,
- environment variables such as `DB_PATH`, `DIGEST_DIR`, `ENABLE_SUMMARY`, `MODEL_NAME`, `MODEL_PATH`, `N_CTX`, and `N_GPU_LAYERS`.

For CPU-only operation on the validated homelab host, `N_GPU_LAYERS` should remain `0`, and the `MODEL_PATH` must point to a real GGUF file available within the mounted `/models` directory.

## Search roadmap: why FTS5 matters

FTS5 is SQLite’s full-text search extension and works by storing an inverted index over tokenized text inside a virtual table. Instead of scanning every row with slow `LIKE '%term%'` queries, FTS5 supports fast retrieval, phrase matching, prefix queries, boolean combinations, proximity search, and ranking via `bm25()`.

This is particularly valuable for a neuroscience literature workflow because search questions are often conceptual rather than exact-string lookups. Examples include finding papers that mention calcium imaging and decoding together, searching limitations across summaries, or discovering all papers whose structured summaries reference hippocampal replay, GLMs, or sample-size constraints.

The practical FTS5 plan is:

1. Add `summary_text` to `papers` if not already present.
2. Flatten structured summary JSON into readable text at summarization time.
3. Create `papers_fts(title, abstract, summary_text)` as an external-content index tied to `papers.id`.
4. Maintain the index with SQLite triggers on insert, update, and delete.
5. Expose search through a helper module first, then through the browser viewer UI.

## What has been validated so far

Several milestones are already complete:

- the pipeline runs inside a containerized TrueNAS workflow,
- the local GGUF model loads correctly through `llama-cpp-python`, 
- 20 papers have already been summarized and inspected for quality,
- the 3B summary model is acceptable for current abstract-level extraction tasks,
- digest generation works,
- browser viewing works after fixes to the digest server and rendering path.

This means the system has already crossed the line from proof of concept into a usable research-support tool.

## Near-term roadmap

The next planned steps are primarily about retrieval, usability, and model iteration.

| Priority | Planned work | Value |
|---|---|---|
| 1 | Integrate FTS5 search end-to-end. | Makes the corpus actively searchable rather than only digest-based. |
| 2 | Surface structured fields more clearly in the digest viewer. | Improves daily triage and review speed. |
| 3 | Add a search route or search page in the viewer. | Gives browser-based access to ranked search results. |
| 4 | Trial a 7B model in a few days and compare quality vs. speed. | Evaluates whether better extraction quality justifies the additional CPU cost. |
| 5 | Expand author-centric indexing and retrieval workflows. | Supports longitudinal tracking of specific researchers and labs. |
| 6 | Potential later expansion to PDF/full-text handling. | Moves beyond abstract-only triage once the core pipeline is stable. |

## Long-term direction

The longer-term trajectory is to turn the pipeline into a local literature intelligence system rather than only a daily summarizer. That means combining ingestion, enrichment, structured extraction, search, author-centric retrieval, and possibly downstream export into notebooks or structured datasets useful for neuroscience project planning and review.

The architecture is intentionally aligned with homelab constraints: SQLite instead of a heavier database, FTS5 instead of a separate search engine, and local GGUF inference instead of cloud LLM calls. That makes the system reproducible, private, inexpensive to operate, and well-matched to a containerized TrueNAS deployment.
