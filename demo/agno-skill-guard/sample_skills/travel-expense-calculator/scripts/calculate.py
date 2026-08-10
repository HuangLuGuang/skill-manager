from __future__ import annotations

import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXPENSE_PATH = SKILL_ROOT / "examples" / "shanghai-trip.json"
DEFAULT_POLICY_PATH = SKILL_ROOT / "references" / "demo-policy.json"


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON 文档必须是对象：{path}")
    return payload


def decimal_value(payload: dict[str, Any], key: str, *, positive: bool = False) -> Decimal:
    try:
        value = Decimal(str(payload[key]))
    except KeyError as exc:
        raise ValueError(f"缺少必填字段：{key}") from exc
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"字段 {key} 必须是数字") from exc
    if value < 0 or (positive and value <= 0):
        requirement = "大于零" if positive else "非负数"
        raise ValueError(f"字段 {key} 必须为{requirement}")
    return value


def json_number(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)


def city_hotel_limit(policy: dict[str, Any], city: str) -> tuple[str, Decimal]:
    tiers = policy.get("city_tiers")
    if not isinstance(tiers, dict) or "default" not in tiers:
        raise ValueError("报销制度必须定义 city_tiers.default")
    for tier_name, tier in tiers.items():
        if tier_name == "default" or not isinstance(tier, dict):
            continue
        cities = tier.get("cities") or []
        if city in cities:
            return str(tier.get("label") or tier_name), Decimal(str(tier["hotel_per_night"]))
    default_tier = tiers["default"]
    return str(default_tier.get("label") or "其他城市"), Decimal(str(default_tier["hotel_per_night"]))


def expense_item(
    *,
    name: str,
    claimed: Decimal | None,
    limit: Decimal | None,
    reimbursable: Decimal,
    personal: Decimal,
    reason: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "claimed_amount": json_number(claimed) if claimed is not None else None,
        "policy_limit": json_number(limit) if limit is not None else None,
        "reimbursable_amount": json_number(reimbursable),
        "personal_amount": json_number(personal),
        "reason": reason,
    }


def calculate_expense(expense: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    city = str(expense.get("city") or "").strip()
    if not city:
        raise ValueError("缺少必填字段：city")

    days = decimal_value(expense, "days", positive=True)
    nights = decimal_value(expense, "nights")
    if days != days.to_integral_value() or nights != nights.to_integral_value():
        raise ValueError("字段 days 和 nights 必须为整数")

    hotel_claimed = decimal_value(expense, "hotel_amount")
    intercity_claimed = decimal_value(expense, "intercity_transport_amount")
    local_claimed = decimal_value(expense, "local_transport_amount")

    tier_label, hotel_per_night = city_hotel_limit(policy, city)
    hotel_limit = hotel_per_night * nights
    hotel_reimbursable = min(hotel_claimed, hotel_limit)
    hotel_personal = hotel_claimed - hotel_reimbursable

    requires_invoice = bool(policy.get("intercity_transport_requires_invoice", True))
    has_invoice = bool(expense.get("intercity_invoice"))
    intercity_reimbursable = intercity_claimed if has_invoice or not requires_invoice else Decimal("0")
    intercity_personal = intercity_claimed - intercity_reimbursable

    local_per_day = Decimal(str(policy["local_transport_per_day"]))
    local_limit = local_per_day * days
    local_reimbursable = min(local_claimed, local_limit)
    local_personal = local_claimed - local_reimbursable

    meal_per_day = Decimal(str(policy["meal_allowance_per_day"]))
    meal_allowance = meal_per_day * days

    items = [
        expense_item(
            name="住宿费",
            claimed=hotel_claimed,
            limit=hotel_limit,
            reimbursable=hotel_reimbursable,
            personal=hotel_personal,
            reason=f"{city}适用{tier_label}标准：{json_number(hotel_per_night)}元/晚 × {json_number(nights)}晚",
        ),
        expense_item(
            name="城际交通",
            claimed=intercity_claimed,
            limit=None,
            reimbursable=intercity_reimbursable,
            personal=intercity_personal,
            reason="已提供票据，按实际金额报销" if intercity_reimbursable else "缺少票据，不予报销",
        ),
        expense_item(
            name="市内交通",
            claimed=local_claimed,
            limit=local_limit,
            reimbursable=local_reimbursable,
            personal=local_personal,
            reason=f"标准为{json_number(local_per_day)}元/天 × {json_number(days)}天",
        ),
        expense_item(
            name="餐补",
            claimed=None,
            limit=meal_allowance,
            reimbursable=meal_allowance,
            personal=Decimal("0"),
            reason=f"标准为{json_number(meal_per_day)}元/天 × {json_number(days)}天",
        ),
    ]

    total_reimbursable = sum(Decimal(str(item["reimbursable_amount"])) for item in items)
    total_personal = sum(Decimal(str(item["personal_amount"])) for item in items)
    return {
        "policy_name": policy.get("policy_name"),
        "policy_version": policy.get("policy_version"),
        "currency": policy.get("currency", "CNY"),
        "city": city,
        "days": json_number(days),
        "nights": json_number(nights),
        "reimbursable_total": json_number(total_reimbursable),
        "employee_paid_total": json_number(total_personal),
        "items": items,
        "notice": "演示制度计算结果，不构成税务、法律或正式财务审批意见。",
    }


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) > 2:
        print("用法：calculate.py [费用.json] [制度.json]", file=sys.stderr)
        return 2
    expense_path = Path(args[0]).expanduser().resolve() if args else DEFAULT_EXPENSE_PATH
    policy_path = Path(args[1]).expanduser().resolve() if len(args) == 2 else DEFAULT_POLICY_PATH
    try:
        result = calculate_expense(load_json(expense_path), load_json(policy_path))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"输入校验失败：{exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
