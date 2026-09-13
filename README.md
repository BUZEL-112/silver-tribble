# AI News to YouTube Video Pipeline

Automated, resilient pipeline turning daily AI news into stylized, comedic video shorts and widescreen episodes using Prefect, LiteLLM, Google GenAI, and Remotion.

---

## Architecture Overview

```
[RSS Feeds]
     │
     ▼
[RssService] ──► [Postgres / pgvector]
     │
     ▼
[ClusteringService] (OpenAI text-embedding-3-small via LiteLLM)
     │
     ▼
[ScriptService] (Two-Stage Chaining: gpt-4o-mini Beat Sheet + DeepSeek Comedic Dialogue)
     │
     ▼
[TtsService] (Google GenAI Speech Synthesis)
     │
     ▼
[CaptionService] (faster-whisper Word-Level Alignment)
     │
     ▼
[RenderService] (Subprocess bridge to Remotion React Engine)
     │
     ▼
[Final MP4 Video + Cost Audit Log]
```

---

## Core Capabilities (Phase 0 and Phase 1 MVP)

- **Orchestration**: Built on Prefect 3.x with retries, task checkpointing, and execution state tracking.
- **Cost Visibility**: Granular `cost_log` tracking per LLM call, TTS character count, alignment runtime, and render compute time.
- **Multi-Model Routing**: LiteLLM proxy container providing unified OpenAI-compatible routing and automated fallback across `gpt-4o-mini` and `deepseek-chat`.
- **Procedural Video Fallbacks**: Remotion video engine renders animated dynamic background grids and kinetic typography when stock B-roll clips are omitted.
- **Dual Formats**: Supports 9:16 vertical (YouTube Shorts / TikTok) and 16:9 horizontal widescreen formats via composition properties.
- **Storage Independence**: Abstract `StorageService` adapter supporting local disk storage for development and S3 / Cloudflare R2 for cloud deployments.

---

## VM Setup and Installation Guide

Follow these steps to deploy and run the pipeline on your Linux/Ubuntu or Windows cloud VM:

### 1. System Prerequisites

Ensure the VM has Docker, Python 3.11+, and Node.js 18+ installed:

```bash
# Ubuntu / Debian setup
sudo apt update
sudo apt install -y python3-pip python3-venv ffmpeg git curl

# Install Docker and Docker Compose
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER

# Install Node.js 20 LTS
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
```

### 2. Clone and Configure Environment

```bash
# Copy environment configuration
cp .env.example .env

# Edit .env with your provider credentials:
# - OPENAI_API_KEY
# - DEEPSEEK_API_KEY
# - GEMINI_API_KEY
nano .env
```

### 3. Start Infrastructure Services

Start the PostgreSQL database (with `pgvector`) and LiteLLM proxy containers:

```bash
docker compose up -d
```

Check container health:
```bash
docker compose ps
```

### 4. Setup Python Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

pip install --upgrade pip
pip install -e ".[dev]"
```

### 5. Setup Remotion Video Engine

```bash
cd remotion
npm install
cd ..
```

---

## Pipeline CLI Usage

The system exposes a rich CLI for running individual stages or end-to-end jobs:

### 1. Initialize Database
Create schema tables and vector extensions:
```bash
python -m src.cli setup-db
```

### 2. Ingest AI News
Fetch entries from curated AI RSS feeds:
```bash
python -m src.cli ingest
```

### 3. Cluster and Detect Stories
Generate embeddings and inspect grouped story clusters:
```bash
python -m src.cli cluster --threshold 0.82
```

### 4. Generate Script for a Story
Run the two-stage LLM generator for a specific cluster:
```bash
python -m src.cli script --cluster-id 1 --aspect-ratio 9:16
```

### 5. Synthesize Audio and Word Captions
Synthesize TTS voice and compute Whisper alignment:
```bash
python -m src.cli voice --script-id 1 --aspect-ratio 9:16
```

### 6. Render Video
Invoke Remotion to compile the finalized video:
```bash
python -m src.cli render --job-id 1
```

### 7. Run End-to-End Pipeline
Trigger the complete pipeline in one command:
```bash
# Automatically pick the largest trending cluster and render 9:16 Shorts
python -m src.cli run --auto-top --aspect-ratio 9:16

# Run in dry-run mode (mock rendering without Node dependency)
python -m src.cli run --auto-top --dry-run
```

### 8. Inspect Cost Log
Display per-stage invocations, total spend, and per-video costs:
```bash
python -m src.cli costs
```

---

## Running Automated Tests

Execute unit and integration tests using pytest:

```bash
pytest
```
