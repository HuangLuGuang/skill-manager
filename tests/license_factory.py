"""Real, ephemeral signing keys for licensed test deployments."""
import base64
import hashlib
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agent_manager.core.licensing import FEATURES, POLICY, LicenseStore, canonical


class TestLicenseIssuer:
    __test__ = False

    def __init__(self, root, monkeypatch):
        root.mkdir()
        self.keys = root / 'keys'
        self.keys.mkdir()
        self.key = Ed25519PrivateKey.generate()
        raw = self.key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.kid = hashlib.sha256(raw).hexdigest()[:16]
        (self.keys / f'{self.kid}.pem').write_bytes(self.key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
        self.path = root / 'state.db'
        monkeypatch.setenv('AGENT_MANAGER_LICENSE_STATE_PATH', str(self.path))
        monkeypatch.setenv('AGENT_MANAGER_LICENSE_KEYS_DIR', str(self.keys))
        self.store = LicenseStore()
        self.request = self.store.request('test-customer', 'Test Customer')

    def payload(self, revision=1, **changes):
        now = datetime.now(timezone.utc)
        return {**self.request, 'license_id':'LIC-'+uuid4().hex, 'revision':revision,
                'issued_at':now.isoformat(), 'not_before':(now-timedelta(hours=1)).isoformat(),
                'expires_at':(now+timedelta(days=365)).isoformat(), 'features':list(FEATURES),
                'limits':{'clients':1000000}, 'expiry_policy':POLICY, **changes}

    def sign(self, payload):
        encode = lambda raw: base64.urlsafe_b64encode(raw).rstrip(b'=').decode()
        encoded = encode(canonical(payload))
        signature = self.key.sign(f'am-license-v1.{self.kid}.{encoded}'.encode())
        return canonical({'format':'am-license-v1','key_id':self.kid,'payload':encoded,'signature':encode(signature)})

    def install(self, revision=1, **changes):
        payload = self.payload(revision, **changes)
        raw = self.sign(payload)
        self.store.import_license(raw, 'test-issuer')
        return payload, raw
