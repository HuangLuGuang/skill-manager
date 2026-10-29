import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess

from cryptography import x509
from cryptography.hazmat.primitives import serialization


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("certificates", ROOT / "deploy/nginx/certificates.py")
certificates = importlib.util.module_from_spec(spec)
spec.loader.exec_module(certificates)


def test_certificate_creation_reuse_renewal_and_host_changes(tmp_path):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    hosts = "localhost,example.test,10.10.71.35,::1"
    assert certificates.renew(tmp_path, hosts, now)
    path = tmp_path / "server.pem"
    original = path.read_bytes()
    cert = x509.load_pem_x509_certificate(original)
    key = serialization.load_pem_private_key(original, password=None)
    assert cert.public_key().public_numbers() == key.public_key().public_numbers()
    assert len(cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value) == 4
    assert path.stat().st_mode & 0o777 == 0o600
    assert not certificates.renew(tmp_path, hosts, now + timedelta(days=334))
    assert path.read_bytes() == original
    assert certificates.renew(tmp_path, hosts, now + timedelta(days=336))
    assert path.read_bytes() != original
    assert certificates.renew(tmp_path, "other.test", now + timedelta(days=337))


def test_https_listener_preserves_routes_and_redirect_method():
    script = (ROOT / "deploy/nginx/https.sh").read_text()
    # Execute the real sed transformation against the shared proxy configuration.
    expression = script.split("sed '", 1)[1].split("' \\", 1)[0]
    result = subprocess.run(["sed", expression, str(ROOT / "deploy/nginx/default.conf")],
                            capture_output=True, text=True, check=True).stdout
    original = (ROOT / "deploy/nginx/default.conf").read_text()
    assert result[result.index("    # Allow multipart"): ] == original[original.index("    # Allow multipart"): ]
    assert "listen 443 ssl;" in result
    assert "ssl_protocols TLSv1.2 TLSv1.3;" in result
    assert "return 308 https://$host$request_uri;" in script
