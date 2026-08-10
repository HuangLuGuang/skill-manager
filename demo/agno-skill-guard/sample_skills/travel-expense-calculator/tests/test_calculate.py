from __future__ import annotations

import importlib.util
import json
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = SKILL_ROOT / "scripts" / "calculate.py"
SPEC = importlib.util.spec_from_file_location("travel_expense_calculator", SCRIPT_PATH)
assert SPEC and SPEC.loader
calculator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(calculator)


def test_shanghai_example_matches_demo_policy() -> None:
    expense = calculator.load_json(SKILL_ROOT / "examples" / "shanghai-trip.json")
    policy = calculator.load_json(SKILL_ROOT / "references" / "demo-policy.json")

    result = calculator.calculate_expense(expense, policy)

    assert result["reimbursable_total"] == 2293
    assert result["employee_paid_total"] == 100
    assert [item["reimbursable_amount"] for item in result["items"]] == [1200, 553, 240, 300]


def test_missing_intercity_invoice_is_not_reimbursed() -> None:
    expense = calculator.load_json(SKILL_ROOT / "examples" / "shanghai-trip.json")
    expense["intercity_invoice"] = False
    policy = calculator.load_json(SKILL_ROOT / "references" / "demo-policy.json")

    result = calculator.calculate_expense(expense, policy)

    assert result["reimbursable_total"] == 1740
    assert result["employee_paid_total"] == 653


def test_default_entrypoint_outputs_structured_result(capsys) -> None:
    assert calculator.main([]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["policy_version"] == "demo-2026.1"
    assert payload["reimbursable_total"] == 2293
