"""End-to-end tests for the CLI against a real (local) HTTP server.

The CLI is standard-library only, so these run on any machine — the fake host
below answers exactly like the real REST surface does.
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wevisone_mcp import cli  # noqa: E402

PNG_BYTES = b"\x89PNG\r\n\x1a\nFAKE-MATTE"

CANNED_OK = {
    "ok": True,
    "task": "segmentation",
    "query": "sofa",
    "rejected": False,
    "response": "<ref>sofa</ref><box><30><454><964><876><OBJ></box>",
    "boxes": [[0.03, 0.454, 0.964, 0.876]],
    "box_count": 1,
    "artifacts": [{"index": 0, "url": "/artifacts/" + "a" * 32, "bytes": len(PNG_BYTES), "content_type": "image/png"}],
    "artifact_count": 1,
    "latency_s": 3.21,
}

CANNED_REJECTED = {
    "ok": True,
    "task": "segmentation",
    "query": "unicorn",
    "rejected": True,
    "response": "none",
    "boxes": [],
    "box_count": 0,
    "latency_s": 1.03,
}


class Handler(BaseHTTPRequestHandler):
    mode = "ok"
    seen_tokens: list[str] = []

    def log_message(self, *args):  # keep test output clean
        pass

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/artifacts/"):
            self.send_response(200)
            self.send_header("content-type", "image/png")
            self.send_header("content-length", str(len(PNG_BYTES)))
            self.end_headers()
            self.wfile.write(PNG_BYTES)
            return
        self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("content-length", "0"))
        request = json.loads(self.rfile.read(length) or b"{}")
        Handler.seen_tokens.append(self.headers.get("authorization", ""))
        if self.path == "/artifacts/boom":
            self._send(500, {"ok": False, "error": "boom"})
            return
        if request.get("task") == "unknown-task":
            self._send(422, {"ok": False, "error": "ValueError: unknown task 'unknown-task'"})
            return
        if Handler.mode == "rejected":
            self._send(200, CANNED_REJECTED)
            return
        if Handler.mode == "server-error":
            self._send(422, {"ok": False, "error": "ValueError: boom"})
            return
        self._send(200, CANNED_OK)


class CliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.endpoint = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self) -> None:
        Handler.mode = "ok"
        Handler.seen_tokens.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.image = self.dir / "room.jpg"
        self.image.write_bytes(b"\xff\xd8fake-jpeg")

    def run_cli(self, *argv: str) -> tuple[int, str, str]:
        import contextlib
        import io

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_doctor_reports_reachable(self) -> None:
        code, out, _ = self.run_cli("--endpoint", self.endpoint, "doctor")
        self.assertEqual(code, 0)
        self.assertIn("reachable: yes", out)
        self.assertIn("unknown task", out)

    def test_doctor_unreachable(self) -> None:
        code, out, _ = self.run_cli("--endpoint", "http://127.0.0.1:1", "doctor")
        self.assertEqual(code, 1)
        self.assertIn("unreachable", out)

    def test_predict_prints_boxes_and_saves_mask(self) -> None:
        out_dir = self.dir / "masks"
        code, out, _ = self.run_cli(
            "--endpoint", self.endpoint, "predict",
            "--image", str(self.image), "--task", "segmentation", "--query", "sofa",
            "--out", str(out_dir),
        )
        self.assertEqual(code, 0)
        self.assertIn("boxes=1", out)
        saved = list(out_dir.glob("room.segmentation.000.png"))
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].read_bytes(), PNG_BYTES)

    def test_predict_without_out_skips_saving(self) -> None:
        before = set(self.dir.iterdir())
        code, out, _ = self.run_cli(
            "--endpoint", self.endpoint, "predict",
            "--image", str(self.image), "--task", "segmentation", "--query", "sofa",
        )
        self.assertEqual(code, 0)
        self.assertNotIn("saved:", out)
        self.assertEqual(set(self.dir.iterdir()), before)

    def test_rejected_target_is_not_a_failure(self) -> None:
        Handler.mode = "rejected"
        code, out, _ = self.run_cli(
            "--endpoint", self.endpoint, "predict",
            "--image", str(self.image), "--task", "segmentation", "--query", "unicorn",
        )
        self.assertEqual(code, 0)
        self.assertIn("rejected", out)

    def test_server_error_exits_nonzero(self) -> None:
        Handler.mode = "server-error"
        code, out, err = self.run_cli(
            "--endpoint", self.endpoint, "predict",
            "--image", str(self.image), "--task", "segmentation", "--query", "sofa",
        )
        self.assertEqual(code, 1)
        self.assertIn("boom", err)

    def test_missing_image_exits_nonzero(self) -> None:
        code, _, err = self.run_cli(
            "--endpoint", self.endpoint, "predict",
            "--image", str(self.dir / "nope.jpg"), "--query", "sofa",
        )
        self.assertEqual(code, 1)
        self.assertIn("cannot read", err)

    def test_batch_continues_after_one_failure(self) -> None:
        second = self.dir / "second.jpg"
        second.write_bytes(b"\xff\xd8fake-jpeg-2")
        code, out, err = self.run_cli(
            "--endpoint", self.endpoint, "predict",
            "--image", str(self.dir / "nope.jpg"), str(second), "--query", "sofa",
        )
        self.assertEqual(code, 1)
        self.assertIn("cannot read", err)
        self.assertIn("second.jpg:", out)  # the good image still ran
        self.assertIn("1 of 2 image(s) failed", err)

    def test_json_output_is_parseable(self) -> None:
        code, out, _ = self.run_cli(
            "--endpoint", self.endpoint, "predict",
            "--image", str(self.image), "--task", "segmentation", "--query", "sofa", "--json",
        )
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["box_count"], 1)
        self.assertEqual(payload["boxes"], CANNED_OK["boxes"])
        self.assertFalse(payload["rejected"])

    def test_token_is_sent_as_bearer(self) -> None:
        code, _, _ = self.run_cli(
            "--endpoint", self.endpoint, "--token", "s3cret", "predict",
            "--image", str(self.image), "--query", "sofa",
        )
        self.assertEqual(code, 0)
        self.assertTrue(Handler.seen_tokens)
        self.assertEqual(Handler.seen_tokens[-1], "Bearer s3cret")

    def test_usage_error_on_unknown_subcommand(self) -> None:
        with self.assertRaises(SystemExit) as caught:
            cli.build_parser().parse_args(["nonsense"])
        self.assertEqual(caught.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
