from __future__ import annotations

import hashlib
from base64 import b64decode, b64encode
from dataclasses import dataclass
from datetime import datetime, timezone

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

ALGORITHM = "x25519-hkdf-sha256-aesgcm-v1"


@dataclass(frozen=True)
class WorkerKeyPair:
    private_key: X25519PrivateKey
    public_key: str
    fingerprint: str


def generate_worker_key_pair() -> WorkerKeyPair:
    private_key = X25519PrivateKey.generate()
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return WorkerKeyPair(
        private_key=private_key,
        public_key=b64encode(public_bytes).decode("ascii"),
        fingerprint=hashlib.sha256(public_bytes).hexdigest(),
    )


def decrypt_secret_envelope(
    envelope: dict[str, str],
    key_pair: WorkerKeyPair,
    *,
    worker_id: str,
    task_id: str,
    credential_id: str,
) -> str:
    if envelope.get("algorithm") != ALGORITHM:
        raise ValueError("unsupported credential envelope algorithm")
    if envelope.get("recipient_fingerprint") != key_pair.fingerprint:
        raise ValueError("credential envelope recipient mismatch")
    expires_at = datetime.fromisoformat(envelope["expires_at"].replace("Z", "+00:00"))
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        raise ValueError("credential envelope expired")
    aad = b64decode(envelope["aad"], validate=True)
    expected_aad = f"{worker_id}|{task_id}|{credential_id}|{expires_at.astimezone(timezone.utc).isoformat()}".encode()
    if aad != expected_aad:
        raise ValueError("credential envelope binding mismatch")
    ephemeral = X25519PublicKey.from_public_bytes(b64decode(envelope["ephemeral_public_key"], validate=True))
    shared = key_pair.private_key.exchange(ephemeral)
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"agent-manager-security-worker-credential-v1",
    ).derive(shared)
    plaintext = AESGCM(key).decrypt(
        b64decode(envelope["nonce"], validate=True),
        b64decode(envelope["ciphertext"], validate=True),
        aad,
    )
    return plaintext.decode("utf-8")
