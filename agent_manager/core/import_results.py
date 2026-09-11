"""Present import results from their associated scan runs, not mutable versions."""


def resolve_import_result(item, runs, *, created_at=None, before=None):
    result = dict(item)
    run_id = item.get('scan_run_id')
    run = next((run for run in runs if run.scan_run_id == run_id), None) if run_id else None
    if not run_id and not item.get('scan_reused') and created_at is not None:
        candidates = [run for run in runs if run.started_at.timestamp() >= created_at
                      and (before is None or run.started_at.timestamp() < before)]
        if len(candidates) == 1:
            run = candidates[0]
    if item.get('scan_reused') and not run_id:
        result['scan_state'] = 'REUSED'
        return result
    state = run.status if run else 'UNKNOWN'
    result.update(scan_run_id=run.scan_run_id if run else run_id, scan_state=state,
                  status='PENDING' if state == 'PENDING' else state,
                  risk_level=None, findings_count=0, sandbox_triggered=False,
                  sandbox_required_by_policy=False, sandbox_runtime=None)
    if run and state in ('COMPLETED', 'REUSED'):
        result.update({key: run.result[key] for key in (
            'status', 'risk_level', 'findings_count', 'sandbox_triggered',
            'sandbox_required_by_policy', 'sandbox_runtime') if key in run.result})
        result['scan_reused'] = state == 'REUSED' or bool(run.result.get('scan_reused'))
    return result
