"""End-to-end MCP self-check for a running wevisone-vl server.

    python client_check.py --url http://127.0.0.1:8000/mcp --image demo.jpg

Prints the discovered tool list plus one doctor and one predict response.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sys


def _text_of(result: object) -> str:
    chunks = []
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if text is not None:
            chunks.append(text)
    return "\n".join(chunks) if chunks else json.dumps({"raw": str(result)})


async def run(args: argparse.Namespace) -> int:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    http_client = None
    if args.token:
        import httpx2

        http_client = httpx2.AsyncClient(headers={"Authorization": f"Bearer {args.token}"})

    try:
        async with streamable_http_client(args.url, http_client=http_client) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                tools = await session.list_tools()
                names = [tool.name for tool in tools.tools]
                print("== tools ==")
                for tool in tools.tools:
                    print(f"  {tool.name}: {(tool.description or '').splitlines()[0][:90]}")
                if "wevisone_doctor" not in names or "wevisone_predict" not in names:
                    print("!! expected tools missing")
                    return 1

                print("== wevisone_doctor ==")
                doctor = json.loads(_text_of(await session.call_tool("wevisone_doctor", {})))
                print(json.dumps(doctor, ensure_ascii=False, indent=2)[:1200])

                if not args.image:
                    print("(no --image given, skipping predict)")
                    return 0

                with open(args.image, "rb") as handle:
                    image_b64 = base64.b64encode(handle.read()).decode("ascii")

                print("== wevisone_predict ==")
                result = await session.call_tool(
                    "wevisone_predict",
                    {
                        "image_base64": image_b64,
                        "task": args.task,
                        "query": args.query,
                    },
                )
                payload = json.loads(_text_of(result))
                if payload.get("mask_pngs"):
                    payload["mask_pngs"] = [f"<{len(p)} base64 chars>" for p in payload["mask_pngs"]]
                print(json.dumps(payload, ensure_ascii=False, indent=2)[:2000])
                return 0 if payload.get("ok") else 1
    finally:
        if http_client is not None:
            await http_client.aclose()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000/mcp")
    parser.add_argument("--image", default="")
    parser.add_argument("--task", default="segmentation")
    parser.add_argument("--query", default="sofa")
    parser.add_argument("--token", default="")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
