from __future__ import annotations

from src.app.db.models import AuditLog


def test_compute_cost_for_zero_tokens():
    assert AuditLog.compute_cost(0, 0) == 0


def test_compute_cost_combines_prompt_and_completion_rates():
    assert AuditLog.compute_cost(1000, 1000) == round(0.00015 + 0.0006, 8)
