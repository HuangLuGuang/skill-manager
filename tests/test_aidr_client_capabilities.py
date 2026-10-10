"""Current protocol support is reported, not inferred from release labels."""
import pytest
from backend.runtime_governance import compatibility_view


@pytest.mark.parametrize('protocol,tasks,expected', [(0, False, 'legacy'), (1, True, 'legacy'), (2, True, 'legacy'), (3, False, 'partial'), (3, True, 'reported_current')])
def test_protocol_and_task_capabilities_have_independent_evidence(protocol, tasks, expected):
    result = compatibility_view({'protocol': protocol}, tasks, False)
    assert result['state'] == expected
    assert result['current']['task_control'] is tasks
    assert result['current']['channel_policy'] is (protocol == 3)
    assert result['current']['runtime_policy'] is (protocol in (2, 3))


def test_unknown_and_stale_reports_cannot_claim_current_support():
    assert all(value is None for value in compatibility_view(None, False, True)['current'].values())
    stale = compatibility_view({'protocol': 3}, True, True)
    assert stale['state'] == 'unknown'
    assert stale['reported_state'] == 'reported_current'
    assert all(value is None for value in stale['current'].values())
