"""Literal command rules used by both runtime detection and the non-executing preview."""
import posixpath
import ntpath
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from .aidr_command_rules import CommandCondition, KeywordCondition, command_match
from .aidr_command_networks import NetworkCondition

LEGACY_COMMANDS = ['destructive_command', 'download_to_shell']
COMMANDS = LEGACY_COMMANDS + ['filesystem_format', 'device_write', 'protected_permissions']


class DetectionCommandCondition(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    executable: str = Field(default='', max_length=128)
    keywords: KeywordCondition | None = None
    networks: NetworkCondition | None = None
    args_all: list[str] = Field(default_factory=list, max_length=16)
    args_any: list[str] = Field(default_factory=list, max_length=16)
    path_prefix: str = Field(default='', max_length=512)
    pipe_to: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode='after')
    def valid(self):
        # Detection accepts Windows paths without widening the Hook policy contract.
        windows_executable = bool(ntpath.splitdrive(self.executable)[0])
        windows_prefix = bool(ntpath.splitdrive(self.path_prefix)[0])
        values = self.model_dump()
        for key, is_windows in (('executable', windows_executable), ('path_prefix', windows_prefix)):
            if is_windows:
                value = values[key]
                if (not ntpath.isabs(value) or ntpath.normpath(value) != value
                        or any(c in value for c in '*?%$`<>|"') or any(ord(c) < 32 for c in value)
                        or len(value.encode()) > (128 if key == 'executable' else 512)):
                    raise ValueError('invalid_windows_path')
                values[key] = 'program' if key == 'executable' else '/path'
        CommandCondition.model_validate(values)
        return self


class CustomCommandRule(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    id: str = Field(pattern=r'^custom_[A-Za-z0-9_-]{1,56}$')
    name: str = Field(min_length=1, max_length=100)
    enabled: bool = True
    platforms: list[Literal['linux', 'darwin', 'windows']] = Field(min_length=1, max_length=3)
    severity: Literal['medium', 'high'] = 'medium'
    condition: DetectionCommandCondition

    @field_validator('name')
    @classmethod
    def nonblank(cls, value):
        if not value.strip() or any(ord(c) < 32 for c in value):
            raise ValueError('invalid_name')
        return value

    @field_validator('platforms')
    @classmethod
    def unique(cls, value):
        if len(set(value)) != len(value):
            raise ValueError('duplicate_platform')
        return value


def device_target(value, platform):
    if value == '/dev/mapper/control':
        return False
    if platform == 'darwin':
        return bool(re.fullmatch(r'/dev/r?disk\d+(?:s\d+)*', value))
    if platform == 'linux':
        return bool(re.fullmatch(r'/dev/(?:[sv]d[a-z]+\d*|xvd[a-z]+\d*|nvme\d+n\d+(?:p\d+)?|mmcblk\d+(?:p\d+)?|loop\d+|mapper/[A-Za-z0-9_.+-]+)', value))
    return False


def format_target(argv, platform):
    """Return a status and explicit target for supported formatter forms."""
    program = posixpath.basename(argv[0])
    args = argv[1:]
    if platform == 'darwin' and program == 'diskutil':
        if not args or args[0] not in ('eraseDisk', 'eraseVolume', 'reformat'):
            return 'unmatched', ''
        valid = ((args[0] == 'eraseDisk' and len(args) in (4, 5))
                 or (args[0] == 'eraseVolume' and len(args) == 4)
                 or (args[0] == 'reformat' and len(args) == 2))
        if args[0] != 'reformat':
            valid = valid and not args[1].startswith('-') and bool(args[1])
        if args[0] == 'eraseDisk' and len(args) == 5:
            valid = valid and args[3] in ('GPT', 'APM', 'MBR')
        target = args[-1] if args[-1].startswith('/') else '/dev/' + args[-1]
        return ('matched', target) if valid and device_target(target, platform) else ('unresolved', '')
    formats = {'mkfs.ext2': {'-F', '-q'}, 'mkfs.ext3': {'-F', '-q'}, 'mkfs.ext4': {'-F', '-q'},
               'mkfs.xfs': {'-f', '-q'}, 'mkfs.vfat': set(), 'mkfs.exfat': set()}
    if platform != 'linux' or program not in {*formats, 'mkfs'}:
        return 'unmatched', ''
    if program == 'mkfs':
        if len(args) != 3 or args[0] != '-t' or 'mkfs.' + args[1] not in formats:
            return 'unresolved', ''
        args = args[2:]
    else:
        if any(a.startswith('-') and a not in formats[program] for a in args):
            return 'unresolved', ''
        args = [a for a in args if not a.startswith('-')]
    if len(args) != 1:
        return 'unresolved', ''
    return ('matched', args[0]) if device_target(args[0], platform) else ('unmatched', '')


def write_target(argv, platform):
    if posixpath.basename(argv[0]) != 'dd':
        return 'unmatched', ''
    options = {}
    for value in argv[1:]:
        key, sep, content = value.partition('=')
        if not sep or key in options or key not in {'if', 'of', 'bs', 'ibs', 'obs', 'cbs', 'count', 'skip', 'seek', 'conv', 'iflag', 'oflag', 'status'}:
            return 'unresolved', ''
        options[key] = content
    if re.fullmatch(r'0+', options.get('count', '')):
        return 'unmatched', ''
    target = options.get('of', '')
    return ('matched', target) if device_target(target, platform) else ('unmatched', '')


def permission_targets(argv):
    if posixpath.basename(argv[0]) != 'chmod':
        return 'unmatched', []
    args = argv[1:]
    while args and args[0] in ('-R', '--recursive', '--'):
        end = args[0] == '--'
        args = args[1:]
        if end:
            break
    if len(args) < 2 or args[0].startswith('-'):
        return 'unresolved', []
    mode = args[0]
    if re.fullmatch(r'[0-7]{3,4}', mode):
        writable = bool(int(mode[-1]) & 2)
    elif re.fullmatch(r'[ugoa]+[+=][rwx]+', mode):
        who, permissions = re.split(r'[+=]', mode)
        writable = ('o' in who or 'a' in who) and 'w' in permissions
    else:
        return 'unresolved', []
    return ('matched', args[1:]) if writable else ('unmatched', [])


def custom_matches(command, cwd, platform, rules):
    return [(rule, command_match(rule['condition'], command, cwd)) for rule in rules
            if rule['enabled'] and platform in rule['platforms']]
