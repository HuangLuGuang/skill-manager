"""Bounded literal shell-command matching. Never invokes a shell."""
import posixpath
import re
from typing import Literal
from pydantic import Field, model_validator
from .aidr_behavior import Strict

SHELL_TOOLS = {'bash', 'exec', 'exec_command', 'shell', 'runcommand', 'run_terminal_cmd', 'run_shell_command'}
INDIRECT_COMMANDS = {'sudo', 'env', 'sh', 'bash', 'zsh', 'eval', 'exec', 'command', 'xargs', 'find', 'cd', 'source', '.', 'time', 'nohup', 'timeout', 'nice', 'doas', 'busybox', 'builtin', 'setsid', 'if', 'then', 'else', 'elif', 'fi', 'for', 'while', 'until', 'do', 'done', 'case', 'esac', 'function', 'select'}


class CommandCondition(Strict):
    executable: str = Field(pattern=r'^[A-Za-z0-9_./+-]{1,128}$')
    args_all: list[str] = Field(default_factory=list, max_length=16)
    args_any: list[str] = Field(default_factory=list, max_length=16)
    path_prefix: str = Field(default='', max_length=512)
    pipe_to: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode='after')
    def valid(self):
        for value in self.args_all + self.args_any:
            if not value or len(value.encode()) > 256 or any(ord(c) < 32 for c in value):
                raise ValueError('hook_command_argument_invalid')
        if self.path_prefix and (len(self.path_prefix.encode()) > 512 or not self.path_prefix.startswith('/') or self.path_prefix.startswith('//') or posixpath.normpath(self.path_prefix) != self.path_prefix):
            raise ValueError('hook_command_path_invalid')
        if any(not re.fullmatch(r'[A-Za-z0-9_.+-]{1,128}', x) for x in self.pipe_to):
            raise ValueError('hook_command_pipeline_invalid')
        return self


class CommandObservation(Strict):
    schema_version: Literal[1]
    policy_revision: str = Field(pattern=r'^[1-9][0-9]{0,17}$')
    matched: list[str] = Field(max_length=128)
    unresolved: list[str] = Field(max_length=128)

    @model_validator(mode='after')
    def valid(self):
        ids = self.matched + self.unresolved
        if len(set(ids)) != len(ids) or any(not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', x) for x in ids):
            raise ValueError('hook_command_observation_invalid')
        return self


def parse(command):
    """Return (argv, outgoing operator) pairs, or None for unsupported syntax."""
    if not command or len(command.encode()) > 32768:
        return None
    commands, argv, token, quote, started = [], [], '', '', False
    i = 0
    while i < len(command):
        c = command[i]
        if ord(c) < 32 and c not in '\n\t':
            return None
        if quote:
            if c == quote:
                quote = ''
            elif quote == '"' and c in '$`\\':
                return None
            else:
                token += c
        elif c in "'\"":
            quote, started = c, True
        elif c == '\\':
            i += 1
            if i == len(command) or command[i] == '\n':
                return None
            token += command[i]
            started = True
        elif c in '$`<>()[{}~*?#!':
            return None
        elif c in ' \t\n;|&':
            if started:
                argv.append(token)
                token, started = '', False
            if c in '\n;|&':
                op = c
                if c in '|&' and i+1 < len(command) and command[i+1] == c:
                    op += c
                    i += 1
                if not argv:
                    if c in '\n;' and commands:
                        i += 1
                        continue
                    return None
                commands.append((argv, op))
                argv = []
        else:
            token += c
            started = True
        i += 1
    if quote:
        return None
    if started:
        argv.append(token)
    if argv:
        commands.append((argv, ''))
    elif commands and commands[-1][1] in ('|', '&&', '||'):
        return None
    # These constructs can execute hidden commands or change path resolution.
    if not commands or len(commands) > 128:
        return None
    for index, (a, _) in enumerate(commands):
        name = posixpath.basename(a[0])
        pipe_shell = name in {'sh', 'bash'} and len(a) == 1 and index > 0 and commands[index-1][1] == '|'
        if not a[0] or '=' in a[0] or (name in INDIRECT_COMMANDS and not pipe_shell):
            return None
    return commands


def command_match(condition, command, cwd='', decision='deny'):
    parts = parse(command)
    if parts is None:
        return 'unresolved'
    matches = []
    for index, (argv, op) in enumerate(parts):
        executable = argv[0] if '/' in condition['executable'] else posixpath.basename(argv[0])
        args = set(argv[1:])
        for arg in argv[1:]:
            if re.fullmatch(r'-[A-Za-z]{2,}', arg):
                args.update('-' + c for c in arg[1:])
        matched = executable == condition['executable'] and all(a in args for a in condition.get('args_all', []))
        matched &= not condition.get('args_any') or any(a in args for a in condition['args_any'])
        prefix = condition.get('path_prefix', '')
        if matched and prefix:
            paths = [a for a in argv[1:] if not a.startswith('-')]
            if any(not p.startswith('/') for p in paths) and not cwd.startswith('/'):
                return 'unresolved'
            paths = [posixpath.normpath('/' + posixpath.join(cwd, p).lstrip('/')) for p in paths]
            checks = [p == prefix or p.startswith(prefix.rstrip('/') + '/') for p in paths]
            matched = bool(checks) and (all(checks) if decision == 'allow' else any(checks))
        if condition.get('pipe_to'):
            matched &= op == '|' and index+1 < len(parts) and posixpath.basename(parts[index+1][0][0]) in condition['pipe_to']
        matches.append(matched)
    return 'matched' if (all(matches) if decision == 'allow' else any(matches)) else 'unmatched'


def observe(policy, agent, tool, command, cwd=''):
    result = dict(schema_version=1, policy_revision=str(policy.get('revision', '1')), matched=[], unresolved=[])
    if tool.lower().split('.')[-1] not in SHELL_TOOLS:
        return result
    for rule in policy['rules']:
        if rule.get('command') and rule['agent'] in ('*', agent) and rule['tool'] in ('*', tool):
            state = command_match(rule['command'], command, cwd, rule['decision'])
            if state != 'unmatched':
                result[state].append(rule['id'])
    return result
