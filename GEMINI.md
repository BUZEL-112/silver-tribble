# Gemini Context and Review Instructions

## Project Overview

`ai-news-video-pipeline` is an automated pipeline that discovers AI news, synthesizes news clusters, generates scripts, produces audio narrations, inspects media assets, and renders videos using Prefect, Google Gemini / LLMs, and Remotion.

## Directory Structure and Architecture

The codebase adheres strictly to layered architecture with one-way dependencies:
`API / CLI -> Services -> Repositories -> Models / Database`

- `src/cli.py` & `src/web.py`: CLI entry points (Typer) and web dashboard (FastAPI). No business logic allowed here.
- `src/services/`: Core domain business logic (RSS fetching, clustering, script generation, audio synthesis, media routing, Remotion rendering).
- `src/repositories/`: Data access layer for database entities and logs via SQLAlchemy.
- `src/models/`: Pydantic schemas and SQLAlchemy database entities.
- `src/flows/`: Prefect pipeline workflows orchestrating service tasks.
- `scripts/`: Operational scripts and automation tools.
- `tests/`: Pytest test suite covering unit and integration behaviors.

## Development and Review Guidelines

When reviewing code or pull requests:
1. Verify Single Responsibility Principle (SRP): Each function, class, and module has one clear responsibility.
2. Verify Separation of Concerns: Ensure business logic does not leak into CLI handlers, API endpoints, or database models.
3. Verify Type Hints: All public APIs, service methods, and models must include explicit type annotations.
4. Verify Fail Fast: Inputs must be validated early, raising explicit exceptions.
5. Verify Test Coverage: Behavior changes must be covered by automated tests in `tests/`.
6. Verify Code Formatting: Code must pass `ruff check` and `ruff format`.
7. Tone and Style: Do not use emojis or em-dashes in code comments, docstrings, or reviews.

## Commands

- Run linter: `ruff check .`
- Run formatter: `ruff format --check .`
- Run test suite: `pytest`
- Type checker: `mypy src`
