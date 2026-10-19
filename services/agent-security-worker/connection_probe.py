"""Bounded OpenAI Chat Completions connectivity probe in the evaluation Worker."""
import json
import ssl
import time

import httpx

from aig_adapter import verify_worker_dns_pin, ScanStopped


def probe(target, secret, *, timeout=10, max_bytes=65536):
    secure = target["endpoint_url"].startswith("https://")
    checks = {"network": "pending", "tls": "pending" if secure else "skipped",
              "authentication": "pending", "protocol": "pending"}
    size = 0
    error = None
    try:
        verify_worker_dns_pin(target)
        started = time.monotonic()
        with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as client:
            with client.stream("POST", target["endpoint_url"].rstrip("/") + "/chat/completions",
                               headers={"Authorization": "Bearer " + secret},
                               json={"model": target["config"]["model"], "messages": [{"role": "user", "content": "Reply OK."}],
                                     "stream": False}) as response:
                checks["network"] = "passed"
                checks["tls"] = "passed" if secure else "skipped"
                if response.status_code in {401, 403}:
                    checks["authentication"] = "failed"
                    error = "CONNECTION_AUTH_FAILED"
                elif not 200 <= response.status_code < 300:
                    checks["protocol"] = "failed"
                    error = "CONNECTION_PROTOCOL_INVALID"
                else:
                    checks["authentication"] = "passed"
                    chunks = []
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > max_bytes:
                            raise ValueError("response size limit")
                        if time.monotonic() - started > timeout:
                            raise httpx.ReadTimeout("probe deadline exceeded")
                        chunks.append(chunk)
                    content = json.loads(b"".join(chunks))["choices"][0]["message"]["content"]
                    if not isinstance(content, str) or not content.strip():
                        raise ValueError("empty text response")
                    checks["protocol"] = "passed"
    except httpx.TimeoutException:
        error = "CONNECTION_TIMED_OUT"
    except (ValueError, KeyError, IndexError, TypeError):
        checks["protocol"] = "failed"
        error = "CONNECTION_PROTOCOL_INVALID"
    except (httpx.HTTPError, ScanStopped) as exc:
        cause = exc
        certificate_error = False
        while cause is not None:
            certificate_error |= isinstance(cause, ssl.SSLCertVerificationError)
            cause = cause.__cause__
        if certificate_error:
            checks["network"], checks["tls"] = "passed", "failed"
            error = "CONNECTION_TLS_FAILED"
        else:
            checks["network"] = "failed"
            error = "CONNECTION_NETWORK_FAILED"
    return checks, error, size
