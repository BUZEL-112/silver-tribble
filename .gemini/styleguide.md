# Code Style and Review Guide for Gemini Code Assist

## Core Architecture and Layering

This repository follows a strict layered architecture with one-way dependencies:
API / Routes -> Services -> Repositories -> Models / Database

1. API and Entry Points (`src/cli.py`, `src/web.py`):
   - Responsible strictly for argument parsing, request routing, and input validation.
   - Must not contain business logic or direct database queries.
   - Delegate all processing to dedicated services.

2. Services Layer (`src/services/`):
   - Encapsulates all business logic, workflow rules, and external integrations.
   - Services must be decoupled from the web framework and CLI tooling.
   - Depend on repositories for persistence and external clients via dependency injection.

3. Repositories Layer (`src/repositories/`):
   - Encapsulates all database queries and data persistence operations.
   - Return entity or domain model instances, not raw database rows.

4. Models Layer (`src/models/`):
   - Contains data structures: Pydantic schemas for data exchange and SQLAlchemy entities for persistence.
   - Database models must not contain business logic.

## Engineering Principles

1. Single Responsibility Principle (SRP):
   - Every module, class, and function must have a single, well-defined responsibility.
   - Keep functions small, focused, and straightforward to test.

2. Separation of Concerns:
   - Keep data access, business operations, and presentation isolated.

3. DRY (Don't Repeat Yourself):
   - Extract common functionality into reusable helpers without over-abstracting prematurely.

4. KISS (Keep It Simple):
   - Favor readable and maintainable solutions over clever or complex designs.

5. YAGNI (You Aren't Gonna Need It):
   - Implement only what is required by current specifications.

6. Type Hints:
   - Provide complete type annotations for all public functions, methods, and data attributes.

7. Fail Fast:
   - Validate inputs at boundaries and raise clear, descriptive exceptions immediately.

8. Formatting and Quality:
   - Code must conform to Ruff formatting and linting rules (line-length 100).
   - Use meaningful, descriptive identifiers instead of ambiguous abbreviations.
   - Do not use emojis or em-dashes in log messages, docstrings, or code comments.

9. Testing:
   - All behavioral changes and new capabilities must include automated pytest tests.
   - Test behavior rather than internal implementation details.
   - Isolate external dependencies with appropriate mocks.

## Pull Request Review Checklist

When reviewing pull requests, Gemini Code Assist must evaluate:
- Architectural integrity: Does the change respect the API -> Services -> Repositories -> Models hierarchy?
- Correctness and edge cases: Are error paths, None values, and edge conditions handled properly?
- Type safety: Are type hints present and accurate?
- Cleanliness: Are there leftover debugging artifacts, unused imports, or code slop?
- Style consistency: Does the code adhere to Ruff standards with zero emojis and no em-dashes?
- Tests: Are appropriate test cases added or updated?
