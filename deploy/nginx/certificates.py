"""Maintain a persistent self-signed certificate using the backend image libraries."""
import ipaddress
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import time

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def renew(directory, hosts, now=None):
    now = now or datetime.now(timezone.utc)
    names = []
    for host in hosts.split(","):
        host = host.strip()
        try:
            names.append(x509.IPAddress(ipaddress.ip_address(host)))
        except ValueError:
            names.append(x509.DNSName(host.encode("idna").decode("ascii")))
    path = directory / "server.pem"
    if path.exists():
        cert = x509.load_pem_x509_certificate(path.read_bytes())
        if (cert.not_valid_after_utc > now + timedelta(days=30)
                and cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
                == x509.SubjectAlternativeName(names)):
            return False
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Agent Manager")])
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=365))
            .add_extension(x509.SubjectAlternativeName(names), critical=False)
            .sign(key, hashes.SHA256()))
    directory.mkdir(parents=True, exist_ok=True)
    # One atomic file keeps Nginx from reading a certificate/key from different renewals.
    temp = directory / "server.pem.tmp"
    with temp.open("wb") as out:
        os.chmod(temp, 0o600)
        out.write(cert.public_bytes(serialization.Encoding.PEM))
        out.write(key.private_bytes(serialization.Encoding.PEM,
                                   serialization.PrivateFormat.PKCS8,
                                   serialization.NoEncryption()))
    temp.replace(path)
    print("Self-signed TLS certificate renewed (365 days)", flush=True)
    return True


if __name__ == "__main__":
    os.umask(0o077)
    while True:
        renew(Path("/certificates"), os.environ.get("TLS_HOSTS", "localhost,127.0.0.1"))
        time.sleep(86400)
