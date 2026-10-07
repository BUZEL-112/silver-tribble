# Production Dockerfile for AI Video Production Platform
FROM python:3.12-slim-bookworm

LABEL maintainer="AI Video Production Studio"
LABEL description="Production container with FastAPI, Remotion, Chromium, and FFmpeg"

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_CONFIG_FILE=/data/config.yaml \
    DATA_DIR=/data

# Install system utilities, FFmpeg, and Chromium rendering libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gnupg \
    ca-certificates \
    ffmpeg \
    git \
    fonts-liberation \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libxkbcommon0 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libxshmfence1 \
    libglu1-mesa \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 22 LTS
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user with UID 1000 for Hugging Face Spaces compliance
RUN useradd -m -u 1000 user || true

WORKDIR /app

# Install Python project dependencies
COPY pyproject.toml /app/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# Install Remotion dependencies
COPY remotion/package*.json /app/remotion/
WORKDIR /app/remotion
RUN npm ci --prefer-offline --no-audit || npm install --no-audit
WORKDIR /app

# Copy application source code and configuration templates
COPY src/ /app/src/
COPY prompts/ /app/prompts/
COPY remotion/ /app/remotion/
COPY scripts/ /app/scripts/
COPY config_example.yaml /app/config_example.yaml

# Create persistent storage directories and assign permissions for UID 1000
RUN mkdir -p /data/assets /data/media /data/audio /data/captions /data/render_props /app/output/videos /app/artifacts/media \
    && chown -R 1000:1000 /app /data /home/user \
    && chmod -R 777 /data /app/output /app/artifacts \
    && chmod +x /app/scripts/docker_entrypoint.sh

# Expose default Hugging Face Spaces port (7860)
EXPOSE 7860

VOLUME ["/data", "/app/output"]

USER 1000
ENV HOME=/home/user \
    PORT=7860

ENTRYPOINT ["/app/scripts/docker_entrypoint.sh"]
