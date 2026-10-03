# Production QA Test Plan: ai-news-video-pipeline

## Overview

This document defines the complete QA test strategy for the `ai-news-video-pipeline` project. It covers every subsystem across four test layers.

| Layer | Marker | Runner | External Deps |
|---|---|---|---|
| Unit | `@pytest.mark.unit` | `pytest -m unit` | None (all mocked) |
| Integration | `@pytest.mark.integration` | `pytest -m integration` | Mocked HTTP, real SQLite |
| E2E | `@pytest.mark.e2e` | `pytest -m e2e` | Real services or staging |
| Manual (UI) | `@pytest.mark.manual` | Playwright (server must be running) | Live web server |
| PostgreSQL | `@pytest.mark.postgres` | `pytest -m postgres` | Live PostgreSQL server |

**Coverage gate:** 80% statement coverage minimum (`pytest --cov=src --cov-fail-under=80`).

---

## 1. RSS Ingest Service (`test_qa_rss_service.py`)

### 1.1 `clean_html()`

| ID | Scenario | Input | Expected |
|---|---|---|---|
| RSS-01 | Happy path: strips HTML tags | `<b>Hello</b> World` | `Hello World` |
| RSS-02 | Unescapes HTML entities | `AI &amp; ML` | `AI & ML` |
| RSS-03 | Removes newsletter boilerplate | `This story appeared in our AI newsletter.` | `""` (whitespace stripped) |
| RSS-04 | Removes "Sign up for..." boilerplate | `Sign up for our daily AI newsletter.` | empty |
| RSS-05 | Removes "[...]" truncation markers | `OpenAI released [...] a new model` | `OpenAI released a new model` |
| RSS-06 | Empty string returns empty string | `""` | `""` |
| RSS-07 | Collapses multiple spaces | `"AI   is   here"` | `"AI is here"` |

### 1.2 `parse_feed_date()`

| ID | Scenario | Input | Expected |
|---|---|---|---|
| RSS-08 | Uses `published_parsed` when present | entry with `published_parsed` | datetime object |
| RSS-09 | Falls back to `updated_parsed` | entry with no `published_parsed`, has `updated_parsed` | datetime from updated |
| RSS-10 | Returns None when neither field exists | bare entry object | `None` |

### 1.3 `canonicalize_url()`

| ID | Scenario | Input | Expected |
|---|---|---|---|
| RSS-11 | Strips utm_source | `https://tc.com/a?utm_source=rss` | `https://tc.com/a` |
| RSS-12 | Strips utm_medium, utm_campaign | multiple utm params | all stripped |
| RSS-13 | Strips fbclid | `?fbclid=xyz` | no fbclid |
| RSS-14 | Strips gclid | `?gclid=abc` | no gclid |
| RSS-15 | Strips fragment | `https://tc.com/a#comments` | no `#comments` |
| RSS-16 | Lowercases scheme and netloc | `HTTPS://TechCrunch.COM/a` | `https://techcrunch.com/a` |
| RSS-17 | Strips trailing slash on path | `https://tc.com/a/` | `https://tc.com/a` |
| RSS-18 | Preserves root slash | `https://tc.com/` | `https://tc.com/` |
| RSS-19 | Empty string returns empty string | `""` | `""` |
| RSS-20 | Preserves non-tracking query params | `?page=2` | `?page=2` preserved |

### 1.4 `fetch_all_feeds()`

| ID | Scenario | Expected |
|---|---|---|
| RSS-21 | String feed URL: produces FeedItems | FeedItem list with title, link, summary |
| RSS-22 | Dict feed URL: produces FeedItems | FeedItem with correct source name from dict |
| RSS-23 | Skips entries with empty title | entry with `title=""` not included |
| RSS-24 | Skips entries with empty link | entry with `link=""` not included |
| RSS-25 | Continues on feed failure | one feed raises -> other feeds still processed |
| RSS-26 | Returns empty list when all feeds fail | all feeds raise -> `[]` |
| RSS-27 | Handles `None`-like feed_info entries | `None` or unexpected type in list -> skipped |

---

## 2. Article Repository (`test_qa_article_repository.py`)

### 2.1 `save_feed_items()`

| ID | Scenario | Expected |
|---|---|---|
| ART-01 | Saves new articles | returns list of saved Article objects |
| ART-02 | Skips duplicate within same batch | only one saved for same URL in input list |
| ART-03 | Skips URL already in DB | existing URL not re-inserted |
| ART-04 | Empty input list | returns `[]` |
| ART-05 | Items with no link | skipped silently |

### 2.2 Embeddings

| ID | Scenario | Expected |
|---|---|---|
| ART-06 | `get_articles_without_embeddings()` | returns only articles where `embedding IS NULL` |
| ART-07 | `update_article_embedding()` | sets `embedding` field on article |
| ART-08 | `update_article_embedding()` non-existent id | does not raise |
| ART-09 | `get_all_embedded_articles()` | returns only articles where `embedding IS NOT NULL` |

### 2.3 Story Clusters

| ID | Scenario | Expected |
|---|---|---|
| ART-10 | `save_story_cluster()` creates new cluster | returns StoryCluster with `status="pending"` |
| ART-11 | `save_story_cluster()` same hash updates existing | upsert: updates title, summary, article_ids |
| ART-12 | `count_articles()` | returns total article count |
| ART-13 | `count_story_clusters()` no filter | total count |
| ART-14 | `count_story_clusters(status="pending")` | filtered count |
| ART-15 | `count_story_clusters(search="OpenAI")` | matches title or summary |
| ART-16 | `list_story_clusters_paginated()` page 1 | correct items and total |
| ART-17 | `list_story_clusters_paginated()` page 2 | second page items |
| ART-18 | `get_cluster_by_id()` existing | correct cluster |
| ART-19 | `get_cluster_by_id()` missing | `None` |
| ART-20 | `get_articles_by_ids()` list of ids | correct articles |
| ART-21 | `get_articles_by_ids([])` | `[]` |
| ART-22 | `update_cluster_status()` | status field updated |
| ART-23 | `update_cluster_status()` non-existent | does not raise |
| ART-24 | `get_trending_clusters()` | sorted by velocity score descending |
| ART-25 | `get_trending_clusters()` excludes old clusters | clusters older than `hours_back` excluded |

---

## 3. Security Module (`test_qa_security.py`)

### 3.1 Secret Masking

| ID | Scenario | Input | Expected |
|---|---|---|---|
| SEC-01 | Value <= 6 chars | `"abc"` | `"******"` |
| SEC-02 | Value 7-12 chars | `"abcdefghij"` | `"ab******ij"` |
| SEC-03 | Value > 12 chars | `"abcdefghijklmnop"` | `"abc********mnop"` |
| SEC-04 | None | `None` | `None` |
| SEC-05 | Empty string | `""` | `""` |
| SEC-06 | Strips before masking | `"  secret  "` | masked version of `"secret"` |

### 3.2 `mask_dict_secrets()`

| ID | Scenario | Expected |
|---|---|---|
| SEC-07 | Masks `api_key` key | value masked |
| SEC-08 | Masks `openai_api_key` | value masked |
| SEC-09 | Masks `admin_password` | value masked |
| SEC-10 | Masks `token` | value masked |
| SEC-11 | Does NOT mask `username` | value unchanged |
| SEC-12 | Recursively masks nested dict | nested secret masked |
| SEC-13 | Recursively masks list items | list of dicts with secrets masked |
| SEC-14 | Non-string secret value | no crash |

### 3.3 Session Token Management

| ID | Scenario | Expected |
|---|---|---|
| SEC-15 | `generate_session_token()` returns string | non-empty string |
| SEC-16 | Two calls return unique tokens | tokens differ |
| SEC-17 | Generated token is valid | `is_session_token_valid()` returns `True` |
| SEC-18 | Unknown token | `is_session_token_valid()` returns `False` |
| SEC-19 | `None` | `is_session_token_valid(None)` returns `False` |
| SEC-20 | Empty string | `is_session_token_valid("")` returns `False` |
| SEC-21 | `invalidate_session_token()` | token no longer valid |
| SEC-22 | Invalidate non-existent token | no exception |

---

## 4. Auth API Endpoints (`test_qa_auth_api.py`)

### 4.1 GET `/api/auth/status`

| ID | Scenario | Expected |
|---|---|---|
| AUTH-01 | No auth configured | `auth_required=False`, `authenticated=True` |
| AUTH-02 | Auth configured, no cookie | `auth_required=True`, `authenticated=False` |
| AUTH-03 | Valid session cookie | `authenticated=True` |
| AUTH-04 | Invalid cookie | `authenticated=False` |

### 4.2 POST `/api/auth/login`

| ID | Scenario | Expected |
|---|---|---|
| AUTH-05 | Correct password | 200, `status=success`, cookie set |
| AUTH-06 | Correct token | 200, `status=success` |
| AUTH-07 | Password matches `api_auth_token` (third branch) | 200 |
| AUTH-08 | Wrong password | 401 |
| AUTH-09 | Wrong token | 401 |
| AUTH-10 | No auth configured | 200, `status=success`, `Authentication not configured` |
| AUTH-11 | Both password and token are None | correct error or success based on config |
| AUTH-12 | Cookie is HttpOnly | cookie attributes verified |

### 4.3 POST `/api/auth/logout`

| ID | Scenario | Expected |
|---|---|---|
| AUTH-13 | Valid session | 200, cookie cleared, token invalidated |
| AUTH-14 | No cookie | 200, no crash |

### 4.4 `verify_auth_token` dependency

| ID | Scenario | Expected |
|---|---|---|
| AUTH-15 | Valid Bearer header | passes (200 on protected endpoint) |
| AUTH-16 | Valid X-API-Key header | passes |
| AUTH-17 | Valid session cookie | passes |
| AUTH-18 | Invalid Bearer token | 401 |
| AUTH-19 | No credentials, auth configured | 401 |
| AUTH-20 | No credentials, no auth configured | passes (bypass) |

---

## 5. Cost Guardrail Service (`test_qa_cost_guardrail.py`)

### 5.1 `get_budget_status()`

| ID | Scenario | Expected |
|---|---|---|
| COST-01 | No caps configured | `daily_percent=0`, `monthly_percent=0` |
| COST-02 | Spend < daily cap | `daily_exceeded=False` |
| COST-03 | Spend = daily cap (boundary) | `daily_exceeded=True` |
| COST-04 | Spend > daily cap | `daily_exceeded=True` |
| COST-05 | Spend < monthly cap | `monthly_exceeded=False` |
| COST-06 | Spend = monthly cap | `monthly_exceeded=True` |
| COST-07 | Daily cap = 0 | no division by zero, `daily_percent=0` |
| COST-08 | `total_spend_usd` rounded to 4 dp | `round(spend, 4)` |

### 5.2 `can_proceed()`

| ID | Scenario | Expected |
|---|---|---|
| COST-09 | Under both caps | returns `(True, None)` |
| COST-10 | Daily cap exceeded | returns `(False, message)`, calls `send_alert` |
| COST-11 | Monthly cap exceeded | returns `(False, message)`, calls `send_alert` |
| COST-12 | Daily exceeded short-circuits | does not check monthly if daily exceeded |

### 5.3 `send_alert()`

| ID | Scenario | Expected |
|---|---|---|
| COST-13 | No webhook URL | returns `False`, no HTTP call |
| COST-14 | Successful POST | returns `True`, posts correct payload |
| COST-15 | HTTP POST raises | returns `False`, no uncaught exception |
| COST-16 | Records action log on success | ActionLog entry created |

---

## 6. Cost Repository (`test_qa_cost_repository.py`)

| ID | Scenario | Expected |
|---|---|---|
| COSTR-01 | `log_cost()` creates record | CostRecord in DB |
| COSTR-02 | `log_cost()` with zero cost | stores `0.0` |
| COSTR-03 | `get_total_spend()` no records | `0.0` |
| COSTR-04 | `get_total_spend()` sums correctly | sum of all `cost_usd` values |
| COSTR-05 | Two `log_cost()` calls | both stored, sum correct |
| COSTR-06 | Negative cost | stored as-is (test actual behavior) |

---

## 7. Pipeline REST API Endpoints (`test_qa_pipeline_api.py`)

### 7.1 POST `/api/pipeline/ingest`

| ID | Scenario | Expected |
|---|---|---|
| API-01 | Happy path | `status=success`, correct counts |
| API-02 | Service raises | 500 with detail |

### 7.2 POST `/api/pipeline/cluster`

| ID | Scenario | Expected |
|---|---|---|
| API-03 | Happy path | `clusters_created`, `articles_embedded` |
| API-04 | Custom threshold query param | passed to service |
| API-05 | Service raises | 500 |

### 7.3 POST `/api/pipeline/script`

| ID | Scenario | Expected |
|---|---|---|
| API-06 | Happy path | `script_id`, `title`, `word_count` |
| API-07 | Service raises | 500 |

### 7.4 POST `/api/pipeline/voice`

| ID | Scenario | Expected |
|---|---|---|
| API-08 | Happy path | `job_id`, `audio_path`, `duration` |
| API-09 | Script not found | 404 |
| API-10 | TTS raises | 500 |

### 7.5 POST `/api/pipeline/render`

| ID | Scenario | Expected |
|---|---|---|
| API-11 | Happy path sync | `output_video_path` |
| API-12 | `async_mode=True` | 202, `status=queued` |
| API-13 | Job not found | 404 |
| API-14 | Script not found | 404 |
| API-15 | Render raises | 500 |
| API-16 | No auth token sent, auth configured | 401 |
| API-17 | Valid Bearer token | 200 |

### 7.6 POST `/api/pipeline/run`

| ID | Scenario | Expected |
|---|---|---|
| API-18 | `async_mode=True` | 202, queued |
| API-19 | No auth, auth configured | 401 |
| API-20 | Pipeline raises | 500 |

### 7.7 GET `/api/jobs/{job_id}/progress`

| ID | Scenario | Expected |
|---|---|---|
| API-21 | Job exists | 200 with progress dict |
| API-22 | Job not found | 404 |

### 7.8 GET `/api/budget`

| ID | Scenario | Expected |
|---|---|---|
| API-23 | Returns budget fields | all 5 fields present |

### 7.9 POST `/api/pipeline/roundup`

| ID | Scenario | Expected |
|---|---|---|
| API-24 | With cluster_ids | deduplicates and sorts before calling service |
| API-25 | Service raises | 500 |

### 7.10 POST `/api/pipeline/roundup-script`

| ID | Scenario | Expected |
|---|---|---|
| API-26 | With cluster_ids | returns script_id, word_count, beats_count |
| API-27 | No clusters found | 404 |

---

## 8. Render Repository (`test_qa_render_repository.py`)

| ID | Scenario | Expected |
|---|---|---|
| RND-01 | `create_job()` creates RenderJob | correct script_id, aspect_ratio |
| RND-02 | `create_job()` default status | `status="pending"` |
| RND-03 | `get_job_by_id()` existing | correct job |
| RND-04 | `get_job_by_id()` missing | `None` |
| RND-05 | `update_job_audio()` sets fields | `audio_path` and `duration_seconds` updated |
| RND-06 | `update_job_audio()` non-existent id | no exception |
| RND-07 | `update_job_captions()` | `captions_path` updated |
| RND-08 | `list_jobs()` ordered by created_at desc | newest first |
| RND-09 | `list_jobs()` with limit | max n results |
| RND-10 | Idempotency: `update_job_audio()` twice | second call overwrites |

---

## 9. Action Log Repository (`test_qa_action_log_repository.py`)

| ID | Scenario | Expected |
|---|---|---|
| ACT-01 | `record_action()` creates ActionLog | all fields stored |
| ACT-02 | `record_action()` with `job_id=None` | stored without job reference |
| ACT-03 | `record_action()` with details dict | details persisted |
| ACT-04 | `track_operation()` success | records `status="success"` |
| ACT-05 | `track_operation()` exception | records `status="error"`, re-raises |
| ACT-06 | `list_recent_actions()` ordered desc | newest first |
| ACT-07 | `list_recent_actions()` with limit | max n |
| ACT-08 | `list_recent_actions()` stage filter | only matching stage |
| ACT-09 | Two independent calls | both stored, count=2 |

---

## 10. Storage Service (`test_qa_storage_service.py`)

| ID | Scenario | Expected |
|---|---|---|
| STG-01 | `save_file()` saves bytes | file exists at returned path |
| STG-02 | `save_file()` returns path key | string path |
| STG-03 | `get_local_path()` returns Path | `pathlib.Path` object |
| STG-04 | `save_file()` creates parent dirs | no `FileNotFoundError` |
| STG-05 | `save_file()` overwrites existing | new content read back |
| STG-06 | `get_storage_service()` no S3 configured | returns `LocalStorageService` |
| STG-07 | Empty bytes saved | file exists with 0 bytes |

---

## 11. Health Service (`test_qa_health_service.py`)

| ID | Scenario | Expected |
|---|---|---|
| HLT-01 | `get_health_status()` DB ok | `database.ok=True` |
| HLT-02 | `get_health_status()` DB fails | `database.ok=False` |
| HLT-03 | `get_health_status()` storage ok | `storage.ok=True` |
| HLT-04 | `get_health_status()` storage fails | `storage.ok=False` |
| HLT-05 | Response has `overall` field | present |
| HLT-06 | `overall=True` when all checks pass | correct |

---

## 12. Job Queue Service (`test_qa_job_queue.py`)

| ID | Scenario | Expected |
|---|---|---|
| JQ-01 | `submit_render_job()` returns id | unique job id |
| JQ-02 | `submit_pipeline_job()` returns id | unique job id |
| JQ-03 | `get_progress()` unknown id | `None` |
| JQ-04 | `get_progress()` known id | progress dict |
| JQ-05 | New job starts in queued state | `state` field reflects initial status |
| JQ-06 | Two jobs have unique ids | no collision |

---

## 13. Cache Pruning Service (`test_qa_job_queue.py` or separate)

| ID | Scenario | Expected |
|---|---|---|
| PRN-01 | No files to prune | `files_deleted=0` |
| PRN-02 | Old files pruned | `files_deleted > 0` |
| PRN-03 | Recent files not pruned | `files_deleted=0` |
| PRN-04 | Returns `PruneResult` schema | schema validates |

---

## 14. PostgreSQL Integration (`test_qa_postgres_integration.py`)

> All tests skipped when `DATABASE_URL` is not a PostgreSQL URL.

| ID | Scenario | Expected |
|---|---|---|
| PG-01 | `save_feed_items()` in PostgreSQL | articles persisted to real PG |
| PG-02 | Duplicate URL constraint | only one row inserted |
| PG-03 | `update_article_embedding()` with pgvector | embedding stored as vector |
| PG-04 | `get_all_embedded_articles()` from PG | returns embedded articles |
| PG-05 | Paginated cluster list from PG | correct pagination with PG ordering |
| PG-06 | RenderJob round-trip in PG | create and retrieve succeeds |
| PG-07 | ScriptRecord round-trip in PG | create and retrieve succeeds |
| PG-08 | Transaction rollback | data not persisted on error |
| PG-09 | Concurrent writes same URL | one succeeds, other gets integrity error |

---

## 15. Playwright Manual UI Tests (`test_qa_playwright_dashboard.py`)

> Requires: `uvicorn src.web:app` running at `http://localhost:8000`
> Run with: `pytest -m manual --headed` (or `--headless`)

### 15.1 Auth Flow

| ID | Scenario | Steps | Expected |
|---|---|---|---|
| UI-01 | Dashboard loads | Navigate to `/` | Page title contains "AI Video" or similar |
| UI-02 | Login required | Auth configured, navigate to `/` | Login form visible |
| UI-03 | Correct password | Fill password, submit | Redirected to dashboard |
| UI-04 | Wrong password | Fill wrong password, submit | Error message visible |
| UI-05 | Logout | Click logout button | Redirected to login page |

### 15.2 Dashboard Main Page

| ID | Scenario | Expected |
|---|---|---|
| UI-06 | Pipeline status section | Visible and rendered |
| UI-07 | Clusters list | Section exists (may be empty) |
| UI-08 | Budget widget | Shows spend figures |
| UI-09 | Navigation links | Present and have correct `href` |

### 15.3 Pipeline Controls

| ID | Scenario | Expected |
|---|---|---|
| UI-10 | Ingest button present | Element found |
| UI-11 | Cluster button present | Element found |
| UI-12 | Script generation button present | Element found |

### 15.4 Settings Page

| ID | Scenario | Expected |
|---|---|---|
| UI-13 | Watermark text field | Input element present |
| UI-14 | Caption style selector | `<select>` with expected options |
| UI-15 | Subscribe toggle | Checkbox or toggle present |
| UI-16 | Save button | Submit button present |

### 15.5 Responsiveness

| ID | Scenario | Viewport | Expected |
|---|---|---|---|
| UI-17 | Mobile viewport | 375x812 | No horizontal overflow |
| UI-18 | Desktop viewport | 1280x720 | Layout correct |

### 15.6 Error States

| ID | Scenario | Expected |
|---|---|---|
| UI-19 | `/nonexistent` route | 404 response or error page |

---

## 16. Running the Test Suite

```bash
# All unit tests (fast, offline)
pytest -m unit

# Integration tests (mocked externals, SQLite)
pytest -m integration

# E2E tests (requires all services)
pytest -m e2e

# PostgreSQL tests (requires PG server)
DATABASE_URL=postgresql://... pytest -m postgres

# Manual Playwright UI tests (requires running server)
uvicorn src.web:app &
pytest -m manual --headed

# Full suite (excludes manual and postgres by default)
pytest -m "not manual and not postgres"

# Coverage report with 80% gate
pytest --cov=src --cov-report=term-missing --cov-fail-under=80 -m "not manual and not postgres"

# Run ruff before tests
ruff check . && ruff format --check . && pytest
```

---

## 17. Test File Index

| File | Layer | Subsystem |
|---|---|---|
| `test_qa_rss_service.py` | unit | RSS ingest |
| `test_qa_article_repository.py` | unit | Article/cluster DB |
| `test_qa_security.py` | unit | Token, masking, session |
| `test_qa_auth_api.py` | integration | Auth endpoints |
| `test_qa_cost_guardrail.py` | unit + integration | Budget enforcement |
| `test_qa_cost_repository.py` | unit | Cost DB |
| `test_qa_pipeline_api.py` | integration | All pipeline endpoints |
| `test_qa_render_repository.py` | unit | RenderJob DB |
| `test_qa_action_log_repository.py` | unit | ActionLog DB |
| `test_qa_storage_service.py` | unit | Local/S3 storage |
| `test_qa_health_service.py` | unit | Health checks |
| `test_qa_job_queue.py` | unit | Async job queue + cache pruning |
| `test_qa_postgres_integration.py` | postgres | PG-specific behavior |
| `test_qa_playwright_dashboard.py` | manual | Browser UI |
