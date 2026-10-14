"""Static Bash/POSIX command occurrences, never execution or policy decisions."""
from collections import Counter
import re
import shlex

from tree_sitter import Language, Parser
import tree_sitter_bash

LANGUAGE = Language(tree_sitter_bash.language())
MAX_BYTES = 32768
MAX_COMMANDS = 512
MAX_NODES = 16384


def parse_command(source, *, truncated=False):
    result = {'status': 'complete', 'commands': []}
    if truncated:
        return dict(result, status='truncated')
    if not source or not source.strip():
        return dict(result, status='unavailable')
    data = source.encode('utf-8')
    if len(data) > MAX_BYTES:
        return dict(result, status='limit')
    # These are explicit collector placeholders, not Shell source.
    if '[HEREDOC OMITTED]' in source:
        return dict(result, status='unavailable')
    parser = Parser(LANGUAGE)
    tree = parser.parse(data)
    if tree.root_node.has_error:
        return dict(result, status='invalid')
    stack = [tree.root_node]
    visited = 0
    while stack:
        node = stack.pop()
        visited += 1
        if visited > MAX_NODES:
            return {'status': 'limit', 'commands': []}
        stack.extend(reversed(node.named_children))
        if node.type != 'command':
            continue
        if len(result['commands']) >= MAX_COMMANDS:
            return {'status': 'limit', 'commands': []}
        name = node.child_by_field_name('name')
        if name is None:
            continue
        # The grammar can expose a continued executable token as separate words.
        # Join only adjacent words separated exclusively by escaped newlines.
        name_parts = [name]
        for part in node.named_children:
            if part.start_byte < name_parts[-1].end_byte:
                continue
            gap = data[name_parts[-1].end_byte:part.start_byte]
            if re.fullmatch(rb'(?:\\\n)+', gap):
                name_parts.append(part)
            else:
                break
        pending = list(name_parts)
        dynamic = False
        while pending:
            part = pending.pop()
            dynamic |= part.type in {'expansion', 'simple_expansion', 'command_substitution', 'process_substitution'}
            pending.extend(part.named_children)
        program = ''
        if not dynamic:
            try:
                words = shlex.split(b''.join(data[p.start_byte:p.end_byte] for p in name_parts).decode().replace('\\\n', ''))
                candidate = words[0].rsplit('/', 1)[-1] if len(words) == 1 else ''
                if re.fullmatch(r'[a-zA-Z0-9_.+-]{1,64}', candidate):
                    program = candidate
            except ValueError:
                pass
        if not program:
            result['status'] = 'partial'
        display = node
        if node.parent and node.parent.type == 'redirected_statement' and node.parent.child_by_field_name('body') == node:
            display = node.parent
        text = data[display.start_byte:display.end_byte].decode()
        result['commands'].append(dict(program=program, text=text[:2048], text_truncated=len(text) > 2048,
                                       line=node.start_point.row + 1, end_line=display.end_point.row + 1))
    return result


def behavior_commands(behavior):
    """Prefer captured Shell source; wrapper code is not Shell. Do not count both."""
    bodies = [item for item in behavior.get('contents') or [] if item.get('kind') == 'command_body'
              and item.get('source_field') in ('input.command', 'input.cmd')]
    if bodies:
        return [parse_command(item.get('text', ''), truncated=item.get('truncated', False)) for item in bodies]
    return [parse_command(action.get('command', ''), truncated=behavior.get('truncated', False))
            for action in behavior.get('actions') or [] if action.get('category') == 'command']


def command_counts(behavior):
    return dict(Counter(command['program'] for parsed in behavior_commands(behavior)
                        for command in parsed['commands'] if command['program']))


def content_commands(item):
    if item.get('kind') == 'command_body' and item.get('source_field') in ('input.command', 'input.cmd', 'behavior.actions.command'):
        return parse_command(item.get('text', ''), truncated=item.get('truncated', False))
    return None
