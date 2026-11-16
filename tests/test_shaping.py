"""Unit tests for wevisone_mcp.shaping (run without a GPU)."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wevisone_mcp import shaping  # noqa: E402


class TestValidateRequest(unittest.TestCase):
    def test_normalises_task_and_query(self) -> None:
        self.assertEqual(
            shaping.validate_request("  Detection ", " sofa "), ("detection", "sofa")
        )

    def test_rejects_unknown_task(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            shaping.validate_request("nope", "x")
        self.assertIn("unknown task", str(ctx.exception))

    def test_requires_query_for_query_tasks(self) -> None:
        for task in shaping.QUERY_REQUIRED:
            with self.subTest(task=task):
                with self.assertRaises(ValueError):
                    shaping.validate_request(task, "   ")

    def test_ocr_needs_no_query(self) -> None:
        self.assertEqual(shaping.validate_request("ocr", ""), ("ocr", ""))

    def test_freeform_needs_no_query(self) -> None:
        self.assertEqual(shaping.validate_request("freeform", ""), ("freeform", ""))


class TestRejection(unittest.TestCase):
    def test_none_without_boxes_is_rejected(self) -> None:
        response = "<ref>a purple elephant</ref><box>none</box>"
        self.assertTrue(shaping.is_rejected(response, []))

    def test_boxes_present_is_not_rejected(self) -> None:
        response = "<ref>sofa</ref><box><30><454><964><876></box>"
        self.assertFalse(shaping.is_rejected(response, [[0.03, 0.454, 0.964, 0.876]]))

    def test_empty_response_without_none_is_not_rejected(self) -> None:
        self.assertFalse(shaping.is_rejected("", []))


class TestShapeResult(unittest.TestCase):
    def test_detection_payload(self) -> None:
        payload = shaping.shape_result(
            task="detection",
            query="sofa",
            response="<ref>sofa</ref><box><30><454><964><876></box>",
            boxes=[[0.03, 0.454, 0.964, 0.876]],
            latency_s=3.41,
        )
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["rejected"])
        self.assertEqual(payload["box_count"], 1)
        self.assertEqual(payload["boxes"][0][0], 0.03)
        self.assertIsInstance(payload["latency_s"], float)
        self.assertNotIn("artifacts", payload)

    def test_pixel_payload_lists_artifacts(self) -> None:
        payload = shaping.shape_result(
            task="matting",
            query="sofa",
            response="<ref>sofa</ref><box><30><454><964><876><OBJ></box>",
            boxes=[[0.03, 0.454, 0.964, 0.876]],
            artifacts=[{"index": 0, "url": "/artifacts/" + "a" * 32, "bytes": 1234}],
        )
        self.assertEqual(payload["artifact_count"], 1)
        self.assertEqual(payload["artifacts"][0]["url"], "/artifacts/" + "a" * 32)
        # I-03: no image bytes anywhere in the payload
        import json

        self.assertNotIn("mask_pngs", payload)
        self.assertNotIn("base64", json.dumps(payload))

    def test_payload_is_json_serialisable_and_has_no_image_block(self) -> None:
        import json

        payload = shaping.shape_result(
            task="referring",
            query="x",
            response="<ref>x</ref><box>none</box>",
            boxes=[],
        )
        self.assertTrue(payload["rejected"])
        json.dumps(payload)  # 不抛异常即通过 I-03

    def test_error_payload(self) -> None:
        self.assertEqual(shaping.shape_error("boom"), {"ok": False, "error": "boom"})


class TestTaskEnumDrift(unittest.TestCase):
    def test_tasks_match_upstream(self) -> None:
        """I-01 guard: the local mirror must equal upstream ``prompts.TASKS``."""
        upstream = os.environ.get("WEVISONE_UPSTREAM", "/Volumes/HD-DATA/AITools/WeVisOne-VL")
        if not os.path.isdir(upstream):
            self.skipTest(f"upstream not available at {upstream}")
        sys.path.insert(0, upstream)
        try:
            from wevisone_vl.prompts import TASKS as upstream_tasks
        except Exception as exc:  # pragma: no cover - environment dependent
            self.skipTest(f"cannot import upstream prompts: {exc}")
        finally:
            sys.path.pop(0)
        self.assertEqual(tuple(upstream_tasks), shaping.TASKS)


class ParseBoxesTests(unittest.TestCase):
    """Coordinate fallback: plain answers omit the ``<OBJ>`` marker upstream filters on."""

    def test_detection_form_without_obj(self) -> None:
        boxes = shaping.parse_boxes("<ref>sofa</ref><box><30><454><964><876></box>")
        self.assertEqual(boxes, [[0.03, 0.454, 0.964, 0.876]])

    def test_segmentation_form_with_obj(self) -> None:
        boxes = shaping.parse_boxes("<ref>sofa</ref><box><30><454><964><876><OBJ></box>")
        self.assertEqual(boxes, [[0.03, 0.454, 0.964, 0.876]])

    def test_multiple_boxes(self) -> None:
        text = "<box><10><10><100><100></box> and <box><200><200><300><300></box>"
        self.assertEqual(
            shaping.parse_boxes(text),
            [[0.01, 0.01, 0.1, 0.1], [0.2, 0.2, 0.3, 0.3]],
        )

    def test_truncated_without_closing_tag(self) -> None:
        boxes = shaping.parse_boxes("<box><30><454><964><876>")
        self.assertEqual(boxes, [[0.03, 0.454, 0.964, 0.876]])

    def test_rejects_bad_geometry(self) -> None:
        # reversed, out of range, and too few coordinates are all dropped
        self.assertEqual(shaping.parse_boxes("<box><900><900><100><100></box>"), [])
        self.assertEqual(shaping.parse_boxes("<box><30><454><1964><876></box>"), [])
        self.assertEqual(shaping.parse_boxes("<box><30><454><964></box>"), [])

    def test_truncates_at_end_token(self) -> None:
        text = "<box><10><10><100><100></box><|im_end|><box><900><900><950><950></box>"
        self.assertEqual(len(shaping.parse_boxes(text)), 1)

    def test_no_boxes(self) -> None:
        self.assertEqual(shaping.parse_boxes("none"), [])
        self.assertEqual(shaping.parse_boxes(""), [])

    def test_shape_result_falls_back_when_engine_is_empty(self) -> None:
        payload = shaping.shape_result(
            task="detection",
            query="sofa",
            response="<ref>sofa</ref><box><30><454><964><876></box>",
            boxes=[],
        )
        self.assertEqual(payload["box_count"], 1)
        self.assertEqual(payload["boxes"], [[0.03, 0.454, 0.964, 0.876]])
        self.assertFalse(payload["rejected"])

    def test_shape_result_keeps_engine_boxes(self) -> None:
        # engine results win; the fallback must never overwrite or duplicate them
        payload = shaping.shape_result(
            task="segmentation",
            query="sofa",
            response="<box><30><454><964><876><OBJ></box>",
            boxes=[[0.5, 0.5, 0.6, 0.6]],
        )
        self.assertEqual(payload["boxes"], [[0.5, 0.5, 0.6, 0.6]])
        self.assertEqual(payload["box_count"], 1)

    def test_shape_result_skips_fallback_when_masks_exist(self) -> None:
        # a pixel payload's boxes must stay in step with its artifacts
        payload = shaping.shape_result(
            task="matting",
            query="sofa",
            response="<box><30><454><964><876><OBJ></box>",
            boxes=[],
            artifacts=[{"index": 0, "url": "/artifacts/" + "a" * 32, "bytes": 10}],
        )
        self.assertEqual(payload["box_count"], 0)
        self.assertEqual(payload["artifact_count"], 1)

    def test_rejection_survives_fallback(self) -> None:
        payload = shaping.shape_result(
            task="detection",
            query="unicorn",
            response="none",
            boxes=[],
        )
        self.assertTrue(payload["rejected"])
        self.assertEqual(payload["boxes"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
