"""Deterministic value replacement matching the version-three client projector."""
import re

VALUE_RULES = [
 re.compile(r'''(?i)((?:--[a-z0-9_-]*(?:token|password|passwd|secret|api[_-]?key|credential)[a-z0-9_-]*[ \t]+|\b[a-z0-9_-]*(?:token|password|passwd|secret|api[_-]?key|credential)[a-z0-9_-]*["']?[ \t]*[:=][ \t]*))("(?:\\.|[^"\\])*"|'[^']*'|(?:\\.|[^\s;,&|<>"'\\])+)'''),
 re.compile(r'''(?i)((?:authorization|proxy-authorization|cookie|set-cookie)[ \t]*[:=][ \t]*(?:Bearer[ \t]+|Basic[ \t]+)?)("(?:\\.|[^"\\])*"|'[^']*'|(?:\\.|[^\s;,&|<>"'\\])+)'''),
 re.compile(r'(?i)(\bBearer[ \t]+)([a-z0-9._~+/=-]+)'),
]
SCRIPT_BODY = re.compile(r'''(?s)(\b(?:sh|bash|zsh|python[0-9.]*|node|perl|ruby)[ \t]+(?:-c|-e|--eval|--command)[ \t]+|\bclaude[ \t]+(?:-p|--print)[ \t]+|\bcodex[ \t]+exec[ \t]+)("(?:\\.|[^"\\])*"|'[^']*')''')
INLINE_BODY = re.compile(r'''(?s)(\b(?:echo|printf)[ \t]+|--(?:data|data-raw|data-binary|prompt|body|content)(?:=|[ \t]+))((?:"(?:\\.|[^"\\])*"|'[^']*')(?:[ \t]+(?:"(?:\\.|[^"\\])*"|'[^']*'))*)''')


def redact_values(value):
    def replace(m):
        v = m[2]
        if v in ('[REDACTED]', '"[REDACTED]"', "'[REDACTED]'"):
            return m[0]
        return m[1] + (v[0] + '[REDACTED]' + v[-1] if len(v) >= 2 and v[0] in "\"'" else '[REDACTED]')
    for rule in VALUE_RULES:
        value = rule.sub(replace, value)
    for rule in [r'(?is)-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)', r'\b(?:sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9_]{8,}|AKIA[A-Z0-9]{16}|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)\b']:
        value = re.sub(rule, '[REDACTED]', value)
    value = re.sub(r'(?i)(https?://[^\s/@:]+:)([^\s/@]+)(@)', r'\1[REDACTED]\3', value)
    return re.sub(r'''(?i)(["'](?:cookie|set-cookie)[ \t]*:[ \t]*)([^"'\r\n]*)(["'])''', r'\1[REDACTED]\3', value)


def bound_command(value):
    value = SCRIPT_BODY.sub(lambda m: m[0] if re.fullmatch(r'exit [0-9]{1,3}',m[2][1:-1]) else m[1]+"'[BODY OMITTED]'", value)
    value = INLINE_BODY.sub(r"\1'[BODY OMITTED]'", value)
    return value.split('<<', 1)[0] + '[HEREDOC OMITTED]' if '<<' in value else value
