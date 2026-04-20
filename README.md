# subi-neko 🐱

Automated subtitle translation pipeline for anime MKV files.

Extracts subtitles from MKV files, translates them using an OpenAI-compatible LLM, runs multi-stage quality review (rules, grammar, LLM), and muxes the finished subtitles back into the container — all driven by a web UI.

---

## Features

- **Automatic MKV processing** — drop files into an import folder; the app discovers, inspects, and processes them automatically
- **Project & speaker management** — group files into projects, map on-screen speakers to named characters with gender/role metadata for context-aware translation
- **Chunked translation** — subtitles are split into configurable chunks and translated in parallel with a preceding context window for coherence
- **Multi-stage review pipeline** per chunk:
  - **Translation** — LLM translation with character context and customisable system prompt
  - **Validation** — structural checks on the translated output
  - **Repair** — automated LLM repair pass when validation fails (one attempt before requiring user action)
  - **Rules review** — rule-based QA checks
  - **Grammar review** — optional grammar/spellcheck via LanguageTool or Korektor
  - **LLM review** — optional second LLM pass to flag translation issues
- **QA items** — flagged issues surfaced per subtitle event; visible in the UI for manual review
- **Output muxing** — renders translated subtitles back to ASS and muxes into the original MKV using mkvmerge
- **Configurable via UI** — all settings (API keys, models, prompts, providers, pipeline switches) editable from the Options drawer without restarting

---

## Requirements

- Docker & Docker Compose

---

## Quick start

```bash
# 1. Clone
git clone https://github.com/yourname/subi-neko.git
cd subi-neko

# 2. Create media directories (already done if you use docker-compose volumes as-is)
mkdir -p media/import media/output config

# 3. Start
docker compose up -d

# 4. Open the UI
open http://localhost:8000
```

The UI is served by the backend on port 8000. No separate frontend server is needed.

---

## Directory layout

| Path | Purpose |
|------|---------|
| `media/import/` | Place project source folders here; each subdirectory becomes a project |
| `media/output/` | Finished MKV files are written here |
| `config/` | SQLite database (`subi.db`) and persistent options |

---

## Configuration

All runtime settings are stored in the database and editable through the **Options drawer** in the UI (gear icon). Changes take effect immediately — no restart required.

### Environment variables

Only the directory paths and low-level flags are set via environment variables (in `docker-compose.yml` or `.env`):

| Variable | Default | Description |
|----------|---------|-------------|
| `IMPORT_ROOT` | `./media/import` | Source MKV import directory |
| `OUTPUT_ROOT` | `./media/output` | Finished output directory |
| `CONFIG_ROOT` | `./config` | SQLite database directory |
| `DEBUG` | `false` | Enable FastAPI debug mode + SQL query logging |

### Options (UI / database)

#### Translation

| Option key | Default | Description |
|------------|---------|-------------|
| `TARGET_LANG_NAME` | *(required)* | Full language name sent to the LLM (e.g. `Czech`) |
| `TARGET_LANG_CODE` | *(required)* | BCP-47 code for grammar tools (e.g. `cs`) |
| `CHUNK_SIZE` | `100` | Subtitle events per translation chunk |
| `PREPEND_CONTEXT_SIZE` | `5` | Events before the chunk sent as read-only context |
| `TRANSLATION_PROMPT` | built-in | System prompt for the translation job; `{TARGET_LANG_NAME}` is substituted |
| `REPAIR_PROMPT` | built-in | System prompt for the repair job |

#### OpenAI / LLM

| Option key | Default | Description |
|------------|---------|-------------|
| `OPENAI_API_KEY` | *(required)* | API key; set to any value for local/proxy endpoints |
| `OPENAI_API_BASE` | `https://api.openai.com/v1` | API base URL; point to any OpenAI-compatible endpoint |
| `OPENAI_MODEL_CHEAP` | `gpt-5.4-mini` | Model used for translation and repair |
| `OPENAI_MODEL_BETTER` | `gpt-5.4` | Model used for LLM review |

#### Grammar review

| Option key | Default | Description |
|------------|---------|-------------|
| `GRAMMAR_PROVIDER` | `languagetool` | `languagetool`, `korektor`, or `none` (skip grammar check) |
| `GRAMMAR_PROVIDER_BASE_URL` | `http://localhost:8010` | REST endpoint of the grammar provider |

#### LLM review

| Option key | Default | Description |
|------------|---------|-------------|
| `LLM_REVIEW_ALWAYS` | `0` | `1` = run LLM review on every chunk; `0` = only when flagged by rules review |
| `LLM_REVIEW_FLAGGED_ONLY` | `1` | `1` = send only events with existing QA issues to the LLM; `0` = send the entire chunk |
| `REVIEW_PROMPT` | built-in | System prompt for the LLM review job |

#### Worker

| Option key | Default | Description |
|------------|---------|-------------|
| `JOB_WORKER_COUNT` | `4` | Number of parallel job worker threads |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL` |

---

## Grammar providers

Grammar review is optional. To use it, uncomment the relevant service in `docker-compose.yml` and set `GRAMMAR_PROVIDER_BASE_URL` in the UI.

**LanguageTool** (multi-language):
```yaml
languagetool:
  image: erikvl87/languagetool
  ports:
    - "8010:8010"
  environment:
    - Java_Xms=512m
    - Java_Xmx=1g
```

**Korektor** (Czech):
```yaml
korektor:
  image: ghcr.io/futuretek-solutions-ltd/docker-korektor
  ports:
    - "8010:8010"
```

Set `GRAMMAR_PROVIDER` to `none` in the UI to skip grammar review entirely.

---

## Translation pipeline

Each file goes through this sequence automatically:

```
MKV file discovered
  └─ inspect_mkv         – probe tracks, detect subtitle format
  └─ extract_subtitles   – extract ASS/SRT subtitle track
  └─ scan_project        – parse subtitle events into DB
  └─ aggregate_speakers  – collect speaker names from events
  └─ resolve_style_fonts – load font/style metadata
  └─ plan_translation_chunks – split events into chunks

[user maps speakers to characters]

Per chunk (parallel):
  └─ translate_chunk     – LLM translation
  └─ validate_chunk      – structural validation
  └─ repair_chunk        – LLM repair (if validation failed once)
  └─ validate_chunk      – re-validate after repair
  └─ review_chunk_rules  – rule-based QA
  └─ review_chunk_grammar – grammar/spellcheck (optional)
  └─ review_chunk_llm    – LLM review (optional)

[user manually reviews warnings]

All chunks complete
  └─ render_output_ass   – write translated ASS file
  └─ mux_output_mkv      – mux back into MKV
```

---

## Chunk failure states

| Status | Meaning | Retry available |
|--------|---------|-----------------|
| `job_failed` | Technical failure (API error, parse error, crash) | ✅ |
| `validate_trans_failed` | First validation rejection — repair will run automatically | — |
| `validate_repair_failed` | Validation rejected again after repair — requires user action | ✅ |

When a chunk is retried manually, it resumes from the correct stage based on where it failed.

---

## Development

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate      # Windows
# source .venv/bin/activate  # Linux/macOS
pip install -r requirements.txt

# Run migrations
alembic upgrade head

# Start dev server
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev     # Vite dev server on http://localhost:5173
```

Set `VITE_API_BASE_URL=http://localhost:8000` (or configure the Vite proxy) to point the frontend at the local backend.

### Tests

```bash
cd backend
pytest tests/
```
