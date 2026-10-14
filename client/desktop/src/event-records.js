// Shared semantic formatting for the desktop client and management console.
// The API owns classification; callers supply their locale resource lookup.
globalThis.clientEventRecords = {
  describe(event, label) {
    const p = event.presentation || {}
    const condition = label('condition_' + p.condition, {}, 'condition_unknown')
    const title = label('title_' + p.title, { condition }, 'title_unknown_event')
    const reason = label('reason_' + p.reason, {}, 'reason_unknown')
    const category = label('category_' + p.category, {}, 'category_other')
    let state = label('state_' + p.state, {}, 'state_unknown')
    if (p.state === 'recorded' && ['record', 'record_only'].includes(p.action)) state = label('action_' + p.action)
    if (['succeeded', 'failed'].includes(p.state)) state = label((p.state === 'succeeded' ? 'success_' : 'failure_') + p.action, {}, 'state_' + p.state)
    const action = label('action_' + p.action, {}, 'action_unrecorded')
    const tone = p.state === 'alert_active' ? 'warning' : p.state === 'failed' ? 'danger' : p.state === 'succeeded' ? 'success' : ['pending', 'running', 'submitted'].includes(p.state) ? 'info' : 'neutral'
    const stage = label('stage_' + (p.stage === 'host_confirmed' ? p.behavior === 'invocation' ? 'loaded' : 'read' : p.stage), {}, 'stage_unknown')
    const timeline = [...(p.timeline || [])].sort((a, b) => Date.parse(a.at || 0) - Date.parse(b.at || 0))
    return { ...p, title, reason, category, state, action, tone, stage, timeline,
      timeLabel: label('time_' + p.time_kind, {}, 'time_recorded'),
      retained: p.state === 'recorded' && p.action === 'record_only',
      count: p.count_kind === 'discoveries' && event.observation_count > 1 ? label('count', { count: event.observation_count }) : '',
    }
  },
}
