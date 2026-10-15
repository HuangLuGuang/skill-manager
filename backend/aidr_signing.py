"""Provision the persistent AIDR P-256 identity before Docker starts the API."""
import argparse
import os
from pathlib import Path
import stat
import tempfile

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def key_path():
    value = os.environ.get('AIDR_POLICY_SIGNING_KEY_FILE', '')
    if not value:
        raise ValueError('AIDR_POLICY_SIGNING_KEY_FILE must be configured')
    return Path(value)


def load_key(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size > 16384 or info.st_uid != os.geteuid():
            raise ValueError('AIDR key must be a private regular file owned by the service user')
        key = serialization.load_pem_private_key(source.read(16385), password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
        raise ValueError('AIDR key must be an unencrypted P-256 PEM private key')
    return key


def initialize_key(path):
    try:
        return load_key(path)
    except FileNotFoundError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    key = ec.generate_private_key(ec.SECP256R1())
    raw = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    fd, temporary = tempfile.mkstemp(prefix='.aidr-key-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as target:
            target.write(raw)
            target.flush()
            os.fsync(target.fileno())
        try:
            # Publish a complete 0600 file atomically; concurrent initializers reuse the winner.
            os.link(temporary, path)
        except FileExistsError:
            pass
    finally:
        os.unlink(temporary)
    return load_key(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Validate the existing key without creating it')
    args = parser.parse_args()
    try:
        path = key_path()
        (load_key if args.check else initialize_key)(path)
    except (OSError, ValueError, TypeError):
        parser.exit(1, 'aidr.enforcement_signer_unavailable: check AIDR_POLICY_SIGNING_KEY_FILE, persistent mount, service UID, private file permissions and P-256 PEM format. Existing keys are never replaced.\n')
    print('AIDR policy signing key ready')


if __name__ == '__main__':
    main()
