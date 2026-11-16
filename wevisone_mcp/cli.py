"""Command-line client for a WeVisOne-VL host.

    python -m wevisone_mcp.cli --image room.jpg --task segmentation --query sofa

Talks to the plain REST surface (`POST /predict`, `GET /artifacts/<id>`), so it
runs on any machine that can reach the GPU host — no torch, no model, no MCP
client. Standard library only.

Exit codes: 0 success, 1 any failure, 2 usage.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_ENDPOINT = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT_S = 180.0


class CliError(Exception):
    """A failure worth reporting as one line plus exit code 1."""


def _headers(token: str) -> dict[str, str]:
    return {"authorization": f"Bearer {token}"} if token else {}


def _request(
    url: str,
    *,
    token: str,
    data: bytes | None = None,
    content_type: str | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> tuple[int, bytes]:
    headers = dict(_headers(token))
    if content_type:
        headers["content-type"] = content_type
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()
    except urllib.error.URLError as error:
        raise CliError(f"cannot reach {url}: {error.reason}") from None


def _json_body(status: int, raw: bytes, url: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        preview = raw[:200].decode("utf-8", "replace")
        raise CliError(f"{url} returned HTTP {status} with non-JSON body: {preview}") from None
    if not isinstance(payload, dict):
        raise CliError(f"{url} returned HTTP {status} with a non-object JSON body")
    return payload


def doctor(args: argparse.Namespace) -> int:
    url = f"{args.endpoint.rstrip('/')}/predict"
    body = json.dumps({"task": "unknown-task", "query": ""}).encode()
    try:
        status, raw = _request(url, token=args.token, data=body, content_type="application/json")
    except CliError as error:
        print(f"unreachable: {error}")
        return 1
    payload = _json_body(status, raw, url)
    # A task-validation rejection proves the host is up and authenticated.
    print(f"endpoint : {args.endpoint}")
    print(f"reachable: yes (HTTP {status})")
    print(f"probe    : {payload.get('error', '')}")
    return 0


def _predict_one(path: Path, args: argparse.Namespace) -> dict[str, Any]:
    try:
        image_bytes = path.read_bytes()
    except OSError as error:
        raise CliError(f"cannot read {path}: {error.strerror or error}") from None
    import base64

    body = json.dumps(
        {
            "image_base64": base64.b64encode(image_bytes).decode("ascii"),
            "task": args.task,
            "query": args.query,
        }
    ).encode()
    url = f"{args.endpoint.rstrip('/')}/predict"
    status, raw = _request(url, token=args.token, data=body, content_type="application/json")
    payload = _json_body(status, raw, url)
    if not payload.get("ok"):
        raise CliError(f"{path.name}: {payload.get('error', f'HTTP {status}')}")
    return payload


def _save_artifacts(payload: dict[str, Any], source: Path, args: argparse.Namespace) -> list[Path]:
    saved: list[Path] = []
    out_dir = Path(args.out) if args.out else None
    for artifact in payload.get("artifacts") or []:
        if not out_dir:
            continue
        out_dir.mkdir(parents=True, exist_ok=True)
        url = f"{args.endpoint.rstrip('/')}{artifact['url']}"
        status, raw = _request(url, token=args.token)
        if status != 200:
            raise CliError(f"downloading {artifact['url']} failed: HTTP {status}")
        suffix = mimetypes.guess_extension(artifact.get("content_type") or "image/png") or ".png"
        target = out_dir / f"{source.stem}.{payload['task']}.{artifact.get('index', len(saved)):03d}{suffix}"
        target.write_bytes(raw)
        saved.append(target)
    return saved


def predict(args: argparse.Namespace) -> int:
    failures = 0
    results: list[dict[str, Any]] = []
    for raw_path in args.image:
        path = Path(raw_path)
        try:
            payload = _predict_one(path, args)
            saved = _save_artifacts(payload, path, args)
        except CliError as error:
            failures += 1
            print(f"error: {error}", file=sys.stderr)
            continue
        record = {
            "image": str(path),
            "task": payload.get("task"),
            "query": payload.get("query"),
            "rejected": payload.get("rejected"),
            "boxes": payload.get("boxes"),
            "box_count": payload.get("box_count"),
            "latency_s": payload.get("latency_s"),
            "artifacts": [str(entry) for entry in saved] or payload.get("artifacts"),
        }
        results.append(record)
        if args.json:
            continue
        state = "rejected" if record["rejected"] else "ok"
        print(f"{path.name}: {state}  boxes={record['box_count']}  {record['latency_s']}s")
        for box in record["boxes"] or []:
            print(f"  box: {[round(float(value), 4) for value in box]}")
        for entry in saved:
            print(f"  saved: {entry}")

    if args.json:
        print(json.dumps(results if len(results) != 1 else results[0], ensure_ascii=False, indent=2))
    if failures:
        print(f"{failures} of {len(args.image)} image(s) failed", file=sys.stderr)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m wevisone_mcp.cli",
        description="Call a WeVisOne-VL host over its REST surface.",
    )
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT, help=f"host base URL (default {DEFAULT_ENDPOINT})")
    parser.add_argument("--token", default="", help="shared token, if the host requires one")
    sub = parser.add_subparsers(dest="command", required=True)

    predict_parser = sub.add_parser("predict", help="run one task per image")
    predict_parser.add_argument("--image", nargs="+", required=True, help="one or more local image paths")
    predict_parser.add_argument("--task", default="detection", help="perception task (default detection)")
    predict_parser.add_argument("--query", default="", help="object description / label / phrase")
    predict_parser.add_argument("--out", default="", help="directory for saved mattes; omit to skip saving")
    predict_parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    predict_parser.set_defaults(handler=predict)

    doctor_parser = sub.add_parser("doctor", help="check that the host answers")
    doctor_parser.set_defaults(handler=doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except CliError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
