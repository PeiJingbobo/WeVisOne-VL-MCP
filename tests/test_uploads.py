"""Unit tests for wevisone_mcp.uploads (stdlib only, no GPU needed)."""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wevisone_mcp import uploads  # noqa: E402


class TestUploadId(unittest.TestCase):
    def test_id_shape(self) -> None:
        value = uploads.new_upload_id()
        self.assertEqual(len(value), 32)
        self.assertTrue(uploads.UPLOAD_ID_RE.match(value))

    def test_ids_are_unique(self) -> None:
        ids = {uploads.new_upload_id() for _ in range(50)}
        self.assertEqual(len(ids), 50)


class TestStoreAndResolve(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.dir = self._dir.name

    def tearDown(self) -> None:
        self._dir.cleanup()

    def test_roundtrip(self) -> None:
        upload_id, size = uploads.store_upload(self.dir, b"hello")
        self.assertEqual(size, 5)
        path = uploads.resolve_upload(self.dir, upload_id)
        self.assertEqual(path.read_bytes(), b"hello")

    def test_rejects_empty_body(self) -> None:
        with self.assertRaises(ValueError):
            uploads.store_upload(self.dir, b"")

    def test_creates_directory(self) -> None:
        nested = Path(self.dir) / "a" / "b"
        upload_id, _ = uploads.store_upload(nested, b"x")
        self.assertTrue((nested / upload_id).is_file())


class TestResolveRejects(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.dir = self._dir.name

    def tearDown(self) -> None:
        self._dir.cleanup()

    def test_rejects_traversal_attempt(self) -> None:
        # I-05 guard: an id is never allowed to carry path syntax.
        for bad in ("../secret", "..", "/etc/passwd", "C:\\Windows\\win.ini", "a" * 31):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    uploads.resolve_upload(self.dir, bad)

    def test_rejects_uppercase_and_symbols(self) -> None:
        for bad in ("A" * 32, "g" * 32, "a" * 31 + "-"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    uploads.resolve_upload(self.dir, bad)

    def test_rejects_unknown_but_wellformed(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            uploads.resolve_upload(self.dir, "b" * 32)
        self.assertIn("unknown upload_id", str(ctx.exception))

    def test_rejects_empty(self) -> None:
        with self.assertRaises(ValueError):
            uploads.resolve_upload(self.dir, "")


class TestSweep(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.dir = self._dir.name

    def tearDown(self) -> None:
        self._dir.cleanup()

    def test_removes_expired_only(self) -> None:
        fresh_id, _ = uploads.store_upload(self.dir, b"fresh")
        stale_id, _ = uploads.store_upload(self.dir, b"stale")
        old = time.time() - 3600
        os.utime(Path(self.dir) / stale_id, (old, old))

        removed = uploads.sweep(self.dir, ttl_s=600)

        self.assertEqual(removed, 1)
        self.assertTrue((Path(self.dir) / fresh_id).is_file())
        self.assertFalse((Path(self.dir) / stale_id).exists())

    def test_leaves_foreign_files_alone(self) -> None:
        foreign = Path(self.dir) / "notes.txt"
        foreign.write_text("keep me", encoding="utf-8")
        old = time.time() - 3600
        os.utime(foreign, (old, old))

        self.assertEqual(uploads.sweep(self.dir, ttl_s=600), 0)
        self.assertTrue(foreign.is_file())

    def test_missing_directory_is_not_an_error(self) -> None:
        self.assertEqual(uploads.sweep(Path(self.dir) / "nope", ttl_s=1), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
