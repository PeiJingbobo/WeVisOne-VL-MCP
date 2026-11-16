"""WeVisOne-VL MCP server: vision perception tools over Streamable HTTP.

Run on the machine that owns the GPU:

    python -m wevisone_mcp.server

Every setting is an environment variable with a working default for the
development host (`dell-16-plus`). See README.md for the full table.
"""

from __future__ import annotations

import base64
import io
import json
import os
import sys
import threading
import time
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from . import shaping, uploads

# ---------------------------------------------------------------- settings ---

UPSTREAM = os.environ.get("WEVISONE_UPSTREAM", r"C:\Users\PeiJingbo\AITools\WeVisOne-VL")
MODEL = os.environ.get(
    "WEVISONE_MODEL", r"C:\Users\PeiJingbo\AITools\models\WeVisOne-VL-2B"
)
DEVICE = os.environ.get("WEVISONE_DEVICE", "cuda")
DECODER_DEVICE = os.environ.get("WEVISONE_DECODER_DEVICE", "cpu")
DTYPE = os.environ.get("WEVISONE_DTYPE", "float16")
MAX_PIXELS = int(os.environ.get("WEVISONE_MAX_PIXELS", str(512 * 32 * 32)))
MAX_NEW_TOKENS = int(os.environ.get("WEVISONE_MAX_NEW_TOKENS", "512"))
HOST = os.environ.get("WEVISONE_MCP_HOST", "127.0.0.1")
PORT = int(os.environ.get("WEVISONE_MCP_PORT", "8000"))
def _load_token() -> str:
    """Read the shared token from the environment, else from a file.

    A file keeps the secret out of process listings, scheduled-task arguments and
    profile configs — the three places it historically leaked. The environment
    wins so a one-off override stays possible.
    """
    from_env = os.environ.get("WEVISONE_MCP_TOKEN", "").strip()
    if from_env:
        return from_env
    token_file = os.environ.get("WEVISONE_MCP_TOKEN_FILE", "").strip()
    if not token_file:
        return ""
    try:
        with open(token_file, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError as exc:
        print(f"cannot read WEVISONE_MCP_TOKEN_FILE={token_file}: {exc}", file=sys.stderr)
        return ""


TOKEN = _load_token()
# 32 MiB: a base64-encoded phone photo fits, the SDK default of 4 MiB does not.
MAX_BODY = int(os.environ.get("WEVISONE_MCP_MAX_BODY", str(32 * 1024 * 1024)))
UPLOAD_DIR = os.environ.get(
    "WEVISONE_UPLOAD_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads"),
)
UPLOAD_TTL_S = int(os.environ.get("WEVISONE_UPLOAD_TTL_S", "600"))
UPLOAD_PATH = "/upload"
ARTIFACT_DIR = os.environ.get(
    "WEVISONE_ARTIFACT_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "artifacts"),
)
ARTIFACT_TTL_S = int(os.environ.get("WEVISONE_ARTIFACT_TTL_S", "600"))
ARTIFACT_PATH = "/artifacts"
PREDICT_PATH = "/predict"

# Remote mode: forward everything to a GPU host that runs the model instead of
# loading it here. Same process and same endpoints, so clients cannot tell the
# difference; the model package (torch) is never imported in this mode.
REMOTE_URL = os.environ.get("WEVISONE_REMOTE_URL", "").rstrip("/")
REMOTE_TOKEN = os.environ.get("WEVISONE_REMOTE_TOKEN", "") or TOKEN
REMOTE_TIMEOUT_S = float(os.environ.get("WEVISONE_REMOTE_TIMEOUT_S", "180"))


def _remote_request(path: str, *, data: bytes | None = None, content_type: str | None = None) -> tuple[int, bytes]:
    """Call the same endpoint on the GPU host and return its status and body."""
    import urllib.error
    import urllib.request

    headers = {"authorization": f"Bearer {REMOTE_TOKEN}"} if REMOTE_TOKEN else {}
    if content_type:
        headers["content-type"] = content_type
    request = urllib.request.Request(
        f"{REMOTE_URL}{path}",
        data=data,
        headers=headers,
        method="POST" if data is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=REMOTE_TIMEOUT_S) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()
    except urllib.error.URLError as error:
        raise RuntimeError(f"remote host {REMOTE_URL} unreachable: {error.reason}") from None

if UPSTREAM not in sys.path:
    sys.path.insert(0, UPSTREAM)

# ------------------------------------------------------------------ engine ---

_engine: Any = None
_load_lock = threading.Lock()
# One GPU / one model: serialise inference so concurrent calls cannot OOM.
_infer_lock = threading.Lock()


def get_engine() -> Any:
    """Load the model once per process (business rule I-02)."""
    global _engine
    if _engine is None:
        with _load_lock:
            if _engine is None:
                from wevisone_vl import WeVisOneVL

                _engine = WeVisOneVL(
                    MODEL,
                    backend="transformers",
                    device=DEVICE,
                    decoder_device=DECODER_DEVICE,
                    dtype=DTYPE,
                    max_pixels=MAX_PIXELS,
                )
    return _engine


# ------------------------------------------------------------------- utils ---


def _decode_image(image_base64: str) -> Any:
    """Decode a base64 image payload; raises ValueError with a safe message."""
    from PIL import Image

    payload = (image_base64 or "").strip()
    if payload.startswith("data:") and "," in payload:
        payload = payload.split(",", 1)[1]  # tolerate data URLs
    try:
        raw = base64.b64decode(payload, validate=True)
    except Exception as exc:
        raise ValueError(f"image_base64 is not valid base64: {exc}") from None
    try:
        return Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception as exc:
        raise ValueError(f"image_base64 is not a decodable image: {exc}") from None


def _load_image(image_base64: str, upload_id: str) -> Any:
    """Resolve exactly one image source: inline base64 or a server-issued id."""
    from PIL import Image

    has_b64 = bool((image_base64 or "").strip())
    has_id = bool((upload_id or "").strip())
    if has_b64 and has_id:
        raise ValueError("provide either image_base64 or upload_id, not both")
    if not has_b64 and not has_id:
        raise ValueError("provide image_base64 or upload_id")
    if has_id:
        from pathlib import Path

        path = uploads.resolve_upload(UPLOAD_DIR, upload_id)
        try:
            return Image.open(path).convert("RGB")
        except Exception as exc:
            raise ValueError(f"upload {upload_id} is not a decodable image: {exc}") from None
    return _decode_image(image_base64)


def _mask_png_bytes(mask: Any) -> bytes:
    """Render one float alpha map (0-1) as PNG bytes."""
    import numpy as np
    from PIL import Image

    array = (np.clip(mask, 0.0, 1.0) * 255).astype("uint8")
    buffer = io.BytesIO()
    Image.fromarray(array, mode="L").save(buffer, format="PNG")
    return buffer.getvalue()


def _mask_stats(mask: Any) -> dict[str, Any]:
    """Summarise one matte so callers can judge it without looking at an image.

    Opening the PNG costs a full image in the caller's context; these numbers cost a
    few dozen bytes and catch every failure that matters (empty matte, wrong object,
    clipped subject, weak alpha).
    """
    import numpy as np

    alpha = np.clip(np.asarray(mask, dtype=np.float32), 0.0, 1.0)
    coverage = float((alpha >= 0.05).mean())
    stats: dict[str, Any] = {
        "alpha_min": round(float(alpha.min()), 3),
        "alpha_max": round(float(alpha.max()), 3),
        "alpha_mean": round(float(alpha.mean()), 4),
        "coverage": round(coverage, 4),
        "size": [int(alpha.shape[1]), int(alpha.shape[0])],
        "bbox": None,
    }
    rows, cols = np.nonzero(alpha >= 0.05)
    if cols.size:
        stats["bbox"] = [int(cols.min()), int(rows.min()), int(cols.max()), int(rows.max())]
        stats["touches_edge"] = bool(
            cols.min() == 0 or rows.min() == 0
            or cols.max() == alpha.shape[1] - 1 or rows.max() == alpha.shape[0] - 1
        )
    else:
        stats["touches_edge"] = False

    # An explicit verdict, so a caller never has to open the PNG to decide whether the
    # matte is usable. Empty problems == ship it.
    problems = []
    if not cols.size:
        problems.append("empty mask")
    else:
        if coverage < 0.01:
            problems.append("coverage below 1%")
        if coverage > 0.95:
            problems.append("mask covers almost the whole frame")
        if not stats["touches_edge"] and float(alpha.max()) < 0.9:
            problems.append("alpha never reaches 0.9")
    stats["verdict"] = "ok" if not problems else "suspect"
    if problems:
        stats["problems"] = problems
    return stats


def _publish_artifacts(masks: Any) -> list[dict[str, Any]]:
    """Write each mask under an unguessable id and describe it for the caller.

    Reuses the upload blob store: same "server-issued id, never a client path"
    contract, different directory (see I-05). The caller gets a relative URL, so
    the mask never enters the model context.
    """
    artifacts: list[dict[str, Any]] = []
    for index, mask in enumerate(masks or []):
        png_bytes = _mask_png_bytes(mask)
        artifact_id, size = uploads.store_upload(ARTIFACT_DIR, png_bytes)
        artifacts.append(
            {
                "index": index,
                "url": f"{ARTIFACT_PATH}/{artifact_id}",
                "bytes": size,
                "content_type": "image/png",
                "stats": _mask_stats(mask),
            }
        )
    if artifacts:
        uploads.sweep(ARTIFACT_DIR, ARTIFACT_TTL_S)
    return artifacts


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


# ------------------------------------------------------------------ server ---

server = MCPServer(
    name="wevisone-vl",
    version="0.1.0",
    instructions=(
        "Visual perception for a single image: open-vocabulary detection, referring "
        "localisation, counting, pointing, OCR, referring segmentation and alpha "
        "matting. Pass the image as base64. Coordinates are normalised to 0-1. "
        "A target the model cannot find is reported as rejected=true instead of a "
        "made-up box."
    ),
)


def run_predict(
    *,
    upload_id: str = "",
    image_base64: str = "",
    task: str = "detection",
    query: str = "",
    max_new_tokens: int = 0,
) -> dict[str, Any]:
    """Shared implementation for the MCP tool and ``POST /predict``.

    In remote mode the work happens on the GPU host: this process only forwards.
    """
    try:
        task, query = shaping.validate_request(task, query)
        if REMOTE_URL:
            payload = {key: value for key, value in {
                "upload_id": upload_id,
                "image_base64": image_base64,
                "task": task,
                "query": query,
                "max_new_tokens": max_new_tokens,
            }.items() if value not in ("", 0, None)}
            status, raw = _remote_request(
                PREDICT_PATH,
                data=json.dumps(payload).encode(),
                content_type="application/json",
            )
            answer = json.loads(raw.decode("utf-8") or "{}")
            if not isinstance(answer, dict):
                return shaping.shape_error(f"remote host returned a non-object body (HTTP {status})")
            return answer
        image = _load_image(image_base64, upload_id)
        engine = get_engine()
        started = time.perf_counter()
        with _infer_lock:
            result = engine.predict(
                image,
                task=task,
                query=query,
                decode_matting=task in shaping.PIXEL_TASKS,
                max_new_tokens=max_new_tokens or MAX_NEW_TOKENS,
            )
        elapsed = time.perf_counter() - started
        artifacts = _publish_artifacts(result.masks)
        return shaping.shape_result(
            task=task,
            query=query,
            response=result.response,
            boxes=result.boxes,
            artifacts=artifacts,
            latency_s=elapsed,
        )
    except Exception as exc:  # boundary: translate to a caller-safe payload
        return shaping.shape_error(f"{type(exc).__name__}: {exc}")


@server.tool(
    description=(
        "Run one WeVisOne-VL perception task on an image identified by upload_id. "
        "Upload bytes first with POST /upload to get the id; image_base64 is also "
        "accepted for small images. "
        f"task is one of: {', '.join(shaping.TASKS)}. "
        "Returns JSON with boxes (normalised xyxy), a rejected flag, the raw model "
        "response, and for segmentation/matting one artifact per box: a relative "
        "/artifacts/<id> URL to download the PNG alpha matte."
    )
)
def wevisone_predict(
    upload_id: str = "",
    image_base64: str = "",
    task: str = "detection",
    query: str = "",
    max_new_tokens: int = 0,
) -> str:
    return _json(
        run_predict(
            upload_id=upload_id,
            image_base64=image_base64,
            task=task,
            query=query,
            max_new_tokens=max_new_tokens,
        )
    )


@server.tool(
    description=(
        "Report server readiness: upstream path, model path, device settings, GPU "
        "status and whether the model is already resident. Call this first when a "
        "prediction fails."
    )
)
def wevisone_doctor() -> str:
    info: dict[str, Any] = {
        "ok": True,
        "upstream": UPSTREAM,
        "upstream_exists": os.path.isdir(UPSTREAM),
        "model": MODEL,
        "model_exists": os.path.isdir(MODEL),
        "device": DEVICE,
        "decoder_device": DECODER_DEVICE,
        "dtype": DTYPE,
        "max_pixels": MAX_PIXELS,
        "max_new_tokens": MAX_NEW_TOKENS,
        "tasks": list(shaping.TASKS),
        "model_loaded": _engine is not None,
        "bind": f"{HOST}:{PORT}",
        "token_required": bool(TOKEN),
        "mode": "remote" if REMOTE_URL else "local",
        "remote_url": REMOTE_URL or None,
        "upload_path": UPLOAD_PATH,
        "upload_dir": UPLOAD_DIR,
        "upload_ttl_s": UPLOAD_TTL_S,
        "artifact_path": ARTIFACT_PATH,
        "artifact_dir": ARTIFACT_DIR,
        "artifact_ttl_s": ARTIFACT_TTL_S,
    }
    try:
        import torch

        info["torch"] = torch.__version__
        info["cuda_available"] = bool(torch.cuda.is_available())
        if torch.cuda.is_available():
            info["gpu"] = torch.cuda.get_device_name(0)
    except Exception as exc:  # torch absent is a reportable state, not a crash
        info["torch"] = f"unavailable: {exc}"
    return _json(info)


# -------------------------------------------------------------------- boot ---


def build_app() -> Any:
    """ASGI app: MCP streamable HTTP plus an optional shared-token gate."""
    app = server.streamable_http_app(
        host=HOST,
        max_request_body_size=MAX_BODY,
        # LAN clients send their own Host header; the DNS-rebinding allowlist is
        # left disabled because a bearer token guards non-loopback binds.
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        ),
    )
    expected = f"Bearer {TOKEN}".encode() if TOKEN else None

    async def send_json(send: Any, status: int, payload: dict[str, Any]) -> None:
        body = _json(payload).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def handle_upload(receive: Any, send: Any) -> None:
        chunks = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                continue
            chunks.extend(message.get("body", b""))
            if len(chunks) > MAX_BODY:
                await send_json(send, 413, {"ok": False, "error": "payload too large"})
                return
            if not message.get("more_body", False):
                break
        try:
            upload_id, size = uploads.store_upload(UPLOAD_DIR, bytes(chunks))
        except ValueError as exc:
            await send_json(send, 400, {"ok": False, "error": str(exc)})
            return
        uploads.sweep(UPLOAD_DIR, UPLOAD_TTL_S)
        await send_json(
            send,
            200,
            {
                "ok": True,
                "upload_id": upload_id,
                "bytes": size,
                "expires_in_s": UPLOAD_TTL_S,
            },
        )

    async def read_body(receive: Any) -> bytes:
        chunks = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return b""
            if message["type"] != "http.request":
                continue
            chunks.extend(message.get("body", b""))
            if len(chunks) > MAX_BODY:
                return b""  # caller reports 413 via the length check it keeps
            if not message.get("more_body", False):
                break
        return bytes(chunks)

    async def send_raw_json(send: Any, status: int, raw: bytes) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": int(status),
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(raw)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": raw})

    async def handle_predict(receive: Any, send: Any) -> None:
        import asyncio
        import json as _jsonlib

        raw = await read_body(receive)
        if len(raw) > MAX_BODY:
            await send_json(send, 413, {"ok": False, "error": "payload too large"})
            return
        try:
            request = _jsonlib.loads(raw or b"{}")
        except Exception as exc:
            await send_json(send, 400, {"ok": False, "error": f"invalid JSON body: {exc}"})
            return
        if not isinstance(request, dict):
            await send_json(send, 400, {"ok": False, "error": "body must be a JSON object"})
            return
        allowed = {"upload_id", "image_base64", "task", "query", "max_new_tokens"}
        unexpected = sorted(set(request) - allowed)
        if unexpected:
            await send_json(
                send,
                400,
                {"ok": False, "error": f"unexpected fields: {', '.join(unexpected)}"},
            )
            return
        kwargs = {key: request[key] for key in allowed if key in request}
        try:
            kwargs["max_new_tokens"] = int(kwargs.get("max_new_tokens", 0) or 0)
        except (TypeError, ValueError):
            await send_json(send, 400, {"ok": False, "error": "max_new_tokens must be an integer"})
            return
        # the model call blocks; keep the event loop free for other requests
        result = await asyncio.to_thread(run_predict, **kwargs)
        await send_json(send, 200 if result.get("ok") else 422, result)

    async def router(scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await app(scope, receive, send)
            return
        if expected is not None:
            headers = dict(scope.get("headers") or [])
            if headers.get(b"authorization", b"") != expected:
                await send_json(send, 401, {"ok": False, "error": "unauthorized"})
                return
        path = scope.get("path", "")
        if path == UPLOAD_PATH:
            if scope.get("method", "").upper() == "POST":
                if REMOTE_URL:
                    body = await read_body(receive)
                    if len(body) > MAX_BODY:
                        await send_json(send, 413, {"ok": False, "error": "payload too large"})
                        return
                    try:
                        status, raw = _remote_request(
                            UPLOAD_PATH, data=body, content_type="application/octet-stream"
                        )
                    except RuntimeError as exc:
                        await send_json(send, 502, {"ok": False, "error": str(exc)})
                        return
                    await send_raw_json(send, status, raw)
                    return
                await handle_upload(receive, send)
            else:
                await send_json(send, 405, {"ok": False, "error": "use POST"})
            return
        if path == PREDICT_PATH:
            if scope.get("method", "").upper() != "POST":
                await send_json(send, 405, {"ok": False, "error": "use POST"})
                return
            await handle_predict(receive, send)
            return
        if path.startswith(ARTIFACT_PATH + "/"):
            if scope.get("method", "").upper() != "GET":
                await send_json(send, 405, {"ok": False, "error": "use GET"})
                return
            if REMOTE_URL:
                try:
                    status, raw = _remote_request(path)
                except RuntimeError as exc:
                    await send_json(send, 502, {"ok": False, "error": str(exc)})
                    return
                if status != 200:
                    await send_json(send, status, {"ok": False, "error": "remote artifact unavailable"})
                    return
                await send(
                    {
                        "type": "http.response.start",
                        "status": 200,
                        "headers": [
                            (b"content-type", b"image/png"),
                            (b"content-length", str(len(raw)).encode()),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": raw})
                return
            try:
                artifact = uploads.resolve_upload(ARTIFACT_DIR, path[len(ARTIFACT_PATH) + 1 :])
            except ValueError as exc:
                await send_json(send, 404, {"ok": False, "error": str(exc)})
                return
            data = artifact.read_bytes()
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [
                        (b"content-type", b"image/png"),
                        (b"content-length", str(len(data)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": data})
            return
        await app(scope, receive, send)

    return router


def main() -> int:
    if HOST not in ("127.0.0.1", "localhost", "::1") and not TOKEN:
        print(
            "refusing to bind a non-loopback address without WEVISONE_MCP_TOKEN",
            file=sys.stderr,
        )
        return 2

    # Cold-starting inside the first tool call takes ~7 s and can outlive the
    # client's SSE stream. Load up front unless explicitly disabled.
    # Remote mode never loads a model here: the GPU host owns it.
    if REMOTE_URL:
        print(f"remote mode: forwarding to {REMOTE_URL} (no local model)")
    elif os.environ.get("WEVISONE_PRELOAD", "1") != "0":
        try:
            get_engine()
            print("model preloaded")
        except Exception as exc:  # report and serve anyway; doctor shows the state
            print(f"model preload failed: {type(exc).__name__}: {exc}", file=sys.stderr)

    import uvicorn

    role = f"remote -> {REMOTE_URL}" if REMOTE_URL else "local model"
    print(f"wevisone-vl MCP on http://{HOST}:{PORT}/mcp (token={'on' if TOKEN else 'off'}, {role})")
    uvicorn.run(build_app(), host=HOST, port=PORT, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
