# Production Deployment Plan: Zero-Cost Serverless AI Video Pipeline

This document details the complete production deployment architecture, step-by-step setup commands, and continuous deployment workflow for running the AI News Video Production platform at zero monthly infrastructure cost ($0/month).

---

## 1. Architecture Topology

```
+-----------------------------------------------------------------------------------+
|                                  CLIENT LAYER                                     |
|                                                                                   |
|  [GitHub Pages]               or               [Hugging Face Static Space]        |
|  - Free global CDN                             - Free static hosting              |
|  - Serves index.html                           - Serves index.html                |
|  - Stores API_AUTH_TOKEN in localStorage       - Proxies calls to Cloud Run       |
+-----------------------------------------------------------------------------------+
                                        |
                      HTTPS REST API    | (Bearer Auth + CORS)
                                        v
+-----------------------------------------------------------------------------------+
|                             BACKEND COMPUTE LAYER                                 |
|                                                                                   |
|  [Google Cloud Run]                                                               |
|  - Serverless container running FastAPI, Remotion, FFmpeg, and Prefect            |
|  - Scales to 0 instances when idle (Zero cost)                                    |
|  - Flags: --timeout 900, --no-cpu-throttling, --min-instances 0, --max-instances 1|
|  - Memory: 2GiB, CPU: 2 vCPU                                                      |
+-----------------------------------------------------------------------------------+
                           |                                   |
           SQL Engine      |                   S3 Storage API  |
           (psycopg2)      |                   (boto3)         |
                           v                                   v
+------------------------------------+   +------------------------------------------+
|          DATABASE LAYER            |   |               STORAGE LAYER              |
|                                    |   |                                          |
|  [Supabase PostgreSQL]             |   |  [Supabase Storage S3 Bucket]            |
|  - Free 500 MB database            |   |  - S3-compatible asset bucket (1 GB free)|
|  - pgvector extension enabled      |   |  - Persists audio, captions, and MP4s    |
|  - Port 5432/6543 pooler (IPv4)    |   |  - Survives container scale-down cycles  |
+------------------------------------+   +------------------------------------------+
```

---

## 2. Monthly Free Tier Budget and Guardrails

All services renew their free quotas monthly. Setting strict container limits ensures zero billing.

| Component | Free Monthly Allowance | Configured Cap | Monthly Cost |
| :--- | :--- | :--- | :--- |
| **Google Cloud Run** | 2,000,000 requests, 360,000 vCPU-seconds, 180,000 GiB-seconds | `--max-instances 1`, `--min-instances 0` | **$0.00** |
| **Supabase Database** | 500 MB database storage, 5 GB monthly egress | Indexed tables, pruned temporary caches | **$0.00** |
| **Supabase Storage** | 1 GB storage, 2 GB monthly download | Pruned intermediate video clips | **$0.00** |
| **GitHub Pages** | Unlimited static visits, 100 GB monthly bandwidth | Static SPA delivery | **$0.00** |
| **Hugging Face Static** | Unlimited public views | Static Space mirrors GitHub Pages | **$0.00** |

### Hard Guardrails

1. **Max Instances Cap**: Passing `--max-instances 1` to Cloud Run blocks accidental auto-scaling spikes.
2. **Billing Alert**: Set a $0.01 threshold alert inside the Google Cloud Billing console.
3. **Inactivity Handling**: Supabase free-tier projects sleep after 7 days of complete inactivity. Running a daily scheduled test or ping maintains active status.

---

## 3. Environment Variables and Secrets Reference

Prepare these secrets before running deployment commands:

| Variable Name | Required | Description | Example / Target Value |
| :--- | :--- | :--- | :--- |
| `DATABASE_URL` | Yes | Supabase connection pooler string | `postgresql://postgres.[REF]:[PW]@aws-0-[REG].pooler.supabase.com:5432/postgres?sslmode=require` |
| `API_AUTH_TOKEN` | Yes | Pre-shared token to protect Cloud Run endpoints | Secure random 32-character string |
| `STORAGE_BACKEND` | Yes | Persist files to S3-compatible cloud storage | `s3` |
| `R2_ACCOUNT_ID` | Yes | Supabase Project Reference for S3 | `[YOUR_SUPABASE_PROJECT_REF]` |
| `R2_ACCESS_KEY_ID` | Yes | Supabase S3 Access Key ID | Generated from Supabase Storage settings |
| `R2_SECRET_ACCESS_KEY` | Yes | Supabase S3 Secret Access Key | Generated from Supabase Storage settings |
| `R2_BUCKET_NAME` | Yes | Name of your storage bucket | `ai-news-assets` |
| `R2_PUBLIC_URL` | Yes | Public or CDN URL prefix for assets | `https://[REF].supabase.co/storage/v1/object/public/ai-news-assets` |
| `OPENAI_API_KEY` | Yes | Beat planning and embeddings | `sk-proj-...` |
| `DEEPSEEK_API_KEY` | Yes | Persona dialogue writing | `sk-...` |
| `GEMINI_API_KEY` | Yes | Speech synthesis and media inspection | `AIzaSy...` |
| `PEXELS_API_KEY` | Optional| Stock footage search | Stock API key |
| `GIPHY_API_KEY` | Optional| GIF search | Giphy API key |

---

## 4. Step 1: Supabase Setup (Database and Storage)

### 1. Create a Supabase Project
1. Log in to [Supabase](https://supabase.com/) and click **New Project**.
2. Set a strong database password and select your closest AWS region.

### 2. Enable pgvector Extension and Provision Schema
Open the Supabase **SQL Editor** and execute the contents of [scripts/supabase_schema.sql](file:///teamspace/studios/this_studio/silver-tribble/scripts/supabase_schema.sql):

```sql
-- Enable vector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Provision all tables and indexes
-- (Paste complete scripts/supabase_schema.sql contents)
```

Alternatively, run the verification script locally to provision the tables automatically:
```bash
python scripts/test_supabase_connection.py "postgresql://postgres.[REF]:[PW]@aws-0-[REG].pooler.supabase.com:5432/postgres?sslmode=require" --migrate
```

### 3. Retrieve Connection String
In Supabase, navigate to **Project Settings** -> **Database** -> **Connection string** -> **URI**.
Select **Connection Pooler** (Supavisor) in **Session mode** (Port `5432`).
> Cloud Run operates over IPv4. The connection pooler URL (`aws-0-[region].pooler.supabase.com`) supports IPv4, whereas the direct URL (`db.[ref].supabase.co`) requires IPv6.

### 4. Create an S3 Storage Bucket
1. In the Supabase Dashboard, go to **Storage** -> **New Bucket**.
2. Name the bucket `ai-news-assets` and toggle **Public bucket** to ON.
3. Navigate to **Project Settings** -> **Storage** -> **S3 Access Keys**.
4. Generate a new key and note the `Access Key ID` and `Secret Access Key`.
5. The S3 endpoint is: `https://[PROJECT-REF].supabase.co/storage/v1/s3`.

---

## 5. Step 2: Google Cloud Run Deployment

### 1. Authenticate and Configure Google Cloud CLI
```bash
# Login to your Google Cloud account
gcloud auth login

# Set project ID
export PROJECT_ID="your-gcp-project-id"
export REGION="us-central1"
gcloud config set project "${PROJECT_ID}"

# Enable required Google APIs
gcloud services enable \
  artifactregistry.googleapis.com \
  run.googleapis.com \
  cloudbuild.googleapis.com
```

### 2. Create Artifact Registry Repository
```bash
gcloud artifacts repositories create ai-video-repo \
  --repository-format=docker \
  --location="${REGION}" \
  --description="AI Video Pipeline Docker repository"
```

### 3. Build and Submit Container Image
Run from the root of this repository:
```bash
gcloud builds submit --tag "${REGION}-docker.pkg.dev/${PROJECT_ID}/ai-video-repo/ai-video-pipeline:v1" .
```

### 4. Deploy Container to Cloud Run
Deploy with flags configured for background video rendering and zero-cost idle state:

```bash
gcloud run deploy ai-video-pipeline \
  --image="${REGION}-docker.pkg.dev/${PROJECT_ID}/ai-video-repo/ai-video-pipeline:latest" \
  --region="${REGION}" \
  --platform=managed \
  --allow-unauthenticated \
  --port=7860 \
  --min-instances=0 \
  --max-instances=1 \
  --cpu=2 \
  --memory=2Gi \
  --timeout=900 \
  --no-cpu-throttling \
  --set-env-vars="STORAGE_BACKEND=s3" \
  --set-env-vars="R2_BUCKET_NAME=bucket1" \
  --set-env-vars="R2_ACCOUNT_ID=[SUPABASE_PROJECT_REF]" \
  --set-env-vars="R2_PUBLIC_URL=https://[SUPABASE_PROJECT_REF].supabase.co/storage/v1/object/public/bucket1" \
  --set-env-vars="S3_ENDPOINT_URL=https://[SUPABASE_PROJECT_REF].supabase.co/storage/v1/s3" \
  --set-env-vars="DATABASE_URL=postgresql://postgres.[REF]:[PW]@aws-0-[REG].pooler.supabase.com:5432/postgres?sslmode=require" \
  --set-env-vars="API_AUTH_TOKEN=your-random-32-char-token" \
  --set-env-vars="R2_ACCESS_KEY_ID=your_s3_key_id" \
  --set-env-vars="R2_SECRET_ACCESS_KEY=your_s3_secret" \
  --set-env-vars="GEMINI_API_KEY=your_gemini_key"
```

After deployment, note the public service URL output by Google Cloud (e.g., `https://ai-video-pipeline-888975339891.us-central1.run.app`).

---

## 6. Step 3: Frontend Deployment

### Option A: GitHub Pages Deployment

1. The frontend entry point is [index.html](file:///teamspace/studios/this_studio/silver-tribble/index.html).
2. Configure the API endpoint in your frontend code or pass it dynamically:
   In [index.html](file:///teamspace/studios/this_studio/silver-tribble/index.html), add or verify the backend URL target:
   ```javascript
   const BACKEND_API_URL = window.localStorage.getItem("ai_video_api_url") || "https://ai-video-pipeline-xyz.a.run.app";
   const AUTH_TOKEN = window.localStorage.getItem("ai_video_auth_token") || "your-token";
   ```
3. Push to your GitHub repository:
   ```bash
   git add index.html
   git commit -m "Configure production frontend entrypoint"
   git push origin main
   ```
4. In GitHub: Navigate to **Settings** -> **Pages** -> **Build and deployment**.
5. Set Source to **Deploy from a branch**, Branch to `main`, and folder to `/ (root)`.
6. Your UI will be live at `https://<username>.github.io/<repo>/`.

### Option B: Hugging Face Static Space Mirror

1. Create a new Space on [Hugging Face](https://huggingface.co/new-space) with SDK set to **Static**.
2. Clone your new Hugging Face Space repository:
   ```bash
   git clone https://huggingface.co/spaces/<username>/ai-video-static
   cd ai-video-static
   ```
3. Copy `index.html` into the Space repository.
4. Add the Hugging Face frontmatter to `README.md`:
   ```yaml
   ---
   title: AI Video Studio Portfolio
   colorFrom: blue
   colorTo: indigo
   sdk: static
   pinned: false
   ---
   ```
5. Commit and push:
   ```bash
   git add README.md index.html
   git commit -m "Deploy static interface to Hugging Face Space"
   git push
   ```

---

## 7. Step 4: Turnkey GitHub Actions CI/CD Pipeline

To automate backend builds and frontend publishing on git push, create `.github/workflows/deploy.yml`:

```yaml
name: Production Deployment Pipeline

on:
  push:
    branches:
      - main

jobs:
  deploy-backend:
    name: Build & Deploy Backend to Cloud Run
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Code
        uses: actions/checkout@v4

      - name: Authenticate to Google Cloud
        uses: google-github-actions/auth@v2
        with:
          credentials_json: ${{ secrets.GCP_SA_KEY }}

      - name: Setup Cloud SDK
        uses: google-github-actions/setup-gcloud@v2

      - name: Configure Docker for Artifact Registry
        run: gcloud auth configure-docker us-central1-docker.pkg.dev

      - name: Build and Push Docker Image
        run: |
          IMAGE_TAG="us-central1-docker.pkg.dev/${{ secrets.GCP_PROJECT_ID }}/ai-video-repo/ai-video-pipeline:${{ github.sha }}"
          docker build -t "$IMAGE_TAG" .
          docker push "$IMAGE_TAG"

      - name: Deploy to Cloud Run
        run: |
          IMAGE_TAG="us-central1-docker.pkg.dev/${{ secrets.GCP_PROJECT_ID }}/ai-video-repo/ai-video-pipeline:${{ github.sha }}"
          gcloud run deploy ai-video-pipeline \
            --image="$IMAGE_TAG" \
            --region=us-central1 \
            --platform=managed \
            --min-instances=0 \
            --max-instances=1 \
            --cpu=2 \
            --memory=2Gi \
            --timeout=900 \
            --no-cpu-throttling \
            --update-env-vars="API_AUTH_TOKEN=${{ secrets.API_AUTH_TOKEN }},DATABASE_URL=${{ secrets.DATABASE_URL }}"

  deploy-frontend:
    name: Publish GitHub Pages
    runs-on: ubuntu-latest
    needs: deploy-backend
    permissions:
      pages: write
      id-token: write
    steps:
      - name: Checkout Code
        uses: actions/checkout@v4

      - name: Setup Pages
        uses: actions/configure-pages@v4

      - name: Upload Artifact
        uses: actions/upload-pages-artifact@v3
        with:
          path: "."

      - name: Deploy to GitHub Pages
        id: deployment
        uses: actions/deploy-pages@v4
```

### Required GitHub Repository Secrets
Under **Settings** -> **Secrets and variables** -> **Actions**, add:
- `GCP_PROJECT_ID`: Your Google Cloud Project ID.
- `GCP_SA_KEY`: JSON service account key with `Artifact Registry Writer` and `Cloud Run Admin` roles.
- `API_AUTH_TOKEN`: Your random secret bearer token.
- `DATABASE_URL`: Your Supabase PostgreSQL pooler connection URL.

---

## 8. Step 5: Verification and Runbook

### Health Check Verification
Verify backend health from terminal:
```bash
curl -i https://<YOUR_CLOUD_RUN_URL>/api/health
```
Expected response:
```json
{
  "status": "healthy",
  "database": "connected",
  "storage": "accessible"
}
```

### Protected Endpoint Check
Verify bearer token authentication:
```bash
# Should return HTTP 401 Unauthorized
curl -i https://<YOUR_CLOUD_RUN_URL>/api/stats

# Should return HTTP 200 OK
curl -i -H "Authorization: Bearer <YOUR_API_AUTH_TOKEN>" https://<YOUR_CLOUD_RUN_URL>/api/stats
```

### End-to-End Test Run
Trigger a dry-run video pipeline test:
```bash
curl -X POST https://<YOUR_CLOUD_RUN_URL>/api/pipeline/run \
  -H "Authorization: Bearer <YOUR_API_AUTH_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"aspect_ratio": "9:16", "dry_run": true, "async_mode": true}'
```
Expected response:
```json
{
  "status": "queued",
  "job_id": 1,
  "message": "Pipeline run dispatched to background queue"
}
```

Poll progress until finished:
```bash
curl -H "Authorization: Bearer <YOUR_API_AUTH_TOKEN>" https://<YOUR_CLOUD_RUN_URL>/api/jobs/1/progress
```

---

## 9. Troubleshooting Common Issues

1. **Database connection times out on Cloud Run**:
   - Check if the URL uses `db.[ref].supabase.co` instead of the pooler. Change the host to `aws-0-[region].pooler.supabase.com:5432` to ensure IPv4 reachability.
   - Verify `?sslmode=require` is present at the end of the connection string.
2. **Remotion fails with Chromium sandbox error**:
   - The container must run with `--no-sandbox`. This is already configured in the Dockerfile and entrypoint script.
3. **CORS errors when calling Cloud Run from GitHub Pages**:
   - Ensure the request does not omit headers. [src/web.py](file:///teamspace/studios/this_studio/silver-tribble/src/web.py) allows all origins (`allow_origins=["*"]`).
4. **Cloud Run instance memory exhausted during video render**:
   - If rendering complex multi-layer horizontal videos, increase container memory from 2Gi to 4Gi (`--memory 4Gi`), which still falls within free tier limits when capped at 1 instance.
