"""Lossless unified view of detection and Hook policies, including legacy records."""
from . import aidr_risk_catalog as catalog
import hashlib
import json
from copy import deepcopy
from sqlalchemy import Column, String, Text
from .sqlite_db import Base
from .aidr_security_config import Document
from .api_errors import ApiError


class SecurityEditorConfig(Base):
    __tablename__ = 'aidr_security_editor_configs'
    scope = Column(String(140), primary_key=True)
    payload = Column(Text, nullable=False)
    control_digest = Column(String(64), nullable=False)


def invalid():
    raise ApiError(422, 'aidr.security.invalid_config', '请检查规则条件、路径集合及动作的支持范围', 'Check rule conditions, path sets and supported actions')


def digest(policy):
    policy = policy or {'default_action': 'allow', 'rules': []}
    policy = {key: value for key, value in policy.items() if key != 'approval_wait_seconds'}
    return hashlib.sha256(json.dumps({**policy, 'rules': sorted(policy['rules'], key=lambda r: r['id'])}, sort_keys=True).encode()).hexdigest()


def editor_policy(control, client):
    value = (control.get('global_policy') if client and control['inherit'] else control.get('policy')) or {}
    return {key: value.get(key, default) for key, default in [('default_action', 'allow'), ('approval_wait_seconds', 180), ('rules', [])]}


def document_view(db, detection, control, client_id):
    legacy = project(detection, control, bool(client_id))
    risk_source = 'global' if not client_id or detection and detection.get('rules_mode') == 'inherit' else 'client'
    control_source = 'global' if not client_id or control.get('inherit') else 'client'
    stored = db.get(SecurityEditorConfig, 'global' if control_source == 'global' else client_id)
    policy = editor_policy(control, bool(client_id))
    metadata = json.loads(stored.payload) if stored and stored.control_digest == digest(policy) else None
    paths, rows = {}, {}
    security = detection.get('security') if detection else None
    if security is not None:
        for path in security['path_sets']:
            paths[path['id']] = {**path, 'source': risk_source}
        for rule in security['rules']:
            if rule['severity'] is not None or rule['action'] == 'none':
                rows[rule['id']] = {**rule, 'action': 'none', 'source': risk_source}
    for row in legacy['rules']:
        if row['domain'] == 'detection' and security is not None:
            continue
        if row['domain'] == 'control' and metadata is not None:
            continue
        condition = deepcopy(row.get('condition'))
        if condition:
            condition['path_prefix'] = ''
        rule = dict(id=row['id'], name=row.get('name', ''), kind='builtin' if row['kind'] != 'custom' else 'command' if condition else 'tool',
                    code=row['code'], enabled=True if row['kind'] == 'event' else row['enabled'], severity=row['severity'], action=row['action'],
                    agent=row.get('agent', '*'), tool=row.get('tool', '*'), platforms=row.get('platforms', ['linux', 'darwin', 'windows']),
                    condition=condition, path_set=row['path_set'], control_id=row['code'] if row['domain'] == 'control' else '', source=row['source'])
        if row['code'] == 'download_to_shell':
            rule['severity'] = 'medium'
        rows[rule['id']] = rule
    used = {r['path_set'] for r in rows.values()}
    for path in legacy['path_sets']:
        if path['id'] in used and path['id'] not in paths:
            paths[path['id']] = {key: path[key] for key in ('id', 'paths', 'builtin_ids', 'source')}
            paths[path['id']]['name'] = path['kind'] if path['kind'] != 'prefix' else next(r['name'] for r in rows.values() if r['path_set'] == path['id'])
    if metadata is not None:
        control_paths = {p['id']: p for p in metadata['path_sets']}
        for original in metadata['rules']:
            rule = deepcopy(original)
            if rule['action'] == 'none' and rule['severity'] is not None:
                continue
            path = control_paths.get(rule['path_set'])
            if path and path['id'] in paths and any(paths[path['id']][key] != path[key] for key in ('paths', 'builtin_ids')):
                rule['path_set'] = f"{control_source}:{path['id']}"
                paths[rule['path_set']] = {**path, 'id': rule['path_set'], 'source': control_source}
            previous = rows.get(rule['id'])
            if previous and any(previous[key] != rule[key] for key in ('kind', 'code', 'condition', 'agent', 'tool', 'platforms', 'path_set', 'enabled')):
                # A later global change can diverge from an existing local condition.
                rule['control_id'] = control_id(rule)
                rule['id'] += ':action'
                previous = None
            if previous:
                previous['action'] = rule['action']
                previous['control_id'] = rule['control_id']
                if previous['source'] != control_source:
                    previous['source'] = 'mixed'
            else:
                rows[rule['id']] = {**rule, 'severity': None, 'source': control_source}
        for path in metadata['path_sets']:
            if path['id'] not in paths:
                paths[path['id']] = {**path, 'source': control_source}
    return {'rules': list(rows.values()), 'path_sets': list(paths.values())}


def clean_document(value):
    if (not isinstance(value, dict) or set(value) != {'rules', 'path_sets'}
            or any(not isinstance(value[key], list) or any(not isinstance(item, dict) for item in value[key]) for key in value)):
        invalid()
    return Document.model_validate({key: [{k: v for k, v in item.items() if k != 'source'} for item in value[key]] for key in ('rules', 'path_sets')}).model_dump()


def control_id(rule):
    return rule['control_id'] or 'security_' + hashlib.sha256(rule['id'].encode()).hexdigest()[:24]


def rule_agents(rule):
    return rule['agent'] if isinstance(rule['agent'], list) else [rule['agent']]


def control_ids(rule):
    agents = rule_agents(rule)
    original = control_id(rule)
    return [original] if len(agents) == 1 else [
        'security_' + hashlib.sha256((original + ':' + agent).encode()).hexdigest()[:24] for agent in agents]


def control_rules(document):
    from .aidr_hook_control import ToolRule
    rules = []
    paths = {p['id']: p for p in document['path_sets']}
    for row in document['rules']:
        if row['action'] == 'none':
            continue
        # Existing Hook clients support literal POSIX commands and native tool names.
        if row['kind'] == 'builtin' or set(row['platforms']) != {'linux', 'darwin', 'windows'}:
            invalid()
        rule = {'id': control_id(row),
                'agent': rule_agents(row)[0], 'tool': row['tool'], 'decision': row['action']}
        if row['kind'] == 'command':
            rule['command'] = deepcopy(row['condition'])
            group = paths.get(row['path_set'])
            if group:
                # One prefix preserves allow's all-segments/all-targets semantics.
                if group['builtin_ids'] or len(group['paths']) != 1:
                    invalid()
                rule['command']['path_prefix'] = group['paths'][0]
        for agent, identity in zip(rule_agents(row), control_ids(row)):
            validated = ToolRule.model_validate({**rule, 'agent': agent, 'id': identity}).model_dump(exclude_none=True)
            if row['enabled']:
                rules.append(validated)
    return rules


def save_metadata(db, client_id, document, policy):
    row = db.get(SecurityEditorConfig, client_id or 'global')
    if row is None:
        row = SecurityEditorConfig(scope=client_id or 'global')
        db.add(row)
    row.payload = json.dumps(document, ensure_ascii=False)
    row.control_digest = digest(policy)


def rule_configuration(rule, document, platform):
    from .aidr_risk import DetectionConfig
    config = DetectionConfig().model_dump(exclude={'expected_revision'})
    config.update(command_rules=[], platform=platform)
    group = next((p for p in document['path_sets'] if p['id'] == rule['path_set']), None)
    config['security_roots'] = [] if group is None else group['paths'] + [spec for item in catalog.CATALOG
        if item['id'] in group['builtin_ids'] for spec in item['paths'] if spec['os'] == platform]
    if rule['kind'] == 'builtin':
        config['command_rules'] = [rule['code']] if rule['code'] in catalog.COMMANDS else []
    if rule['kind'] == 'command':
        prefixes = group['paths'] if group else ['']
        if group and group['builtin_ids']:
            # The literal custom matcher has no template/exact-file condition.
            invalid()
        config['custom_commands'] = [dict(id=rule['code'] if rule['code'].startswith('custom_') and len(prefixes) == 1 else 'custom_' + hashlib.sha256((rule['id'] + str(i)).encode()).hexdigest()[:24], name=rule['name'] or rule['id'],
            enabled=True, platforms=rule['platforms'], severity=rule['severity'] or 'medium',
            condition={**rule['condition'], 'path_prefix': path}) for i, path in enumerate(prefixes)]
    return config


def eligible(rule, platform, event=None):
    return rule['enabled'] and rule['severity'] is not None and platform in rule['platforms'] and (event is None or
        any(agent in ('*', event.get('agent')) for agent in rule_agents(rule)) and rule['tool'] in ('*', event.get('tool')))


def annotate(matches, rule):
    code = rule['code'] if rule['kind'] == 'builtin' else 'custom_command'
    return [{**hit, 'severity': rule['severity'], 'security_rule_id': rule['id'],
             'name': rule['name'] or hit.get('name', ''), 'path_set': rule['path_set']}
            for hit in matches if hit['risk_code'] == code]


def assess_command(command, cwd, config, platform):
    from . import aidr_risk as risk
    if not config['enabled']:
        return {'status': 'disabled', 'matches': [], 'unresolved_rules': []}
    matches, unresolved = [], []
    for rule in config['security']['rules']:
        if not eligible(rule, platform) or rule['kind'] == 'tool':
            continue
        if ((rule.get('condition') or {}).get('keywords') or (rule.get('condition') or {}).get('networks')):
            result = text_command_assessment(rule, command)
        else:
            result = risk.command_assessment(command, cwd, rule_configuration(rule, config['security'], platform), platform)
        matches.extend(annotate(result['matches'], rule))
        if result['status'] == 'unresolved' or result['unresolved_rules']:
            unresolved.append(rule['id'])
    return {'status': 'matched' if matches else 'unresolved' if unresolved else 'unmatched', 'matches': matches, 'unresolved_rules': unresolved}


def text_command_assessment(rule, command):
    from .aidr_command_rules import command_match
    from .aidr_risk import match_record
    state = command_match(rule['condition'], command)
    return {'status': state, 'unresolved_rules': [rule['id']] if state == 'unresolved' else [],
            'matches': [match_record('custom_command', rule['severity'], rule_id=rule['id'], name=rule['name'], condition=rule['condition'])] if state == 'matched' else []}


def detect(event, config, *, windows=False, system=False):
    from . import aidr_risk as risk
    if not config['enabled']:
        return []
    platform = config.get('platform') or ('windows' if windows else 'linux')
    matches = []
    for rule in config['security']['rules']:
        if not eligible(rule, platform, event):
            continue
        if rule['kind'] == 'tool':
            if not system and event.get('kind') in ('tool.pre', 'tool_call'):
                matches.append({**risk.match_record('custom_tool', rule['severity'], rule_id=rule['id'], name=rule['name'], condition={'agent': rule['agent'], 'tool': rule['tool']}), 'security_rule_id': rule['id']})
        elif ((rule.get('condition') or {}).get('keywords') or (rule.get('condition') or {}).get('networks')):
            from .aidr_command_rules import SHELL_TOOLS
            if event.get('tool', '').lower().split('.')[-1] in SHELL_TOOLS:
                for action in (event.get('behavior') or {}).get('actions', []):
                    if action.get('category') == 'command' and action.get('command'):
                        matches.extend(annotate(text_command_assessment(rule, action['command'])['matches'], rule))
        else:
            matches.extend(annotate(risk.detect_matches(event, rule_configuration(rule, config['security'], platform), windows=windows, system=system), rule))
    return matches


def project(detection, control, client):
    rules, paths = [], []
    if detection is not None:
        source = 'global' if not client or detection['rules_mode'] == 'inherit' else 'client'
        for category in ('sensitive', 'protected'):
            paths.append({'id': 'detection:' + category, 'kind': category, 'source': source,
                          'paths': detection[category + '_paths'], 'builtin_ids': [item['id'] for item in catalog.CATALOG
                            if item['category'] == category and item['id'] in detection['builtin_ids']]})
        for code, severity, path in [('sensitive_path_read', 'medium', 'sensitive'),
                                      ('protected_path_change', 'high', 'protected'),
                                      ('tool_policy_denied', 'medium', None), ('system_access_denied', 'medium', None)]:
            rules.append({'id': 'detection:' + code, 'domain': 'detection', 'kind': 'event', 'code': code,
                          'source': source, 'enabled': detection['enabled'], 'severity': severity,
                          'action': 'none', 'path_set': 'detection:' + path if path else None})
        for code in catalog.COMMANDS:
            rules.append({'id': 'detection:' + code, 'domain': 'detection', 'kind': 'builtin', 'code': code,
                          'source': source, 'enabled': code in detection['command_rules'], 'severity': 'high',
                          'action': 'none', 'path_set': 'detection:protected' if code in ('destructive_command', 'protected_permissions') else None})
        for rule in detection.get('custom_commands', []):
            key = 'detection:custom:' + rule['id']
            path = rule['condition'].get('path_prefix')
            rules.append({'id': key, 'domain': 'detection', 'kind': 'custom', 'code': rule['id'],
                          'name': rule['name'], 'source': source, 'enabled': rule['enabled'],
                          'severity': rule['severity'], 'action': 'none', 'condition': rule['condition'],
                          'platforms': rule['platforms'], 'path_set': key if path else None})
            if path:
                paths.append({'id': key, 'kind': 'prefix', 'source': source, 'paths': [path], 'builtin_ids': [], 'rule_id': key})
    source = 'global' if not client or control['inherit'] else 'client'
    policy = (control.get('global_policy') if client and control['inherit'] else control.get('policy')) or {'rules': [], 'default_action': 'allow'}
    for rule in policy['rules']:
        key = 'control:' + rule['id']
        path = (rule.get('command') or {}).get('path_prefix')
        rules.append({'id': key, 'domain': 'control', 'kind': 'custom', 'code': rule['id'], 'name': rule['id'],
                      'source': source, 'enabled': True, 'severity': None, 'action': rule['decision'],
                      'condition': rule.get('command'), 'agent': rule['agent'], 'tool': rule['tool'], 'path_set': key if path else None})
        if path:
            paths.append({'id': key, 'kind': 'prefix', 'source': source, 'paths': [path], 'builtin_ids': [], 'rule_id': key})
    for group in paths:
        group['rule_ids'] = [rule['id'] for rule in rules if rule['path_set'] == group['id']]
    return {'rules': rules, 'path_sets': paths}
