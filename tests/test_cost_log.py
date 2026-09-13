"""Unit tests for pipeline cost logging repository."""

from src.models.schemas import CostLogCreate
from src.repositories.cost_repository import CostRepository


def test_log_cost_and_calculate_totals(cost_repo: CostRepository):
    # Log costs across different stages
    cost_repo.log_cost(
        CostLogCreate(
            stage="clustering",
            provider="openai",
            model="text-embedding-3-small",
            units=500.0,
            unit_type="tokens",
            cost_usd=0.0001,
            job_id=1,
        )
    )
    cost_repo.log_cost(
        CostLogCreate(
            stage="script_dialogue",
            provider="deepseek",
            model="deepseek-chat",
            units=1200.0,
            unit_type="tokens",
            cost_usd=0.00025,
            job_id=1,
        )
    )
    cost_repo.log_cost(
        CostLogCreate(
            stage="tts_voice",
            provider="gemini",
            model="gemini-2.0-flash",
            units=800.0,
            unit_type="characters",
            cost_usd=0.032,
            job_id=1,
        )
    )

    total_spend = cost_repo.get_total_spend()
    assert round(total_spend, 4) == round(0.0001 + 0.00025 + 0.032, 4)

    job_costs = cost_repo.get_job_costs(job_id=1)
    assert len(job_costs) == 3

    stage_breakdown = cost_repo.get_spend_by_stage()
    stages = [s["stage"] for s in stage_breakdown]
    assert "tts_voice" in stages
    assert "script_dialogue" in stages
    assert "clustering" in stages
