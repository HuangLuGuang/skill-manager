"""Current Hook execution context, separate from draft rule matching."""
import time

from .client_governance import policy_view


def view(db, client_id, control):
    policy = policy_view(db, client_id or None)
    target = policy['runtime_governance']
    configured = policy['runtime_governance_configured']
    enabled = bool(target['enabled'] and (target.get('channels') or {}).get('hooks', True)) if configured else None
    result = {'scope': 'client' if client_id else 'global',
              'source': 'client' if policy['runtime_governance_source'] == 'client' else 'global',
              'target_mode': (target.get('modes') or {}).get('hooks'),
              'enabled': enabled, 'mode': 'unknown', 'valid_until': 0,
              'state': 'global' if not client_id else 'unknown'}
    if not client_id:
        return result
    now = time.time()
    reports = [r for r in (control.get('runtime') or {}).get('items', [])
               if -5 <= now - int(r['received_at']) <= 90]
    modes = {r['control_mode'] for r in reports}
    result['valid_until'] = min((int(r['received_at']) + 90 for r in reports), default=0)
    result['mode'] = ('audit' if modes == {'audit'} else 'intercept' if modes == {'plugin_pre_tool'}
                      else 'mixed' if len(modes) > 1 else 'unknown')
    if enabled is False:
        result['state'] = 'disabled'
    elif result['mode'] in ('audit', 'mixed', 'unknown'):
        result['state'] = result['mode']
    else:
        result['state'] = 'ready' if all(r.get('control_code') == 'aidr_hook_policy_ready'
            and r.get('matches_published_revision') for r in reports) else 'pending'
    return result
