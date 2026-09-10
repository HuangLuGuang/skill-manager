"""Run with the scan image's pinned SDK and model dependencies."""

import asyncio
import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services/aig-scan-service/vendor/ai-infra-guard/AIG-PromptSecurity"))
try:
    from cli.model_utils.openailike import OpenaiAlikeModel
except ModuleNotFoundError as error:
    raise unittest.SkipTest("Requires the AI-Infra-Guard scan image dependencies") from error


class ModelAuthenticationTest(unittest.TestCase):
    def test_sync_and_async_authentication_on_the_wire(self):
        seen = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                seen.append(self.headers.get("Authorization"))
                body = json.dumps({
                    "id": "test", "object": "chat.completion", "created": 0, "model": "test",
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}],
                }).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.dict(os.environ, {"OPENAI_API_KEY": "ambient-key", "OPENAI_CUSTOM_HEADERS": "Authorization: Bearer ambient-header"}):
                for token in ("", "configured-key"):
                    os.environ["OPENAI_CUSTOM_HEADERS"] = "Authorization: Bearer ambient-header" if not token else ""
                    model = OpenaiAlikeModel("test", f"http://127.0.0.1:{server.server_port}/v1", token, 1)
                    try:
                        self.assertEqual(model.test_model_connection(), (True, "OK"))
                        self.assertEqual(model.generate("OK"), "OK")

                        async def call_async():
                            try:
                                self.assertEqual(await model.a_generate("OK"), "OK")
                            finally:
                                await model.async_client.close()

                        asyncio.run(call_async())
                    finally:
                        model.client.close()
            self.assertEqual(seen[:3], [None] * 3)
            self.assertEqual(seen[3:], ["Bearer configured-key"] * 3)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
