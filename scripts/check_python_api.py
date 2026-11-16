"""Verify the in-process Python API on the machine that owns the GPU.

    python scripts/check_python_api.py --image <path>

Prints a doctor summary plus one segmentation through wevisone_mcp.client,
including the shape and value range of the returned PIL masks.
"""

from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--task", default="segmentation")
    parser.add_argument("--query", default="sofa")
    args = parser.parse_args()

    from PIL import Image

    from wevisone_mcp import client

    report = client.doctor()
    print("== doctor ==")
    for key in ("ok", "model_loaded", "device", "decoder_device", "gpu", "tasks"):
        print(f"  {key}: {report.get(key)}")

    with Image.open(args.image) as handle:
        image = handle.convert("RGB")

    print(f"== predict (task={args.task}, query={args.query!r}) ==")
    payload = client.predict(image, task=args.task, query=args.query)
    if not payload.get("ok"):
        print("  FAILED:", payload.get("error"))
        return 1

    print(f"  response   : {payload['response']}")
    print(f"  rejected   : {payload['rejected']}")
    print(f"  box_count  : {payload['box_count']}")
    print(f"  latency_s  : {payload['latency_s']}")
    print(f"  mask_count : {payload['mask_count']}")
    for index, mask in enumerate(payload["masks"]):
        print(f"  mask[{index}]  : {mask.mode} {mask.size} min={min(mask.getdata())} max={max(mask.getdata())}")

    # bytes input must behave identically to a PIL image
    with open(args.image, "rb") as handle:
        raw = handle.read()
    again = client.predict(raw, task=args.task, query=args.query)
    same = again.get("boxes") == payload.get("boxes")
    print(f"  bytes-input parity: {'OK' if same else 'MISMATCH'}")

    # validation still passes here, so this exercises the image decoder itself
    bad = client.predict(b"not an image", task="segmentation", query="sofa")
    print(f"  bad-image envelope: {bad}")
    return 0 if same and bad.get("ok") is False else 1


if __name__ == "__main__":
    raise SystemExit(main())
