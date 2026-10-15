import concurrent.futures
import os
import subprocess
import sys

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519

from backend.aidr_signing import initialize_key, load_key


def public(key):
    return key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def test_fresh_deployment_reuses_identity_and_signs(tmp_path):
    path = tmp_path / 'data/signing/aidr.pem'
    key = initialize_key(path)
    original = path.read_bytes()
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.stat().st_uid == os.geteuid()
    assert public(initialize_key(path)) == public(key)
    assert path.read_bytes() == original
    signature = load_key(path).sign(b'device-policy', ec.ECDSA(hashes.SHA256()))
    key.public_key().verify(signature, b'device-policy', ec.ECDSA(hashes.SHA256()))
    path.chmod(0o400)
    assert public(initialize_key(path)) == public(key)
    assert path.stat().st_mode & 0o777 == 0o400


def test_concurrent_initializers_publish_one_complete_identity(tmp_path):
    path = tmp_path / 'concurrent/aidr.pem'
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        keys = list(pool.map(lambda _: public(initialize_key(path)), range(16)))
    assert len(set(keys)) == 1
    assert list(path.parent.iterdir()) == [path]


@pytest.mark.parametrize('invalid', ['permissions', 'owner', 'corrupt', 'wrong_curve', 'wrong_type', 'symlink', 'dangling', 'directory', 'fifo'])
def test_invalid_existing_identity_is_never_replaced(tmp_path, monkeypatch, invalid):
    path = tmp_path / 'aidr.pem'
    initialize_key(path)
    if invalid == 'permissions':
        path.chmod(0o644)
    elif invalid == 'owner':
        monkeypatch.setattr(os, 'geteuid', lambda: path.stat().st_uid + 1)
    elif invalid == 'corrupt':
        path.write_bytes(b'not a private key')
    elif invalid in ('wrong_curve', 'wrong_type'):
        key = ec.generate_private_key(ec.SECP384R1()) if invalid == 'wrong_curve' else ed25519.Ed25519PrivateKey.generate()
        path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    elif invalid in ('symlink', 'dangling'):
        target = tmp_path / 'original.pem'
        path.rename(target)
        path.symlink_to(target if invalid == 'symlink' else tmp_path / 'missing.pem')
    elif invalid in ('directory', 'fifo'):
        path.unlink()
        path.mkdir() if invalid == 'directory' else os.mkfifo(path, 0o600)
    before = path.lstat()
    original = path.read_bytes() if path.is_file() else None
    with pytest.raises((OSError, ValueError, TypeError)):
        initialize_key(path)
    after = path.lstat()
    assert (before.st_ino, before.st_mode) == (after.st_ino, after.st_mode)
    if original is not None:
        assert path.read_bytes() == original


def test_check_is_read_only_and_cli_does_not_disclose_private_key(tmp_path):
    path = tmp_path / 'aidr.pem'
    env = {**os.environ, 'AIDR_POLICY_SIGNING_KEY_FILE': str(path)}
    command = [sys.executable, '-m', 'backend.aidr_signing']
    checked = subprocess.run([*command, '--check'], env=env, capture_output=True, text=True)
    assert checked.returncode == 1 and not path.exists()
    result = subprocess.run(command, env=env, capture_output=True, text=True)
    assert result.returncode == 0
    assert 'PRIVATE KEY' not in result.stdout + result.stderr
    assert path.read_text() not in result.stdout + result.stderr
    checked = subprocess.run([*command, '--check'], env=env, capture_output=True, text=True)
    assert checked.returncode == 0
