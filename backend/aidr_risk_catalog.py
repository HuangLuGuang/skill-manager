"""Versioned, bounded path templates for runtime detection; no shell expansion."""
import ntpath
import posixpath
from .aidr_risk_commands import COMMANDS

VERSION = 'common-paths/1'


def entry(id, category, paths, *, directory=False):
    return {'id': id, 'category': category, 'paths': [
        {'os': os, 'path': path, 'directory': directory} for os, path in paths]}


def homes(suffix):
    return [('darwin', '/Users/{user}/' + suffix), ('darwin', '/var/root/' + suffix),
            ('linux', '/home/{user}/' + suffix), ('linux', '/root/' + suffix),
            ('windows', 'C:\\Users\\{user}\\' + suffix.replace('/', '\\'))]


CATALOG = [
    entry('ssh_private_keys', 'sensitive', [p for name in ('id_rsa', 'id_ed25519', 'id_ecdsa', 'id_dsa') for p in homes('.ssh/' + name)]),
    entry('aws_credentials', 'sensitive', homes('.aws/credentials')),
    entry('kube_config', 'sensitive', homes('.kube/config')),
    entry('package_credentials', 'sensitive', homes('.npmrc') + homes('.pypirc')),
    entry('password_database', 'sensitive', [('linux', '/etc/shadow'), ('linux', '/etc/gshadow'), ('darwin', '/etc/master.passwd'), ('darwin', '/private/etc/master.passwd')]),
    entry('ssh_authorized_keys', 'protected', homes('.ssh/authorized_keys')),
    entry('account_configuration', 'protected', [(os, prefix + name) for os, prefix in [('linux', '/etc/'), ('darwin', '/etc/'), ('darwin', '/private/etc/')] for name in ('passwd', 'group', 'sudoers')]),
    entry('sudo_configuration', 'protected', [(os, path) for os, path in [('linux', '/etc/sudoers.d'), ('darwin', '/etc/sudoers.d'), ('darwin', '/private/etc/sudoers.d')]], directory=True),
    entry('startup_configuration', 'protected', [('linux', '/etc/cron.d'), ('linux', '/etc/systemd/system'), ('darwin', '/Library/LaunchAgents'), ('darwin', '/Library/LaunchDaemons'), ('darwin', '/Users/{user}/Library/LaunchAgents'), ('windows', 'C:\\ProgramData\\Microsoft\\Windows\\Start Menu\\Programs\\Startup'), ('windows', 'C:\\Users\\{user}\\AppData\\Roaming\\Microsoft\\Windows\\Start Menu\\Programs\\Startup')], directory=True),
]
IDS = [item['id'] for item in CATALOG]


def roots(config, category, windows=False):
    if 'security_roots' in config:
        return config['security_roots']
    os = config.get('platform', 'windows' if windows else 'linux')
    return config[category + '_paths'] + [spec for item in CATALOG
        if item['id'] in config.get('builtin_ids', []) and item['category'] == category
        for spec in item['paths'] if spec['os'] == os]


def template_matches(candidate, spec, windows=False):
    path = ntpath if windows else posixpath
    parts = path.normcase(candidate).split(path.sep)
    expected = path.normcase(spec['path']).split(path.sep)
    if len(parts) < len(expected) or (not spec['directory'] and len(parts) != len(expected)):
        return False
    return all(actual == wanted or (wanted == '{user}' and actual not in ('', '.', '..'))
               for actual, wanted in zip(parts, expected))
