from datetime import datetime, timezone
from types import SimpleNamespace
from agent_manager.core.import_results import resolve_import_result


def run(id, status, time=100, **result):
    return SimpleNamespace(scan_run_id=id, status=status, started_at=datetime.fromtimestamp(time, timezone.utc), result=result)


def test_pending_hides_old_report_and_completion_uses_bound_run():
    item = dict(scan_run_id='current', status='APPROVED', risk_level='benign', findings_count=1, sandbox_runtime='remote')
    pending = resolve_import_result(item, [run('current', 'PENDING')])
    assert pending['status'] == 'PENDING'
    assert pending['risk_level'] is None
    assert pending['sandbox_runtime'] is None
    done = resolve_import_result(item, [run('later', 'COMPLETED', status_unused='x'), run('current', 'COMPLETED', **{'risk_level':'malicious', 'findings_count':3})])
    assert done['risk_level'] == 'malicious'
    assert done['findings_count'] == 3


def test_history_matches_only_unique_run_in_submission_window():
    old = {'status':'APPROVED', 'risk_level':'benign'}
    runs = [run('prior', 'COMPLETED', 99), run('this', 'COMPLETED', 101), run('next', 'PENDING', 200)]
    assert resolve_import_result(old, runs, created_at=100, before=200)['scan_run_id'] == 'this'
    assert resolve_import_result(old, runs, created_at=100)['scan_state'] == 'UNKNOWN'
    assert resolve_import_result(old, [], created_at=100)['risk_level'] is None


def test_cached_submission_retains_its_snapshot():
    item = {'scan_reused':True,'status':'APPROVED','risk_level':'benign'}
    assert resolve_import_result(item, [run('later', 'PENDING')])['scan_state'] == 'REUSED'
