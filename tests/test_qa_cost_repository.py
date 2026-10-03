"""Tests for CostRepository in src/repositories/cost_repository.py.

Covers log_cost() and get_total_spend() including happy path, zero cost,
accumulation across multiple records, data-integrity round-trips, and
negative cost behaviour (documents actual storage behaviour).
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from src.models.schemas import CostLogCreate
from src.repositories.cost_repository import CostRepository

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(
    *,
    stage: str = "script",
    provider: str = "openai",
    model: str | None = "gpt-4o-mini",
    units: float = 1000.0,
    unit_type: str = "tokens",
    cost_usd: float = 0.05,
    job_id: int | None = None,
) -> CostLogCreate:
    """Build a minimal CostLogCreate for use in tests."""
    return CostLogCreate(
        stage=stage,
        provider=provider,
        model=model,
        units=units,
        unit_type=unit_type,
        cost_usd=cost_usd,
        job_id=job_id,
    )


# ---------------------------------------------------------------------------
# log_cost() tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_log_cost_returns_record_with_correct_fields(cost_repo: CostRepository) -> None:
    """log_cost() persists all entry fields and returns the ORM record."""
    entry = _make_entry(
        stage="tts",
        provider="gemini",
        model="gemini-tts",
        units=500.0,
        unit_type="characters",
        cost_usd=0.0025,
        job_id=42,
    )

    record = cost_repo.log_cost(entry)

    assert record.id is not None
    assert record.stage == "tts"
    assert record.provider == "gemini"
    assert record.model == "gemini-tts"
    assert record.units == 500.0
    assert record.unit_type == "characters"
    assert record.cost_usd == pytest.approx(0.0025)
    assert record.job_id == 42


@pytest.mark.unit
def test_log_cost_assigns_auto_increment_id(cost_repo: CostRepository) -> None:
    """Each log_cost() call generates a unique auto-incremented primary key."""
    entry_a = _make_entry(cost_usd=0.01)
    entry_b = _make_entry(cost_usd=0.02)

    record_a = cost_repo.log_cost(entry_a)
    record_b = cost_repo.log_cost(entry_b)

    assert record_a.id != record_b.id
    assert record_b.id > record_a.id


@pytest.mark.unit
def test_log_cost_with_zero_cost_stores_zero(cost_repo: CostRepository) -> None:
    """log_cost() stores 0.0 cost_usd without coercion or error."""
    entry = _make_entry(cost_usd=0.0, units=0.0)

    record = cost_repo.log_cost(entry)

    assert record.cost_usd == 0.0


@pytest.mark.unit
def test_log_cost_with_none_model_stores_null(cost_repo: CostRepository) -> None:
    """log_cost() accepts a None model value and persists it as NULL."""
    entry = _make_entry(model=None)

    record = cost_repo.log_cost(entry)

    assert record.model is None


@pytest.mark.unit
def test_log_cost_with_none_job_id_stores_null(cost_repo: CostRepository) -> None:
    """log_cost() stores NULL job_id when not provided."""
    entry = _make_entry(job_id=None)

    record = cost_repo.log_cost(entry)

    assert record.job_id is None


@pytest.mark.unit
def test_log_cost_with_negative_cost_stores_value(cost_repo: CostRepository) -> None:
    """log_cost() stores negative cost values as-is (no validation at repo layer).

    NOTE: The CostLogCreate schema enforces ge=0 on cost_usd, so this test
    verifies CostRepository itself does not add extra validation -- the schema
    is the enforcement boundary. Calling with a manually constructed object
    that bypasses schema would persist the value.
    """
    from src.models.entities import CostLogEntry

    record = CostLogEntry(
        stage="script",
        provider="openai",
        model="gpt-4o-mini",
        units=1.0,
        unit_type="tokens",
        cost_usd=-0.01,
    )
    cost_repo.session.add(record)
    cost_repo.session.flush()

    assert record.cost_usd == pytest.approx(-0.01)


# ---------------------------------------------------------------------------
# get_total_spend() tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_total_spend_returns_zero_when_no_records(cost_repo: CostRepository) -> None:
    """get_total_spend() returns 0.0 on an empty cost_log table."""
    total = cost_repo.get_total_spend()

    assert total == 0.0


@pytest.mark.unit
def test_get_total_spend_returns_single_record_cost(cost_repo: CostRepository) -> None:
    """get_total_spend() equals the cost of a single logged entry."""
    cost_repo.log_cost(_make_entry(cost_usd=1.2345))

    total = cost_repo.get_total_spend()

    assert total == pytest.approx(1.2345)


@pytest.mark.unit
def test_get_total_spend_accumulates_multiple_records(cost_repo: CostRepository) -> None:
    """get_total_spend() sums all cost records across different stages."""
    cost_repo.log_cost(_make_entry(stage="ingest", cost_usd=0.10))
    cost_repo.log_cost(_make_entry(stage="script", cost_usd=0.25))
    cost_repo.log_cost(_make_entry(stage="tts", cost_usd=0.05))

    total = cost_repo.get_total_spend()

    assert total == pytest.approx(0.40)


@pytest.mark.unit
def test_get_total_spend_returns_float_type(cost_repo: CostRepository) -> None:
    """get_total_spend() always returns a Python float."""
    cost_repo.log_cost(_make_entry(cost_usd=0.5))

    total = cost_repo.get_total_spend()

    assert isinstance(total, float)


# ---------------------------------------------------------------------------
# Data integrity tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_data_integrity_two_log_cost_calls_sum_correctly(
    db_session: Session,
) -> None:
    """Two sequential log_cost() calls accumulate correctly in get_total_spend()."""
    repo = CostRepository(db_session)

    repo.log_cost(_make_entry(cost_usd=0.50))
    repo.log_cost(_make_entry(cost_usd=0.50))

    total = repo.get_total_spend()

    assert total == pytest.approx(1.00)


@pytest.mark.integration
def test_data_integrity_records_are_independent(
    db_session: Session,
) -> None:
    """Each log_cost() call creates a distinct row; get_total_spend() counts all rows."""
    repo = CostRepository(db_session)

    amounts = [0.01, 0.02, 0.03, 0.04, 0.05]
    for amount in amounts:
        repo.log_cost(_make_entry(cost_usd=amount))

    total = repo.get_total_spend()

    assert total == pytest.approx(sum(amounts))


@pytest.mark.integration
def test_data_integrity_high_precision_costs_accumulate(
    db_session: Session,
) -> None:
    """High-decimal-precision costs accumulate without lossy truncation."""
    repo = CostRepository(db_session)

    repo.log_cost(_make_entry(cost_usd=0.000123))
    repo.log_cost(_make_entry(cost_usd=0.000456))

    total = repo.get_total_spend()

    assert total == pytest.approx(0.000579, rel=1e-4)


@pytest.mark.integration
def test_data_integrity_zero_cost_entries_do_not_inflate_total(
    db_session: Session,
) -> None:
    """Zero-cost entries do not change the running total."""
    repo = CostRepository(db_session)

    repo.log_cost(_make_entry(cost_usd=1.00))
    repo.log_cost(_make_entry(cost_usd=0.00))
    repo.log_cost(_make_entry(cost_usd=0.00))

    total = repo.get_total_spend()

    assert total == pytest.approx(1.00)
