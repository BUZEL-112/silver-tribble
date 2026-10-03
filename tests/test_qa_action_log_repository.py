"""QA tests for ActionLogRepository.

Covers:
- record_action: field persistence and optional job_id
- record_action: details dict stored as JSON
- track_operation: success path records 'success' status entry
- track_operation: failure path records 'failed' status entry and re-raises
- list_recent_actions (get_recent_logs): ordering, limit, and stage filter
- idempotency: two independent record_action calls both stored
- data integrity: total record count matches number of calls
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from src.models.entities import ActionLog
from src.repositories.action_log_repository import ActionLogRepository

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_record_action_creates_log_with_correct_fields(
    db_session: Session,
    action_repo: ActionLogRepository,
) -> None:
    """record_action persists stage, action, actor, status, and message exactly."""
    log = action_repo.record_action(
        stage="render",
        action="generate_audio",
        actor="worker",
        status="started",
        message="Beginning TTS synthesis.",
    )

    assert log.id is not None
    assert log.stage == "render"
    assert log.action == "generate_audio"
    assert log.actor == "worker"
    assert log.status == "started"
    assert log.message == "Beginning TTS synthesis."


@pytest.mark.unit
def test_record_action_with_job_id_none_stores_null(
    db_session: Session,
    action_repo: ActionLogRepository,
) -> None:
    """record_action accepts job_id=None and stores a NULL value without error."""
    log = action_repo.record_action(
        stage="ingest",
        action="fetch_feed",
        job_id=None,
        status="success",
    )

    assert log.job_id is None


@pytest.mark.unit
def test_record_action_with_details_dict_persists_payload(
    db_session: Session,
    action_repo: ActionLogRepository,
) -> None:
    """record_action stores the details dict and returns it faithfully on reload."""
    payload: dict[str, object] = {"articles_fetched": 12, "source": "bbc"}

    log = action_repo.record_action(
        stage="ingest",
        action="fetch_feed",
        details=payload,
        status="success",
    )

    reloaded = db_session.get(ActionLog, log.id)
    assert reloaded is not None
    assert reloaded.details == payload


@pytest.mark.unit
def test_track_operation_success_records_success_entry(
    db_session: Session,
    action_repo: ActionLogRepository,
) -> None:
    """track_operation writes a 'success' log entry when the body exits cleanly."""
    with action_repo.track_operation(stage="render", action="composite_video"):
        pass

    logs = action_repo.get_recent_logs(stage="render")
    statuses = [lg.status for lg in logs]
    assert "success" in statuses


@pytest.mark.unit
def test_track_operation_on_exception_records_failed_and_reraises(
    db_session: Session,
    action_repo: ActionLogRepository,
) -> None:
    """track_operation writes a 'failed' log entry and re-raises the original exception."""
    with pytest.raises(RuntimeError, match="boom"):
        with action_repo.track_operation(stage="render", action="composite_video"):
            raise RuntimeError("boom")

    logs = action_repo.get_recent_logs(stage="render")
    statuses = [lg.status for lg in logs]
    assert "failed" in statuses


@pytest.mark.unit
def test_list_recent_actions_returns_most_recent_first(
    db_session: Session,
    action_repo: ActionLogRepository,
) -> None:
    """get_recent_logs returns entries ordered by created_at descending."""
    action_repo.record_action(stage="ingest", action="alpha", status="success")
    action_repo.record_action(stage="ingest", action="beta", status="success")
    action_repo.record_action(stage="ingest", action="gamma", status="success")

    logs = action_repo.get_recent_logs()

    actions = [lg.action for lg in logs]
    assert actions.index("gamma") < actions.index("alpha")


@pytest.mark.unit
def test_list_recent_actions_with_limit_respects_limit(
    db_session: Session,
    action_repo: ActionLogRepository,
) -> None:
    """get_recent_logs with limit=2 returns exactly 2 entries even when more exist."""
    for i in range(5):
        action_repo.record_action(stage="script", action=f"step_{i}", status="success")

    logs = action_repo.get_recent_logs(limit=2)

    assert len(logs) == 2


@pytest.mark.unit
def test_list_recent_actions_with_stage_filter_returns_matching_stage_only(
    db_session: Session,
    action_repo: ActionLogRepository,
) -> None:
    """get_recent_logs with stage= returns only entries for that specific stage."""
    action_repo.record_action(stage="render", action="audio", status="success")
    action_repo.record_action(stage="ingest", action="fetch", status="success")
    action_repo.record_action(stage="render", action="captions", status="success")

    logs = action_repo.get_recent_logs(stage="render")

    assert all(lg.stage == "render" for lg in logs)
    assert len(logs) == 2


@pytest.mark.unit
def test_two_record_action_calls_are_stored_independently(
    db_session: Session,
    action_repo: ActionLogRepository,
) -> None:
    """Two distinct record_action calls produce two separate rows with different ids."""
    first = action_repo.record_action(stage="ingest", action="fetch_feed", status="success")
    second = action_repo.record_action(stage="ingest", action="fetch_feed", status="success")

    assert first.id != second.id


@pytest.mark.unit
def test_action_count_matches_number_of_record_action_calls(
    db_session: Session,
    action_repo: ActionLogRepository,
) -> None:
    """Total stored ActionLog rows equals the exact number of record_action invocations."""
    call_count = 7

    for i in range(call_count):
        action_repo.record_action(
            stage="script",
            action=f"beat_{i}",
            status="success",
        )

    logs = action_repo.get_recent_logs(limit=call_count + 10)

    assert len(logs) == call_count
