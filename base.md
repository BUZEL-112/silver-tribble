# Codebase Structure and File Documentation

This document provides a complete directory file tree and an architectural breakdown of each file and component in the **AI News to YouTube Video Pipeline** codebase.

---

## 1. Project Directory Tree

```
silver-tribble/
├── .env.example                       # Example environment variables template
├── .gitignore                          # Git ignore rules for Python, Node, and media outputs
├── base.md                             # Architectural file tree and module documentation (this file)
├── config_example.yaml                 # Comprehensive configuration template (clone to config.yaml)
├── docker-compose.yml                  # Container stack: PostgreSQL (pgvector) & LiteLLM proxy
├── get-docker.sh                       # Docker installation utility script
├── pyproject.toml                      # Python package configuration, dependencies, and tooling rules
│
├── config/
│   └── litellm_config.yaml             # LiteLLM routing matrix, model aliases, and fallbacks
│
├── prompts/
│   ├── beat_sheet.yaml                 # System prompt and Jinja2 template for Stage 1 beat sheet generation
│   └── eswar_host_persona.yaml         # System prompt and Jinja2 template for Stage 2 comedic host dialogue
│
├── src/
│   ├── __init__.py                     # Package marker for src
│   ├── cli.py                          # Typer CLI application exposing all individual stages & end-to-end pipeline
│   │
│   ├── core/
│   │   ├── __init__.py                 # Package marker for core module
│   │   ├── config.py                   # Pydantic Settings management loaded from environment/.env
│   │   └── database.py                 # SQLAlchemy engine creation, session factory, and schema initialization
│   │
│   ├── flows/
│   │   ├── __init__.py                 # Package marker for flows module
│   │   └── video_pipeline_flow.py      # Prefect 3.x orchestration flow and task decorators
│   │
│   ├── models/
│   │   ├── __init__.py                 # Package marker for models module
│   │   ├── entities.py                 # SQLAlchemy declarative ORM models (Article, StoryCluster, ScriptRecord, RenderJob, CostLogEntry)
│   │   └── schemas.py                  # Pydantic validation models and data contracts across pipeline stages
│   │
│   ├── repositories/
│   │   ├── __init__.py                 # Package marker for repositories module
│   │   ├── base.py                     # Base repository class handling SQLAlchemy session lifecycle
│   │   ├── article_repository.py       # Persistence and queries for raw articles and story clusters
│   │   ├── cost_repository.py          # Granular spend logging and budget aggregation by stage and video job
│   │   ├── render_repository.py        # Render job state machine, media paths, and lifecycle tracking
│   │   └── script_repository.py        # Persistence and retrieval of beat sheets and dialogue scripts
│   │
│   └── services/
│       ├── __init__.py                 # Package marker for services module
│       ├── caption_service.py          # Word-level timestamp extraction with faster-whisper and uniform fallback
│       ├── clustering_service.py       # Embedding generation (text-embedding-3-small) and cosine similarity clustering
│       ├── render_service.py           # Remotion props builder and subprocess execution bridge
│       ├── rss_service.py              # Multi-feed RSS scraper and HTML content sanitizer
│       ├── script_service.py           # Two-stage LLM generator (gpt-4o-mini structuring + DeepSeek expansion)
│       ├── storage_service.py          # Abstract storage adapter with Local disk and S3 / Cloudflare R2 implementations
│       └── tts_service.py              # Voice synthesis bridge via Google GenAI SDK (Gemini audio) with synthetic fallback
│
├── remotion/
│   ├── package.json                    # Node.js dependencies (Remotion, React, TypeScript)
│   ├── remotion.config.ts              # Remotion render configuration (OpenGL renderer, image format, overwrite)
│   ├── tsconfig.json                   # TypeScript compiler configuration for Remotion
│   │
│   └── src/
│       ├── index.ts                    # Remotion entrypoint registering the root component
│       ├── Root.tsx                    # Composition definitions for 9:16 Shorts and 16:9 Widescreen
│       ├── types.ts                    # TypeScript interfaces for render props, beats, and word captions
│       │
│       ├── components/
│       │   ├── AnimatedBackground.tsx  # Procedural SVG cyber grid and dynamic radial glow background
│       │   ├── Captions.tsx            # Word-by-word active kinetic typography synchronized to audio timestamps
│       │   ├── OutroCard.tsx           # Call-to-action closing card with spring bounce animation
│       │   └── TitleCard.tsx           # Lower-third headline badge with entrance spring animation
│       │
│       └── compositions/
│           └── MainVideo.tsx           # Primary composition orchestrating audio, background, visuals, and captions
│
├── tests/
│   ├── __init__.py                     # Package marker for tests
│   ├── conftest.py                     # Pytest fixtures: in-memory SQLite database, repositories, and isolated storage
│   ├── test_article_and_clustering.py  # Unit tests for URL deduplication, embeddings, and cosine clustering
│   ├── test_cost_log.py                # Unit tests for cost audit repository and aggregate spending calculation
│   ├── test_render_props.py            # Unit tests for Remotion JSON props serialization and dry-run execution
│   ├── test_schemas.py                 # Unit tests verifying Pydantic schema validation and alias dumping
│   ├── test_services.py                # Tests for Whisper sparse caption fallback, HTML cleaner, and cluster status
│   ├── test_storage.py                 # Unit tests for LocalStorageService file and byte operations
│   └── test_e2e_pipeline.py            # End-to-end integration tests for Prefect flow, CLI stages, and render props
│
└── output/
    └── videos/                         # Default export folder for rendered MP4 video files
```

---

## 2. Component and File Details

### Root & Infrastructure Configuration

- **`pyproject.toml`**: Project configuration file defining Python dependencies (`prefect`, `pydantic`, `sqlalchemy`, `pgvector`, `openai`, `google-genai`, `faster-whisper`, `boto3`, `typer`, `rich`, `scikit-learn`), optional dev dependencies (`pytest`, `ruff`, `mypy`), CLI entrypoints, and linter settings.
- **`docker-compose.yml`**: Defines the local container infrastructure. Spins up a PostgreSQL 16 database with the `pgvector` extension and the LiteLLM proxy container mapped to port 4000.
- **`.env.example` / `.env`**: Environment file configuring database connection URLs (SQLite or PostgreSQL), LiteLLM proxy URL, provider API keys (OpenAI, DeepSeek, Gemini, Pexels), storage backend, and Whisper model settings.
- **`config_example.yaml` / `config.yaml`**: Primary YAML configuration file containing all runtime settings (database connection, LiteLLM gateway, model routing, direct provider API keys, media storage, Whisper transcription, Remotion render parameters, clustering similarity threshold, and curated RSS feeds). Users copy `config_example.yaml` to `config.yaml` to customize their environment.
- **`config/litellm_config.yaml`**: LiteLLM configuration mapping model names (`gpt-4o-mini`, `deepseek-chat`, `text-embedding-3-small`) to provider endpoints with routing rules, retries, and fallback chains.

---

### Prompt Templates (`prompts/`)

- **`prompts/beat_sheet.yaml`**: Prompt definition for Stage 1 script generation. Instructs `gpt-4o-mini` to analyze clustered articles and structure them into timed narrative beats (hook, context, breakthrough, skepticism, outro) with visual directions and lower-third on-screen text.
- **`prompts/eswar_host_persona.yaml`**: Prompt definition for Stage 2 script generation. Directs `deepseek-chat` to expand the structured beat sheet into humorous, cynical spoken dialogue adopting the "Eswar" host persona, avoiding corporate buzzwords and formatting clean text for TTS synthesis.

---

### Core Module (`src/core/`)

- **`src/core/config.py`**: Declares the `Settings` class using `pydantic-settings`. Loads configuration parameters from environment variables or `.env` files with sensible defaults and provides utility methods for directory creation.
- **`src/core/database.py`**: Manages the SQLAlchemy database engine (`build_engine`), connection pooling, session lifecycle via the `@contextmanager get_session()`, and schema table creation (`init_db`) including conditional `pgvector` extension setup.

---

### Models & Schemas (`src/models/`)

- **`src/models/entities.py`**: SQLAlchemy ORM entity classes representing database tables:
  - `Article`: Stored RSS feed articles, URLs, summaries, and embedding vectors.
  - `StoryCluster`: Clustered news events grouping multiple related articles.
  - `ScriptRecord`: Generated beat sheets and continuous spoken narration.
  - `RenderJob`: State and media asset tracking for video render jobs.
  - `CostLogEntry`: Granular financial tracking recording USD costs per token, character, or compute second.
- **`src/models/schemas.py`**: Pydantic models enforcing schema contracts:
  - `FeedItem`: Cleaned article payload from RSS feeds.
  - `StoryBeat` & `BeatSheetResponse`: Stage 1 structured outline schema.
  - `ExpandedBeat` & `ScriptExpansionResponse`: Stage 2 spoken script schema.
  - `WordCaption` & `CaptionSegment`: Synchronized word timestamp schema.
  - `RenderBeatProp` & `RenderProps`: Complete Remotion input property payload.
  - `CostLogCreate`: Schema for recording stage execution costs.

---

### Data Access Layer (`src/repositories/`)

- **`src/repositories/base.py`**: `BaseRepository` storing the active SQLAlchemy `Session`.
- **`src/repositories/article_repository.py`**: Handles article insertion with batch URL deduplication, embedding vector assignment, cluster storage by unique hash, and article lookup queries.
- **`src/repositories/cost_repository.py`**: Records cost entries and calculates total spend, spend breakdown by stage, and spend grouped by video job ID.
- **`src/repositories/render_repository.py`**: Manages video render jobs, updating audio paths, caption paths, render props, and marking jobs as completed or failed.
- **`src/repositories/script_repository.py`**: Creates and fetches finalized script records by ID or cluster ID.

---

### Business Services (`src/services/`)

- **`src/services/rss_service.py`**: Iterates through curated tech RSS feeds (TechCrunch, VentureBeat, The Verge, MIT Tech Review, ArXiv), parses feed entries, and sanitizes raw HTML into plain text.
- **`src/services/clustering_service.py`**: Computes 1536-dimensional OpenAI vector embeddings via LiteLLM for unembedded articles, calculates cosine similarity matrices with NumPy, and groups related articles into story clusters above a configurable similarity threshold.
- **`src/services/script_service.py`**: Implements two-stage script generation:
  1. *Stage 1*: Generates a structured beat sheet via `gpt-4o-mini`.
  2. *Stage 2*: Expands the beat sheet into comedic spoken dialogue via `deepseek-chat`.
  Includes offline synthetic fallbacks for local and testing environments.
- **`src/services/tts_service.py`**: Synthesizes voice audio from narration text using the Google GenAI SDK (`gemini-2.0-flash` audio modality) with automatic fallback to calibrated WAV files for offline execution.
- **`src/services/caption_service.py`**: Transcribes audio and extracts word-level timestamps using `faster-whisper`. Automatically triggers uniform word distribution fallback if speech transcription is sparse or audio is synthetic.
- **`src/services/render_service.py`**: Translates script beats and word captions into structured `render_props.json` and executes the Remotion CLI via subprocess to compile and render final MP4 video files (with dry-run support).
- **`src/services/storage_service.py`**: Storage abstraction with two implementations:
  - `LocalStorageService`: Reads and writes assets directly to local disk.
  - `S3StorageService`: Uploads assets to Cloudflare R2 / AWS S3 with local caching.

---

### Orchestration & CLI (`src/flows/` and `src/cli.py`)

- **`src/flows/video_pipeline_flow.py`**: Prefect 3.x orchestration flow connecting all tasks:
  - `ingest_feeds_task`: Ingests and saves new news articles.
  - `cluster_articles_task`: Embeds and groups articles into story clusters.
  - `generate_script_task`: Generates beat sheets and spoken narration.
  - `voice_and_captions_task`: Synthesizes audio and generates word captions.
  - `render_video_task`: Prepares props and executes the video render.
- **`src/cli.py`**: Command-line interface built with Typer and Rich:
  - `setup-db`: Initializes database tables and vector extensions.
  - `ingest`: Fetches latest AI news articles from RSS feeds.
  - `cluster`: Generates embeddings and prints detected story clusters.
  - `script`: Generates two-stage script for a given cluster ID.
  - `voice`: Generates TTS audio and captions for a given script ID.
  - `render`: Compiles Remotion props and renders final MP4 for a job ID.
  - `run`: Runs the full pipeline end-to-end (with `--auto-top`, `--cluster-id`, `--aspect-ratio`, and `--dry-run`).
  - `costs`: Displays tabular breakdown of total pipeline spend by stage and per video.

---

### Remotion Video Engine (`remotion/`)

- **`remotion/package.json`**: NPM package configuration declaring Remotion, React 18, and TypeScript dependencies.
- **`remotion/remotion.config.ts`**: Configures Remotion CLI rendering settings (`angle` OpenGL renderer, JPEG image format, and overwrite permissions).
- **`remotion/src/types.ts`**: TypeScript definitions matching Python Pydantic schemas (`RenderProps`, `RenderBeatProp`, `WordCaption`).
- **`remotion/src/index.ts`**: Remotion entrypoint calling `registerRoot(RemotionRoot)`.
- **`remotion/src/Root.tsx`**: Defines compositions:
  - `AiNewsVideoVertical`: 1080x1920 (9:16 aspect ratio for YouTube Shorts / TikTok).
  - `AiNewsVideoHorizontal`: 1920x1080 (16:9 aspect ratio for widescreen YouTube).
- **`remotion/src/compositions/MainVideo.tsx`**: Primary video layout synchronizing background motion graphics, B-roll clips, title cards, word captions, and outro cards according to current playback frame.
- **`remotion/src/components/AnimatedBackground.tsx`**: Procedural animated cyber grid and color-shifting radial glow responding to the active beat type (hook, breakthrough, skepticism, outro).
- **`remotion/src/components/Captions.tsx`**: Kinetic typography component rendering high-contrast, highlighted captions word-by-word according to Whisper timestamps.
- **`remotion/src/components/TitleCard.tsx`**: Animated lower-third card displaying the video headline and beat topic.
- **`remotion/src/components/OutroCard.tsx`**: Call-to-action closing card encouraging subscriptions with a spring entrance animation.

---

### Test Suite (`tests/`)

- **`tests/conftest.py`**: Pytest setup providing isolated in-memory SQLite database sessions, repository fixtures, and temporary asset storage.
- **`tests/test_schemas.py`**: Tests data validation and JSON serialization for Pydantic models.
- **`tests/test_storage.py`**: Tests file and byte storage operations for `LocalStorageService`.
- **`tests/test_cost_log.py`**: Tests granular cost tracking and aggregate spend calculations in `CostRepository`.
- **`tests/test_article_and_clustering.py`**: Tests article batch deduplication and cosine clustering accuracy.
- **`tests/test_render_props.py`**: Tests timeline interval calculations, Remotion props generation, dry-run video compilation, and `RenderRepository` lifecycle state changes.
- **`tests/test_services.py`**: Tests `CaptionService` fallback mechanisms under sparse transcription, `RssService` HTML cleaning, and story cluster status progression.

---

## 3. User-Facing Testing Guide & Verification Checklist

This section outlines the primary user-facing components, the exact commands to test them, and what to verify at each stage.

### 1. Step-by-Step CLI Stages
The CLI (`src/cli.py`) is the primary user control panel. Test the stages in sequence:

| Step | Command | What to Verify |
| :--- | :--- | :--- |
| **0. LLM & LiteLLM Config** | `python -m src.cli config-llm --test` | Displays active routing for Planning, Writing, and Embedding models, LiteLLM URL, and tests live connectivity. |
| **1. News Ingestion** | `python -m src.cli ingest` | Fetches live articles from AI feeds. Run twice to confirm deduplication (`Saved 0 new unique articles` on repeat). |
| **2. Story Clustering** | `python -m src.cli cluster --threshold 0.82 --model text-embedding-3-small` | Computes embeddings and groups articles into story clusters. Supports custom embedding models. |
| **3. Script & Dialogue** | `python -m src.cli script --cluster-id 1 --planner-model gpt-4o --writer-model deepseek-chat` | Generates a 2-stage script using custom models for planning and comedic writing via LiteLLM. |
| **4. Voice & Captions** | `python -m src.cli voice --script-id 1` | Synthesizes `.wav` audio and generates word-level `.json` Whisper captions. Confirms complete word alignment. |
| **5. Remotion Render** | `python -m src.cli render --job-id 1 --dry-run` | Validates that Remotion render props are correctly mapped from audio and captions to output video. |
| **6. Cost Audit Log** | `python -m src.cli costs` | Displays granular spend breakdown per stage (TTS, alignment, rendering) and total cost for each video job. |

---

### 2. End-to-End Automated Pipeline
Test the complete hands-off workflow from news ingestion to finished video file:

```bash
# Automated top trending story in 9:16 vertical Short format
python -m src.cli run --auto-top --aspect-ratio 9:16 --dry-run

# Or render a specific cluster for 16:9 widescreen YouTube
python -m src.cli run --cluster-id 2 --aspect-ratio 16:9 --dry-run
```
- **What to verify**: Confirms Prefect successfully orchestrates all tasks (`ingest` → `cluster` → `script` → `voice` → `render`) and outputs the final `.mp4` path in `output/videos/`.

---

### 3. Visual Styling & Remotion Player (Browser Preview)
To visually inspect animations, kinetic subtitle styling, and lower-third cards without rendering full video files:

```bash
cd remotion
npm run start
```
- **What to verify**:
  - Open the Remotion preview URL in your browser.
  - Switch between `AiNewsVideoVertical` (9:16 Shorts) and `AiNewsVideoHorizontal` (16:9 Widescreen).
  - Inspect the kinetic caption highlights in `remotion/src/components/Captions.tsx`.
  - Check the animated gradient grid in `remotion/src/components/AnimatedBackground.tsx`.

---

### 4. Persona & Prompt Customization
Test modifying the editorial voice and narrative pacing:

1. **Host Persona (`prompts/eswar_host_persona.yaml`)**:
   - Edit the system prompt (e.g., adjust the level of sarcasm or add new banned cliches).
   - Re-run `python -m src.cli script --cluster-id 1` and inspect the generated dialogue.
2. **Beat Sheet Pacing (`prompts/beat_sheet.yaml`)**:
   - Adjust beat duration targets (e.g., change target duration from 50s to 30s).
   - Verify that the resulting script adjusts its beat intervals.

---

### 5. API Keys Configuration: LiteLLM Proxy vs. Direct Providers
You can configure keys either in `.env` or pass them directly to any CLI command:

- **Scenario A: Using LiteLLM Proxy or OpenRouter**
  ```bash
  # Set LiteLLM Master/Virtual key and URL in .env:
  python -m src.cli config-llm --litellm-url http://localhost:4000 --litellm-key "sk-litellm-master-key"
  # Or OpenRouter:
  python -m src.cli config-llm --api-base https://openrouter.ai/api/v1 --api-key "sk-or-v1-..."
  ```

- **Scenario B: Direct Provider Keys (No LiteLLM Server Needed)**
  If you don't want to run the LiteLLM proxy container, simply provide direct provider keys:
  ```bash
  # Configure direct keys:
  python -m src.cli config-llm --openai-key "sk-proj-..." --deepseek-key "sk-..." --gemini-key "AIza..."
  ```
  The pipeline will automatically route requests directly to `api.openai.com`, `api.deepseek.com`, and Google GenAI.

- **Scenario C: Passing Keys on the Fly Per Command**
  You don't even need to save keys in `.env` if you prefer not to store them on disk:
  ```bash
  python -m src.cli script --cluster-id 1 --openai-key "sk-proj-..." --deepseek-key "sk-..."
  python -m src.cli cluster --openai-key "sk-proj-..."
  python -m src.cli run --openai-key "sk-proj-..." --deepseek-key "sk-..."
  ```

---

### 6. Embedding Model Configuration (Local vs. BYOK Provider)
Story clustering relies on vector embeddings. You can host embeddings 100% locally or bring any external API key/provider:

- **Mode 1: 100% Local In-Process (`fastembed` - Free, Zero API Keys, Zero Server)**
  Runs quantized ONNX models directly inside Python:
  ```bash
  # Set default to local:
  python -m src.cli config-llm --embedding-model local
  # Or specify a custom Hugging Face model:
  python -m src.cli config-llm --embedding-model "BAAI/bge-small-en-v1.5"
  # Or run clustering on the fly:
  python -m src.cli cluster --model local
  ```

- **Mode 2: Local Server Hosting (Ollama / LocalAI / LM Studio / vLLM)**
  Connect to a locally hosted embedding server exposing OpenAI-compatible endpoints:
  ```bash
  # Ollama with nomic-embed-text or all-minilm:
  python -m src.cli config-llm \
    --embedding-base-url "http://localhost:11434/v1" \
    --embedding-model "nomic-embed-text"
  # Or run cluster on the fly:
  python -m src.cli cluster --embedding-base-url "http://localhost:11434/v1" --model "nomic-embed-text"
  ```

- **Mode 3: Bring Your Own API Key (Google AI Studio, OpenAI, Voyage AI, OpenRouter)**
  ```bash
  # Google AI Studio (Gemini text-embedding-004):
  python -m src.cli config-llm --gemini-key "AIzaSy..." --embedding-model "text-embedding-004"
  # Or on the fly:
  python -m src.cli cluster --gemini-key "AIzaSy..." --model "text-embedding-004"

  # Direct OpenAI:
  python -m src.cli config-llm --openai-key "sk-proj-..." --embedding-model "text-embedding-3-small"
  # Or Voyage AI / Custom Provider:
  python -m src.cli config-llm \
    --embedding-base-url "https://api.voyageai.com/v1" \
    --embedding-key "pa-..." \
    --embedding-model "voyage-3-lite"
  ```

---

### 7. Automated Test Suite
Whenever you modify prompts, templates, or business logic:
```bash
# Run all unit and end-to-end tests:
pytest
# Run lint check:
ruff check src tests
```
- **What to verify**: All 26 tests pass (21 unit tests + 5 E2E integration tests) and linting reports 0 errors.

---

### 8. End-to-End Testing Scenarios Matrix

| Scenario ID | Test Scope | Commands / Inputs | Key Verification |
| :--- | :--- | :--- | :--- |
| **E2E-01** | **Happy Path Pipeline (9:16 Shorts)** | `python -m src.cli run --aspect-ratio 9:16 --dry-run` | Ingestion, clustering, script beats, audio synth, Whisper alignment, vertical Remotion props generated, DB status updated to `completed`. |
| **E2E-02** | **Horizontal Widescreen (16:9)** | `python -m src.cli run --aspect-ratio 16:9 --dry-run` | Composition selection (`AiNewsVideoHorizontal`), 1920x1080 canvas, lower-third layout adjusted. |
| **E2E-03** | **Stage-by-Stage CLI Pipeline** | `ingest` -> `cluster` -> `script` -> `voice` -> `render` -> `costs` | Each CLI stage independently succeeds, passing IDs and state down the pipeline. |
| **E2E-04** | **100% Offline / Local Execution** | `python -m src.cli run --embedding-model local --dry-run` | FastEmbed in-process (384-dim ONNX, 0 API calls), offline script persona fallback, synthetic local audio fallback. Zero network calls, `$0.00` spend. |
| **E2E-05** | **Multi-Provider BYOK Run** | `python -m src.cli run --planner-model gpt-4o-mini --writer-model deepseek-chat --embedding-model text-embedding-004 --gemini-key "AIzaSy..."` | Stage 1 routes to OpenAI, Stage 2 routes to DeepSeek, Embeddings route to Google AI Studio natively via `google-genai`. |
| **E2E-06** | **Full Remotion MP4 Production Render** | `python -m src.cli render --job-id 6` | Headless Chromium executes Remotion bundle, encodes H.264 MP4 with animated SVG grid, kinetic typography, and base64 audio data URI. |
| **E2E-07** | **Cost & Spend Audit Verification** | `python -m src.cli costs` | Detailed breakdown of token/character spend across `script_beat_sheet`, `script_dialogue`, `clustering`, `tts`, and per-video totals. |

---

### 4. Roadmap & Ongoing Tasks
- [x] Test and ensure end-to-end functionality across all CLI stages and test suite.
- [x] Configure and test LiteLLM dynamic model routing for planning, writing, and embeddings directly from the CLI.
- [ ] Document project architecture walkthrough and design patterns.
- [ ] Step-by-step implementation guide for building similar generative media pipelines.

---

## 5. Hands-On CLI User Testing Walkthrough (Interactive End-User Manual)

This manual provides an interactive, step-by-step testing walkthrough for end users to verify that every CLI command, background pipeline stage, asset generator, and render engine functions correctly.

### 0. Environment Setup & CLI Sanity
Before running any tests, activate the virtual environment:
```bash
source /workspaces/silver-tribble/.venv/bin/activate
```
Verify the CLI help screen displays all registered commands:
```bash
python -m src.cli --help
```
* **Success Criteria**: Typer lists all 9 commands: `config-llm`, `setup-db`, `ingest`, `cluster`, `script`, `voice`, `render`, `run`, and `costs`.

---

### Scenario 1: Model Routing & LLM Connectivity Health Check
**Objective**: Verify model routing configuration and test live connectivity to configured LLMs.

#### Step 1.1: Inspect Active Routing
```bash
python -m src.cli config-llm
```
* **Expected Terminal Output**: A Rich table displaying LiteLLM URL/key, Planning model, Writing model, Embedding model, and provider key statuses.
* **Pass Check**: Active settings reflect your desired configuration.

#### Step 1.2: Connectivity Ping (Optional when API keys are configured)
```bash
python -m src.cli config-llm --test
```
* **Pass Check**: Displays `✓ Passed: planning` and `✓ Passed: writing`. (If running offline without keys, it gracefully flags missing credentials without crashing).

---

### Scenario 2: Database Initialization & Sanity Check
**Objective**: Ensure the SQLite database schema and asset directories are provisioned.

```bash
python -m src.cli setup-db
```
* **Expected Terminal Output**: `Database tables initialized successfully.`
* **Files Generated**:
  - SQLite database: [`data/ai_news.db`](file:///workspaces/silver-tribble/data/ai_news.db)
  - Asset directories: `data/assets/audio/`, `data/assets/captions/`, `data/assets/broll/`, `data/assets/render_props/`, `output/videos/`
* **Verification Command**:
  ```bash
  ls -lh data/ai_news.db && ls -d data/assets/* output/videos
  ```
* **Pass Check**: Database file exists and directory paths are present.

---

### Scenario 3: RSS Feed News Ingestion
**Objective**: Test live multi-feed article scraping, content sanitization, and URL hash deduplication.

#### Step 3.1: Initial Fetch
```bash
python -m src.cli ingest
```
* **Expected Terminal Output**: `Ingested X items. Saved Y new unique articles.` (where Y > 0).

#### Step 3.2: Deduplication / Idempotency Check
Run the exact same command a second time immediately:
```bash
python -m src.cli ingest
```
* **Expected Terminal Output**: `Ingested X items. Saved 0 new unique articles.`
* **Verification Command**:
  ```bash
  sqlite3 data/ai_news.db "SELECT id, title, source, published_at FROM articles ORDER BY id DESC LIMIT 5;"
  ```
* **Pass Check**: New articles are visible in the database; re-running does not produce duplicate rows.

---

### Scenario 4: Story Clustering & Semantic Grouping
**Objective**: Test semantic vector embedding and cosine similarity grouping.

#### Option 4A: 100% Offline / Zero-Cost (FastEmbed ONNX)
```bash
python -m src.cli cluster --model local
```
* **Expected Terminal Output**:
  - `Using local in-process ONNX embeddings (model: BAAI/bge-small-en-v1.5)...`
  - A Rich table listing `Cluster ID`, `Articles` count, `Primary Headline`, and `Status` (`PENDING`).

#### Option 4B: Remote / Google AI Studio / OpenAI (With API Keys)
```bash
# Google AI Studio
python -m src.cli cluster --model text-embedding-004 --gemini-key "YOUR_GEMINI_KEY"

# Or OpenAI
python -m src.cli cluster --model text-embedding-3-small --openai-key "YOUR_OPENAI_KEY"
```
* **Verification Command**:
  ```bash
  sqlite3 data/ai_news.db "SELECT id, title, article_count, status FROM story_clusters ORDER BY id DESC LIMIT 5;"
  ```
* **Pass Check**: At least one cluster record is returned with `article_count >= 1`. Note the `Cluster ID` (e.g. `1`) for the next step.

---

### Scenario 5: Script & Comedic Narration Generation
**Objective**: Verify Stage 1 beat sheet structuring and Stage 2 dialogue expansion.

```bash
python -m src.cli script --cluster-id 1 --aspect-ratio 9:16
```
*(Optional: pass `--planner-model`, `--writer-model`, `--openai-key`, `--deepseek-key`, or `--gemini-key` to test custom models).*

* **Expected Terminal Output**:
  - `Generating script for cluster 1 (Planner: ..., Writer: ...)...`
  - `Created script record #X: 'Headline...'`
  - Spoken Narration Script printed in terminal showing host dialogue with hook, meat, and outro beats.
* **Verification Command**:
  ```bash
  sqlite3 data/ai_news.db "SELECT id, cluster_id, title, length(full_narration), target_duration FROM scripts ORDER BY id DESC LIMIT 1;"
  ```
* **Pass Check**: Script record exists with a non-empty `full_narration`. Note the `Script ID` (e.g. `1`) for the next step.

---

### Scenario 6: Voice Synthesis & Word-Level Caption Alignment
**Objective**: Synthesize speech audio and extract word-level timestamps using Whisper.

```bash
python -m src.cli voice --script-id 1 --aspect-ratio 9:16
```
* **Expected Terminal Output**:
  - `Synthesizing TTS audio for script #1...`
  - `Audio generated (XX.Xs): .../data/assets/audio/narration_job_X.wav`
  - `Extracting word timestamps with Whisper...`
  - `Captions extracted (XX words): .../data/assets/captions/captions_job_X.json`
  - `Render job #X prepared for rendering.`
* **Verification Commands**:
  ```bash
  # Check WAV audio file
  ls -lh data/assets/audio/narration_job_*.wav

  # Inspect word-level timestamps in the captions JSON
  head -n 25 data/assets/captions/captions_job_*.json
  ```
* **Pass Check**:
  - Audio duration is between 25s–45s.
  - Captions JSON has entries with `"word"`, `"start"`, and `"end"` float values.
  - A render job record is created in `render_jobs`. Note the `Job ID` for Scenario 7.

---

### Scenario 7: Video Rendering via Remotion
**Objective**: Verify Remotion props preparation and render execution into final MP4 video files.

#### Step 7.1: Fast Dry-Run (Verifies Props serialization without frame rendering)
```bash
python -m src.cli render --job-id 1 --dry-run
```
* **Pass Check**: Terminal outputs `Render completed: ... (dry-run)` and writes [`data/assets/render_props/job_1_props.json`](file:///workspaces/silver-tribble/data/assets/render_props).

#### Step 7.2: Production MP4 Export
```bash
python -m src.cli render --job-id 1
```
* **Expected Terminal Output**:
  - `Writing Remotion render props...`
  - `Rendering video for job #1...`
  - Headless Chromium progress bar: `Bundling... Rendering frames... Finished in XXs`
  - `Render completed: .../output/videos/video_job_1_AiNewsVideoVertical.mp4`
* **Verification Command**:
  ```bash
  ls -lh output/videos/video_job_1_AiNewsVideoVertical.mp4
  ffprobe -i output/videos/video_job_1_AiNewsVideoVertical.mp4 2>&1 | grep -E "Duration|Video:"
  ```
* **Pass Check**:
  - MP4 file exists with size > 1MB.
  - Resolution is `1080x1920` for 9:16 vertical shorts (or `1920x1080` for 16:9 widescreen).
  - Audio and visuals are cleanly multiplexed.

---

### Scenario 8: Single-Command End-to-End Autopilot (`run`)
**Objective**: Verify hands-free orchestration from live RSS scraping to final MP4 video export.

#### Vertical 9:16 Shorts (Autopilot):
```bash
python -m src.cli run --aspect-ratio 9:16 --embedding-model local
```

#### Horizontal 16:9 Landscape (Autopilot):
```bash
python -m src.cli run --aspect-ratio 16:9 --embedding-model local
```

* **Expected Terminal Output**:
  ```text
  Starting AI News to YouTube Video Pipeline
  ...
  Pipeline Run Completed Successfully
  Cluster ID: X
  Script ID:  Y
  Job ID:     Z
  Video File: /workspaces/silver-tribble/output/videos/video_job_Z_AiNewsVideoVertical.mp4
  ```
* **Pass Check**: Pipeline runs autonomously from start to finish and reports valid Cluster, Script, Job IDs and output video file path.

---

### Scenario 9: Financial Telemetry & Cost Audit (`costs`)
**Objective**: Audit the financial tracking system to verify spend recording across all stages.

```bash
python -m src.cli costs
```
* **Expected Terminal Output**:
  1. **Pipeline Spend by Stage Table**: Lists `llm_planning`, `llm_writing`, `text_embedding`, `tts`, `transcription`, `remotion_render` with call counts and USD totals.
  2. **Total Pipeline Spend (USD)**.
  3. **Cost per Video Job Table**: Granular spend attributed to each specific video job.
* **Pass Check**:
  - Local runs with FastEmbed show `$0.00000` for embeddings.
  - All rendered jobs show accurate per-job cost attribution.

---

### Quick Verification Matrix

| Step | Command | Primary Artifact Created / Inspected | Pass Criteria |
| :--- | :--- | :--- | :--- |
| **0. Sanity** | `python -m src.cli --help` | Terminal Help Output | All 9 subcommands visible |
| **1. Config** | `python -m src.cli config-llm` | Terminal Table | Active models & URLs correct |
| **2. DB** | `python -m src.cli setup-db` | `data/ai_news.db` | Tables and asset directories provisioned |
| **3. Ingest** | `python -m src.cli ingest` | `articles` table in DB | Articles saved; 0 new on rerun |
| **4. Cluster**| `python -m src.cli cluster --model local` | `story_clusters` table in DB | At least 1 cluster formed |
| **5. Script** | `python -m src.cli script --cluster-id 1` | `scripts` table in DB | 3-beat narration dialogue generated |
| **6. Voice**  | `python -m src.cli voice --script-id 1` | `data/assets/audio/*.wav`, `data/assets/captions/*.json` | Audio (25-45s) & word timestamps |
| **7. Render** | `python -m src.cli render --job-id 1` | `output/videos/*.mp4` | Valid H.264 MP4 (> 1MB, 1080x1920) |
| **8. E2E**    | `python -m src.cli run` | Final `.mp4` video | End-to-end hands-off completion |
| **9. Costs**  | `python -m src.cli costs` | `cost_tracking` table in DB | Itemized spend per stage and per job |