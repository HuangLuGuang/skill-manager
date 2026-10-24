"""Bounded literal Windows command detection; never reads scripts or executes code."""
import ntpath
import re


def program(value):
    return ntpath.basename(value).lower().removesuffix('.exe')


def absolute(value):
    drive, tail = ntpath.splitdrive(value)
    return bool(drive and (tail.startswith(('\\', '/')) or (drive.startswith('\\\\') and not tail)))


def parse(text, shell='', depth=0):
    if not text or len(text.encode()) > 32768 or depth > 1 or '[REDACTED]' in text:
        return None
    # Only explicit command-text wrappers are unwrapped; script files stay unresolved.
    wrapper = re.match(r'^\s*("[^"]+"|[^\s]+)\s+(.*)$', text, re.S)
    if wrapper and program(wrapper[1].strip('"')) in ('cmd', 'powershell', 'pwsh'):
        name, rest = program(wrapper[1].strip('"')), wrapper[2]
        pattern = r'(?i)(?:/d\s+)?/c\s+(.+)' if name == 'cmd' else r'(?i)(?:(?:-NoProfile|-NonInteractive|-NoLogo)\s+)*-Command\s+(.+)'
        match = re.fullmatch(pattern, rest, re.S)
        if not match:
            return None
        body = match[1]
        if body.startswith('"') and body.endswith('"'):
            body = body[1:-1]
        return parse(body, 'cmd' if name == 'cmd' else 'powershell', depth + 1)
    parts, argv, token, quote, started = [], [], '', '', False
    i = 0
    while i < len(text):
        char = text[i]
        if ord(char) < 32 and char not in '\r\n\t':
            return None
        if quote:
            if char == quote:
                if i + 1 < len(text) and text[i + 1] == quote:
                    return None
                quote = ''
            else:
                token += char
        elif char in ('"', "'"):
            if char == "'" and shell == 'cmd':
                return None
            quote, started = char, True
        elif char in ' \t\r\n;|&':
            if started:
                argv.append(token)
                token, started = '', False
            if char in '\n;|&':
                if shell == 'cmd' and char == ';':
                    return None
                op = char
                if char in '|&' and i + 1 < len(text) and text[i + 1] == char:
                    op += char
                    i += 1
                if not argv:
                    return None
                parts.append((argv, op))
                argv = []
        elif char in '<>`^{}()':
            return None
        else:
            token += char
            started = True
        i += 1
    if quote:
        return None
    if started:
        argv.append(token)
    if argv:
        parts.append((argv, ''))
    elif parts and parts[-1][1] in ('|', '&&', '||'):
        return None
    if not parts or len(parts) > 128:
        return None
    blocked = {'cmd', 'powershell', 'pwsh', 'iex', 'invoke-expression', 'invoke-command', 'start-process',
               'call', 'for', 'if', 'set', 'set-location', 'cd', 'pushd', 'popd', 'start', 'runas', 'function'}
    for args, _ in parts:
        if program(args[0]) in blocked or args[0].lower().endswith(('.ps1', '.cmd', '.bat')) or not args[0]:
            return None
        for arg in args:
            # Literal boolean switches are the only supported PowerShell expansion.
            cleaned = re.sub(r'(?i)^-(confirm|whatif):\$(true|false)$', '', arg)
            if any(c in cleaned for c in '$%`^{}<>!'):
                return None
        if program(args[0]) in ('rm', 'ri', 'del', 'erase', 'rd', 'rmdir') and (shell == 'powershell' or
                (shell != 'cmd' and (program(args[0]) in ('rm', 'ri') or any(a.startswith('-') for a in args[1:])))):
            args[0] = 'Remove-Item'
    return parts


def ps_arguments(args, values, switches):
    result, positional = {}, []
    index = 0
    while index < len(args):
        arg = args[index]
        key, colon, value = arg.lower().partition(':')
        if arg.startswith('-'):
            if key in ('-whatif', '-confirm'):
                if colon and value not in ('$true', '$false'):
                    return None
                value = value != '$false'
            elif key in switches and not colon:
                value = True
            elif key in values and not colon and index + 1 < len(args) and not args[index + 1].startswith('-'):
                index += 1
                value = args[index]
            else:
                return None
            if key in result:
                return None
            result[key] = value
        else:
            positional.append(arg)
        index += 1
    result['positional'] = positional
    return result


def builtin(argv):
    """Return code, status, targets. Path-sensitive results are filtered by the caller."""
    name, args = program(argv[0]), argv[1:]
    codes = {'format': 'filesystem_format', 'format-volume': 'filesystem_format',
             'dd': 'device_write', 'clear-disk': 'device_write', 'diskpart': 'device_write',
             'del': 'destructive_command', 'erase': 'destructive_command', 'rd': 'destructive_command',
             'rmdir': 'destructive_command', 'remove-item': 'destructive_command',
             'icacls': 'protected_permissions', 'takeown': 'protected_permissions', 'set-acl': 'protected_permissions'}
    code = codes.get(name)
    if not code:
        return None, 'unmatched', []
    unresolved = (code, 'unresolved', [])
    if any(a.lower() in ('/?', '-?', '-help', '--help') for a in args):
        return code, 'unmatched', []
    if name in ('diskpart', 'set-acl'):
        return unresolved
    if name == 'format':
        targets = [a for a in args if not a.startswith('/')]
        options = [a for a in args if a.startswith('/')]
        if len(targets) != 1 or any(not re.fullmatch(r'(?i)/(?:q|x|c|fs:(?:ntfs|fat|fat32|exfat|refs|udf)|v:[^/]*|p:\d+)', a) for a in options):
            return unresolved
        if not re.fullmatch(r'[A-Za-z]:', targets[0]) and not absolute(targets[0]):
            return unresolved
        return code, 'matched', targets
    if name in ('format-volume', 'clear-disk', 'remove-item'):
        values = {'format-volume': {'-driveletter', '-filesystem', '-newfilesystemlabel', '-allocationunitsize'},
                  'clear-disk': {'-number'}, 'remove-item': {'-path', '-literalpath'}}[name]
        switches = {'-force', '-full'} if name == 'format-volume' else {'-removedata', '-removeoem'} if name == 'clear-disk' else {'-force', '-recurse'}
        parsed = ps_arguments(args, values, switches)
        if parsed is None:
            return unresolved
        if parsed.get('-whatif'):
            return code, 'unmatched', []
        if name == 'remove-item':
            selectors = [parsed[k] for k in ('-path', '-literalpath') if k in parsed]
            targets = selectors + parsed['positional']
            if len(selectors) > 1 or (selectors and parsed['positional']) or not targets:
                return unresolved
            if '-literalpath' in parsed and any('*' in p or '?' in p for p in targets):
                return unresolved
        else:
            key = '-driveletter' if name == 'format-volume' else '-number'
            targets = [parsed[key]] if key in parsed else parsed['positional']
            if (key in parsed and parsed['positional']) or len(targets) != 1:
                return unresolved
            pattern = r'[A-Za-z]' if name == 'format-volume' else r'\d+'
            if not re.fullmatch(pattern, targets[0]):
                return unresolved
            targets = [targets[0] + ':' if name == 'format-volume' else 'PhysicalDrive' + targets[0]]
        return code, 'matched', targets
    if name == 'dd':
        options = {}
        for arg in args:
            key, sep, value = arg.partition('=')
            if not sep or key in options or key not in {'if', 'of', 'bs', 'ibs', 'obs', 'count', 'skip', 'seek', 'conv'}:
                return unresolved
            options[key] = value
        if re.fullmatch('0+', options.get('count', '')):
            return code, 'unmatched', []
        target = options.get('of', '')
        matched = bool(re.fullmatch(r'(?i)\\\\\.\\(?:PhysicalDrive\d+|[A-Z]:)', target))
        return code, 'matched' if matched else 'unmatched', [target] if matched else []
    if name in ('del', 'erase', 'rd', 'rmdir'):
        allowed = {'/s', '/q', '/f', '/p'} if name in ('del', 'erase') else {'/s', '/q'}
        if any(a.startswith('/') and a.lower() not in allowed for a in args):
            return unresolved
        targets = [a for a in args if not a.startswith('/')]
        return (code, 'matched', targets) if targets else unresolved
    if name == 'takeown':
        targets, index = [], 0
        while index < len(args):
            key = args[index].lower()
            if key in ('/a', '/r'):
                pass
            elif key in ('/f', '/d') and index + 1 < len(args):
                index += 1
                if key == '/f':
                    targets.append(args[index])
                elif args[index].lower() not in ('y', 'n'):
                    return unresolved
            else:
                return unresolved
            index += 1
        return (code, 'matched', targets) if len(targets) == 1 else unresolved
    if name == 'icacls':
        if not args or args[0].startswith('/'):
            return unresolved
        broad, index = False, 1
        while index < len(args):
            key = args[index].lower()
            if key in ('/t', '/c', '/l', '/q'):
                pass
            elif key in ('/grant', '/grant:r') and index + 1 < len(args):
                index += 1
                principal, sep, permission = args[index].rpartition(':')
                if not sep or not re.fullmatch(r'(?i)(?:\((?:OI|CI|IO|NP|I)\))*(?:F|M|W|R|RX|N)', permission):
                    return unresolved
                broad |= principal.lower().lstrip('*') in {'everyone', 'users', 'builtin\\users', 'authenticated users', 's-1-1-0', 's-1-5-11', 's-1-5-32-545'} and permission[-1:].upper() in ('F', 'M', 'W') and '(IO)' not in permission.upper()
            else:
                return unresolved
            index += 1
        return code, 'matched' if broad else 'unmatched', [args[0]] if broad else []
    return unresolved


def custom_match(condition, parts, cwd):
    unresolved = False
    for index, (argv, op) in enumerate(parts):
        expected = condition['executable']
        executable = ntpath.normcase(argv[0]) if ntpath.dirname(expected) else program(argv[0])
        expected = ntpath.normcase(expected) if ntpath.dirname(expected) else program(expected)
        if executable != expected:
            continue
        args = {a.casefold() for a in argv[1:]}
        if not all(a.casefold() in args for a in condition.get('args_all', [])):
            continue
        if condition.get('args_any') and not any(a.casefold() in args for a in condition['args_any']):
            continue
        if condition.get('pipe_to') and not (op == '|' and index + 1 < len(parts) and program(parts[index + 1][0][0]) in {program(p) for p in condition['pipe_to']}):
            continue
        prefix = condition.get('path_prefix')
        if prefix:
            if not absolute(prefix):
                unresolved = True
                continue
            paths = [a for a in argv[1:] if not a.startswith(('-', '/'))]
            resolved = [resolve_path(p, cwd) for p in paths]
            normalized = ntpath.normcase(prefix)
            if not any(p and (p == normalized or p.startswith(normalized.rstrip('\\') + '\\')) for p in resolved):
                unresolved |= any(p is None for p in resolved)
                continue
        return 'matched'
    return 'unresolved' if unresolved else 'unmatched'


def resolve_path(value, cwd):
    if not value or any(c in value for c in '*?[]'):
        return None
    if not absolute(value):
        if ntpath.splitdrive(value)[0] or value.startswith(('\\', '/')) or not absolute(cwd):
            return None
        value = ntpath.join(cwd, value)
    return ntpath.normcase(ntpath.normpath(value))


def target_path(value, cwd):
    # A terminal all-files glob identifies its directory, not arbitrary wildcard expansion.
    if value.endswith(('\\*', '\\*.*', '/*', '/*.*')):
        value = value.rsplit('\\' if '\\' in value else '/', 1)[0] + '\\'
    return resolve_path(value, cwd)
