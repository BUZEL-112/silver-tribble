---
name: ai-video
description: >-
  Autonomous AI News to YouTube Video Production CLI and REST API client.
  Use when asked to ingest AI news, discover trending story clusters, generate
  beat sheets and comedic narration scripts, synthesize audio voiceovers, assemble
  b-roll visual media, render MP4 videos via Remotion, check job rendering progress,
  or publish videos to YouTube.
---

# AI Video Production Studio: Agent Skill Guide

This skill guides AI agents (in Cursor, Claude Code, Antigravity, OpenHands, or autonomous loops) to programmatically interact with the AI Video Production Studio using either:
1. **Remote HTTP Mode** (Recommended): Interacting with a running production container via REST API without requiring local Node.js, Chromium, or Whisper dependencies.
2. **Local Workspace Mode**: Executing directly against the local Python repository environment.

---

## 1. Quick Start & Environment Configuration

Set the target server and optional API token in your environment:

```bash
# Target containerized production server
export AI_VIDEO_SERVER="http://localhost:8000"
export AI_VIDEO_API_KEY="your-optional-bearer-token"
```

To verify connectivity and server health:

```bash
python -m src.cli health --json
```

---

## 2. Core Workflow Commands

### Step 1: Ingest News Feeds
Fetch recent articles from configured AI news feeds (TechCrunch, ArXiv, The Verge, VentureBeat):

```bash
# Ingest news feeds headlessly
python -m src.cli ingest --json
```

### Step 2: Discover and List Story Clusters
List semantically grouped news clusters with constituent article counts:

```bash
# List top trending story clusters as machine-readable JSON
python -m src.cli clusters --limit 5 --json
```

Output format:
```json
{
  "status": "success",
  "count": 5,
  "clusters": [
    {
      "id": 12,
      "title": "OpenAI Announces Strawberry Reasoning Architecture",
      "article_count": 4,
      "status": "pending"
    }
  ]
}
```

### Step 3: Generate Script for a Story Cluster
Generate a 2-stage narrative beat sheet and comedic host dialogue:

```bash
# Generate script for cluster #12 in 9:16 vertical shorts format
python -m src.cli script --cluster-id 12 --aspect-ratio 9:16 --json

# Generate script for widescreen documentary (16:9) format
python -m src.cli script --cluster-id 12 --aspect-ratio 16:9 --json
```

Output format:
```json
{
  "status": "success",
  "script_id": 45,
  "title": "OpenAI's Strawberry Is Actually Insane",
  "word_count": 185,
  "beats_count": 5
}
```

### Step 4: Synthesize Voice and Align Subtitle Captions
Generate speech audio and compute word-level subtitle alignment:

```bash
# Generate voice audio and word captions for script #45
python -m src.cli voice --script-id 45 --aspect-ratio 9:16 --json
```

Output format:
```json
{
  "status": "success",
  "job_id": 88,
  "audio_path": "/data/audio/audio_job_88.wav",
  "captions_count": 192,
  "duration_seconds": 42.5
}
```

### Step 5: Gather and Route Visual Media
Select b-roll videos, entity photos, and reaction GIFs for narrative beats:

```bash
# Gather visual assets for job #88
python -m src.cli media --job-id 88 --json
```

### Step 6: Render Final Video MP4
Trigger Remotion video rendering. Use `--async` for detached queue execution or `--dry-run` for fast pipeline testing:

```bash
# Asynchronous queue dispatch (returns immediately with job ID)
python -m src.cli render --job-id 88 --async --json

# Dry-run render (simulates rendering without Chromium compile)
python -m src.cli render --job-id 88 --dry-run --json
```

Output format:
```json
{
  "status": "queued",
  "job_id": 88,
  "message": "Render job dispatched to queue"
}
```

### Step 7: Poll Job Progress and Retrieve Output
Check rendering stage and obtain the finalized video path or CDN URL:

```bash
# Check execution status for job #88
python -m src.cli status --job-id 88 --json
```

Output format:
```json
{
  "job_id": 88,
  "status": "completed",
  "stage": "completed",
  "percent": 100,
  "output_video_path": "/app/output/videos/job_88_final.mp4"
}
```

### Step 8: Publish Completed Video to YouTube
Publish the rendered video directly to the connected YouTube channel:

```bash
# Upload to YouTube as unlisted video
python -m src.cli publish-youtube --job-id 88 --privacy unlisted --json
```

Output format:
```json
{
  "status": "success",
  "video_id": "dQw4w9WgXcQ",
  "video_url": "https://youtu.be/dQw4w9WgXcQ",
  "privacy_status": "unlisted"
}
```

---

## 3. End-to-End Autonomous Run

To execute the entire pipeline autonomously for the top trending story cluster in a single invocation:

```bash
# Run full pipeline end-to-end in async mode
python -m src.cli run --auto-top --aspect-ratio 9:16 --async --json
```

---

## 4. Cost and Budget Audit

Inspect spend breakdown across LLMs, TTS characters, and media generation:

```bash
# Inspect total platform expenditure
python -m src.cli costs --json
```
