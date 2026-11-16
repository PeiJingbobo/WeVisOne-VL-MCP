"""Remote-mode tests: the MCP server forwards to a GPU host instead of loading a model.

Skipped when the ``mcp`` package is absent, since importing the server requires it.
``WEVISONE_REMOTE_URL`` is module-level state, so each test re-imports the module.
"""

from __future__ import annotations

import importlib
import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from wevisone_mcp import server as server_module

    HAVE_SERVER = True
except Exception as exc:  # pragma: no cover - environment dependent
    HAVE_SERVER = False
    IMPORT_ERROR = str(exc)

FORWARDED: list[dict] = []


class RemoteHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep output clean
        pass

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("content-length", "0"))
        raw = self.rfile.read(length)
        if self.path == "/upload":
            self._send(200, {"ok": True, "upload_id": "a" * 32, "bytes": len(raw), "expires_in_s": 600})
            return
        request = json.loads(raw or b"{}")
        FORWARDED.append(
            {"path": self.path, "body": request, "auth": self.headers.get("authorization", "")}
        )
        if request.get("task") == "boom":
            self._send(422, {"ok": False, "error": "ValueError: boom"})
            return
        self._send(
            200,
            {
                "ok": True,
                "task": request.get("task"),
                "query": request.get("query"),
                "rejected": False,
                "response": "<box><10><10><100><100></box>",
                "boxes": [[0.01, 0.01, 0.1, 0.1]],
                "box_count": 1,
                "latency_s": 1.5,
            },
        )

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/artifacts/"):
            body = b"\x89PNG\r\n\x1a\nREMOTE"
            self.send_response(200)
            self.send_header("content-type", "image/png")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._send(404, {"ok": False, "error": "not found"})


@unittest.skipUnless(HAVE_SERVER, f"mcp package unavailable: {IMPORT_ERROR if not HAVE_SERVER else ''}")
class RemoteModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.remote = ThreadingHTTPServer(("127.0.0.1", 0), RemoteHandler)
        threading.Thread(target=cls.remote.serve_forever, daemon=True).start()
        cls.remote_url = f"http://127.0.0.1:{cls.remote.server_address[1]}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.remote.shutdown()
        cls.remote.server_close()

    def setUp(self) -> None:
        FORWARDED.clear()
        import os

        self._saved = {k: os.environ.get(k) for k in ("WEVISONE_REMOTE_URL", "WEVISONE_REMOTE_TOKEN")}
        os.environ["WEVISONE_REMOTE_URL"] = self.remote_url
        os.environ["WEVISONE_REMOTE_TOKEN"] = "remote-secret"
        self.server = importlib.reload(server_module)
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        import os

        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        importlib.reload(server_module)

    def test_mode_is_remote(self) -> None:
        doctor = json.loads(self.server.wevisone_doctor())
        self.assertEqual(doctor["mode"], "remote")
        self.assertEqual(doctor["remote_url"], self.remote_url)

    def test_run_predict_forwards_and_returns_remote_payload(self) -> None:
        payload = self.server.run_predict(task="detection", query="sofa", upload_id="a" * 32)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["boxes"], [[0.01, 0.01, 0.1, 0.1]])
        self.assertEqual(len(FORWARDED), 1)
        self.assertEqual(FORWARDED[0]["path"], "/predict")
        self.assertEqual(FORWARDED[0]["body"]["upload_id"], "a" * 32)
        self.assertEqual(FORWARDED[0]["auth"], "Bearer remote-secret")

    def test_remote_error_payload_is_passed_through(self) -> None:
        payload = self.server.run_predict(task="boom", query="x", upload_id="a" * 32)
        self.assertFalse(payload["ok"])
        self.assertIn("boom", payload["error"])

    def test_local_validation_still_runs_first(self) -> None:
        payload = self.server.run_predict(task="nope", query="x")
        self.assertFalse(payload["ok"])
        self.assertEqual(FORWARDED, [])  # never leaves the process

    def test_remote_request_fetches_artifacts(self) -> None:
        status, raw = self.server._remote_request("/artifacts/" + "b" * 32)
        self.assertEqual(status, 200)
        self.assertTrue(raw.startswith(b"\x89PNG"))

    def test_unreachable_remote_reports_clearly(self) -> None:
        import os

        os.environ["WEVISONE_REMOTE_URL"] = "http://127.0.0.1:1"
        reloaded = importlib.reload(server_module)
        payload = reloaded.run_predict(task="detection", query="sofa", upload_id="a" * 32)
        self.assertFalse(payload["ok"])
        self.assertIn("unreachable", payload["error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
