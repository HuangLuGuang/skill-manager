from datetime import datetime, timedelta, timezone
import json
import socket
import ssl
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from agent_manager.core.dify_console_client import DifyConsoleClient, DifyConsoleClientConfig, DifyConsoleError


@pytest.mark.parametrize("certificate_host", ["dify.review.test", "wrong.review.test"])
def test_pinned_https_preserves_tls_identity(tmp_path, monkeypatch, certificate_host):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, certificate_host)])
    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(private_key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(hours=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(certificate_host)]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(private_key, hashes.SHA256())
    )
    cert_path = tmp_path / "server.pem"
    key_path = tmp_path / "server.key"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(private_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption(),
    ))
    received = []
    server_names = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            received.append((self.path, self.headers["Host"], self.headers["Authorization"]))
            payload = json.dumps({"data": {"name": "TLS verified"}}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_port
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(cert_path, key_path)
    server_context.set_servername_callback(lambda _sock, hostname, _ctx: server_names.append(hostname))
    server.socket = server_context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    original_socket = socket.socket
    original_resolve = socket.getaddrinfo
    original_context = ssl.create_default_context
    connections = []

    class TestSocket(original_socket):
        def connect(self, address):
            if address[0] == "8.8.8.8":
                connections.append(address)
                address = ("127.0.0.1", port)
            return super().connect(address)

    def resolve(host, request_port, *args, **kwargs):
        if host == "dify.review.test":
            return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", request_port or port))]
        return original_resolve(host, request_port, *args, **kwargs)

    def trusted_context(*args, **kwargs):
        context = original_context(*args, **kwargs)
        context.load_verify_locations(cafile=str(cert_path))
        return context

    monkeypatch.setattr(socket, "socket", TestSocket)
    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    monkeypatch.setattr(ssl, "create_default_context", trusted_context)
    try:
        client = DifyConsoleClient(DifyConsoleClientConfig(
            base_url=f"https://dify.review.test:{port}", workspace_id="workspace", app_id="app",
            admin_api_key="test-secret", expected_ips=("8.8.8.8",), max_retries=0,
        ))
        if certificate_host == "dify.review.test":
            assert client.get_app_detail() == {"name": "TLS verified"}
            assert received == [("/console/api/apps/app", f"dify.review.test:{port}", "Bearer test-secret")]
        else:
            with pytest.raises(DifyConsoleError):
                client.get_app_detail()
            assert not received
        assert connections == [("8.8.8.8", port)]
        assert server_names == ["dify.review.test"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
