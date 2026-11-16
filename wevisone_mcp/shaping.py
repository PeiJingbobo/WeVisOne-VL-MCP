"""Pure request/result shaping for the WeVisOne-VL MCP server.

Deliberately free of torch, numpy, PIL and the MCP SDK so it can be unit-tested
on a machine without a GPU (see AGENTS.md §3.2).
"""

from __future__ import annotations

import re
from typing import Any, Sequence

# Mirror of upstream ``wevisone_vl.prompts.TASKS``. Upstream is the single
# source; tests/test_shaping.py::test_tasks_match_upstream guards against drift.
TASKS: tuple[str, ...] = (
    "detection",
    "referring",
    "point",
    "count_box",
    "count_point",
    "segmentation",
    "matting",
    "ocr",
    "ocr_grounding",
    "visual_prompt",
    "freeform",
)

# Tasks whose output carries an <OBJ> marker and therefore pixel output.
PIXEL_TASKS: tuple[str, ...] = ("segmentation", "matting")

# Tasks that require a non-empty query.
QUERY_REQUIRED: tuple[str, ...] = (
    "detection",
    "referring",
    "point",
    "count_box",
    "count_point",
    "segmentation",
    "matting",
    "ocr_grounding",
    "visual_prompt",
)


def validate_request(task: str, query: str) -> tuple[str, str]:
    """Normalise and validate one tool request.

    Returns ``(task, query)``. Raises ``ValueError`` with a caller-safe message.
    """
    normalised_task = (task or "").strip().lower()
    if normalised_task not in TASKS:
        raise ValueError(
            f"unknown task {task!r}; choose from {', '.join(TASKS)}"
        )
    normalised_query = (query or "").strip()
    if normalised_task in QUERY_REQUIRED and not normalised_query:
        raise ValueError(f"task {normalised_task!r} requires a non-empty query")
    return normalised_task, normalised_query


def is_rejected(response: str, boxes: Sequence[Sequence[float]]) -> bool:
    """True when the model says the target is absent (upstream emits ``none``)."""
    if boxes:
        return False
    return "none" in (response or "").lower()


# Coordinate grammar mirrored from upstream ``wevisone_vl/engine.py:42-43,57``.
# Upstream is the single source of the *format*; the duplication is deliberate:
# importing upstream would pull in torch, and shaping.py must stay testable
# without a GPU (AGENTS.md §3.2).
_BOX_RE = re.compile(r"<box>(.*?)(?:</box>|$)", re.DOTALL | re.IGNORECASE)
_COORD_RE = re.compile(r"<(\d{1,4})>")


def parse_boxes(text: str) -> list[list[float]]:
    """Extract every normalized xyxy box from a raw model response.

    Upstream's ``parse_seg_boxes`` only keeps boxes carrying an ``<OBJ>`` marker,
    because its callers need pixel output. Plain ``detection`` / ``point`` /
    ``count_box`` answers omit that marker, so forwarding upstream's list left
    ``boxes`` empty even though the answer contained coordinates. This parser
    accepts both forms; callers use it only when the engine returned nothing.
    """
    body_text = (text or "").split("<|im_end|>", 1)[0]
    boxes: list[list[float]] = []
    for body in _BOX_RE.findall(body_text):
        numbers = [int(value) for value in _COORD_RE.findall(body)]
        if len(numbers) < 4:
            continue
        x1, y1, x2, y2 = numbers[-4:]
        if not all(0 <= value <= 1000 for value in (x1, y1, x2, y2)):
            continue
        if x2 <= x1 or y2 <= y1:
            continue
        boxes.append([x1 / 1000.0, y1 / 1000.0, x2 / 1000.0, y2 / 1000.0])
    return boxes


def shape_result(
    *,
    task: str,
    query: str,
    response: str,
    boxes: Sequence[Sequence[float]],
    artifacts: Sequence[dict[str, Any]] | None = None,
    latency_s: float | None = None,
) -> dict[str, Any]:
    """Build the JSON payload returned by every MCP tool.

    ``artifacts`` describes already-written files (an ``/artifacts/<id>`` URL,
    byte count and content type); this module never handles image bytes, so a
    pixel task costs the model a few dozen bytes of JSON instead of a base64 blob.

    When the engine yields no boxes and there are no masks, the response text is
    parsed directly: plain detection answers carry coordinates without the
    ``<OBJ>`` marker upstream filters on (see ``parse_boxes``).
    """
    resolved = [[float(value) for value in box] for box in boxes]
    if not resolved and not artifacts:
        resolved = parse_boxes(response)
    payload: dict[str, Any] = {
        "ok": True,
        "task": task,
        "query": query,
        "rejected": is_rejected(response, resolved),
        "response": response,
        "boxes": resolved,
        "box_count": len(resolved),
    }
    if artifacts:
        payload["artifacts"] = list(artifacts)
        payload["artifact_count"] = len(artifacts)
    if latency_s is not None:
        payload["latency_s"] = round(float(latency_s), 3)
    return payload


def shape_error(message: str) -> dict[str, Any]:
    """Uniform error payload (AGENTS.md §4.3)."""
    return {"ok": False, "error": str(message)}
