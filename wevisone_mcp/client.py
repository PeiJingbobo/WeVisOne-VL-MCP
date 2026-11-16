"""In-process Python API: call the model directly, no MCP and no HTTP.

    from wevisone_mcp import client
    payload = client.predict(Image.open("photo.jpg"), task="segmentation", query="sofa")
    payload["masks"]  # list[PIL.Image], one continuous-alpha matte per box

Differences from the MCP tool, deliberately:

* input is a ``PIL.Image`` (or raw image bytes) — the caller opens the file, so
  I-05 ("never accept a client-supplied path") needs no exception;
* masks come back as image objects, not ``/artifacts/<id>`` URLs, because an
  in-process caller can hold the bytes directly.

Importing this module pulls in torch and the upstream package (a few seconds).
"""

from __future__ import annotations

import io
import time
from typing import Any

from . import shaping, server


def _as_image(image: Any) -> Any:
    """Accept a PIL image or raw encoded bytes; return an RGB PIL image."""
    from PIL import Image

    if isinstance(image, Image.Image):
        return image.convert("RGB")
    if isinstance(image, (bytes, bytearray, memoryview)):
        try:
            return Image.open(io.BytesIO(bytes(image))).convert("RGB")
        except Exception as exc:
            raise ValueError(f"bytes are not a decodable image: {exc}") from None
    raise TypeError(f"expected PIL.Image or bytes, got {type(image).__name__}")


def predict(
    image: Any,
    *,
    task: str = "detection",
    query: str = "",
    max_new_tokens: int | None = None,
    decode_matting: bool | None = None,
) -> dict[str, Any]:
    """Run one perception task in this process.

    Returns the same scalar fields as the MCP tool plus ``masks`` (list of PIL
    images) and ``mask_count``. On failure returns ``{"ok": False, "error": ...}``
    rather than raising, mirroring the tool contract.
    """
    try:
        task, query = shaping.validate_request(task, query)
        pil_image = _as_image(image)
        engine = server.get_engine()
        wants_masks = task in shaping.PIXEL_TASKS if decode_matting is None else bool(decode_matting)

        started = time.perf_counter()
        with server._infer_lock:
            result = engine.predict(
                pil_image,
                task=task,
                query=query,
                decode_matting=wants_masks,
                max_new_tokens=max_new_tokens or server.MAX_NEW_TOKENS,
            )
        elapsed = time.perf_counter() - started

        payload = shaping.shape_result(
            task=task,
            query=query,
            response=result.response,
            boxes=result.boxes,
            latency_s=elapsed,
        )
        payload["masks"] = _render_masks(result.masks)
        payload["mask_count"] = len(payload["masks"])
        return payload
    except Exception as exc:  # boundary: same envelope as the MCP tool
        return shaping.shape_error(f"{type(exc).__name__}: {exc}")


def _render_masks(masks: Any) -> list[Any]:
    """Turn float alpha maps into 8-bit grayscale PIL images."""
    import numpy as np
    from PIL import Image

    rendered = []
    for mask in masks or []:
        array = (np.clip(mask, 0.0, 1.0) * 255).astype("uint8")
        rendered.append(Image.fromarray(array, mode="L"))
    return rendered


def doctor() -> dict[str, Any]:
    """Same readiness report the MCP tool exposes, as a dict."""
    import json

    return json.loads(server.wevisone_doctor())
