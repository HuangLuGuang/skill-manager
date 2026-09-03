from fastapi import APIRouter, Depends

from ..feature_flags import (
    FEATURE_AGENT_SECURITY_SCANNING,
    FEATURE_RUNTIME_TRACE,
    load_upstream_baseline,
    require_agent_security_scanning,
    require_runtime_trace,
)

router = APIRouter(prefix="/v1", tags=["agent-security-baseline"])


@router.get(
    "/agent-security/baseline",
    dependencies=[Depends(require_agent_security_scanning)],
)
def get_agent_security_baseline():
    baseline = load_upstream_baseline()
    return {
        "feature": FEATURE_AGENT_SECURITY_SCANNING,
        "enabled": True,
        "integration": baseline["integrations"]["ai_infra_guard"],
        "runtime_source_fetch": baseline["policy"]["runtime_source_fetch"],
    }


@router.get(
    "/runtime-traces/baseline",
    dependencies=[Depends(require_runtime_trace)],
)
def get_runtime_trace_baseline():
    baseline = load_upstream_baseline()
    return {
        "feature": FEATURE_RUNTIME_TRACE,
        "enabled": True,
        "integration": baseline["integrations"]["deepseek_harness"],
        "runtime_source_fetch": baseline["policy"]["runtime_source_fetch"],
    }
