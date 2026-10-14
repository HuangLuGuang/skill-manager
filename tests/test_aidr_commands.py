"""Static command syntax and counting boundaries; input is never evaluated."""
import pytest

from backend.aidr_commands import parse_command, command_counts, behavior_commands


@pytest.mark.parametrize('source,expected', [
    ("sed -n '1,180p' test.py\nrg 'HOOK|未按单一程序' backend\nrg 'entry|probe' web", ['sed', 'rg', 'rg']),
    ('A=1 /usr/bin/printf x > out 2>&1; pwd && rg x f || cat f | sort & wait', ['printf', 'pwd', 'rg', 'cat', 'sort', 'wait']),
    ("printf '%s\\n' 'a;b|c\nd'\n# rg fake\nrg -- \\\n  'x|y' f", ['printf', 'rg']),
    ("cat <<'END'\nrg fake\n$(evil)\nEND\npwd", ['cat', 'pwd']),
    ('cat <<END\n$(printf hello)\nEND', ['cat', 'printf']),
    ('(cd /tmp; ls) && { pwd; echo ok; }', ['cd', 'ls', 'pwd', 'echo']),
    ('if test -f a; then rg x a; else echo missing; fi', ['test', 'rg', 'echo']),
    ('for x in a b; do rg x "$x"; done; f(){ echo hi; }; f', ['rg', 'echo', 'f']),
    ('echo "$(pwd)"; cat <(rg x a)', ['echo', 'pwd', 'cat', 'rg']),
    ('X=$(pwd); "$CMD" arg; "./my tool" arg', ['pwd', '', '']),
    ('"/bin/echo" hi; r\\\ng x a', ['echo', 'rg']),
    ('python -c "print(1)"; bash -c "echo inner; rg x"', ['python', 'bash']),
    ('A=1\n# just comments\n', []),
])
def test_shell_syntax(source, expected):
    parsed = parse_command(source)
    assert [c['program'] for c in parsed['commands']] == expected
    assert parsed['status'] == ('partial' if '' in expected else 'complete')


def test_spans_preserve_redirection_unicode_and_multiline_source():
    source = "echo 中文 > out\nrg 'a\nb' f"
    commands = parse_command(source)['commands']
    assert commands[0]['text'] == 'echo 中文 > out'
    assert commands[1]['text'] == "rg 'a\nb' f"
    assert commands[1]['line'] == 2 and commands[1]['end_line'] == 3


def test_limits_invalid_input_and_no_execution(tmp_path):
    target = tmp_path / 'must-not-exist'
    assert parse_command(f'touch {target}')['commands'][0]['program'] == 'touch'
    assert not target.exists()
    for source in ("echo 'unterminated", 'cat <<END\nbody', 'echo hi &&'):
        assert parse_command(source) == {'status': 'invalid', 'commands': []}
    assert parse_command('echo hi', truncated=True)['status'] == 'truncated'
    assert parse_command('echo ' + 'x' * 32768)['status'] == 'limit'
    assert parse_command('pwd\n' * 513)['status'] == 'limit'
    assert parse_command('cat [HEREDOC OMITTED]')['status'] == 'unavailable'


def test_full_body_priority_and_wrapper_literal_actions():
    body = {'category': 'command', 'actions': [{'category': 'command', 'command': 'sed REDACTED'}],
            'contents': [{'kind': 'command_body', 'source_field': 'input.cmd', 'text': 'sed a\nrg x\nrg y'}]}
    assert command_counts(body) == {'sed': 1, 'rg': 2}
    body['contents'][0]['truncated'] = True
    assert command_counts(body) == {}
    assert behavior_commands(body)[0]['status'] == 'truncated'
    wrapper = {'category': 'wrapper', 'contents': [{'kind': 'command_body', 'source_field': 'input.code',
               'text': 'await tools.exec_command({cmd: "pwd"})'}],
               'actions': [{'category': 'command', 'command': 'pwd\nrg x'}, {'category': 'command', 'command': 'pwd'}]}
    assert command_counts(wrapper) == {'pwd': 2, 'rg': 1}


def test_dynamic_programs_do_not_get_invented_names():
    assert command_counts({'category': 'command', 'actions': [{'category': 'command', 'command': '"$CMD" hi; echo $(pwd)'}]}) == {'echo': 1, 'pwd': 1}


def test_metadata_only_legacy_commands_and_truncation():
    from backend.aidr_content import metadata_view
    b = {'truncated': True, 'actions': [{'category': 'command', 'command': 'echo clipped'}],
         'contents': [{'kind': 'command_body', 'source_field': 'input.cmd', 'text': 'PRIVATE-BODY'}]}
    view = metadata_view(b)
    assert 'text' not in view['contents'][0]
    assert 'command' not in view['actions'][0]
    assert 'command_analysis' not in view['actions'][0]
    assert b['contents'][0]['text'] == 'PRIVATE-BODY'
