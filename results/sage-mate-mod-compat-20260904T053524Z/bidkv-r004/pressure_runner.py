#!/usr/bin/env python3
"""Bounded concurrent OpenAI-compatible pressure probe for BidKV qualification."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path


def api_key_from_env_file(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("VLLM_HUST_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("VLLM_HUST_API_KEY is missing")


def request_once(index: int, args: argparse.Namespace, api_key: str) -> dict[str, object]:
    prompt = (
        "Continue with concise numbered facts about deterministic distributed systems. "
        + ("coordination state invariant recovery progress " * args.repeat)
        + f"\nRequest marker: {index}."
    )
    payload = json.dumps(
        {
            "model": args.model,
            "prompt": prompt,
            "temperature": 0,
            "max_tokens": args.max_tokens,
            "ignore_eos": True,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        args.url,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            body = json.loads(response.read())
            text = body["choices"][0]["text"]
            usage = body.get("usage", {})
            return {
                "index": index,
                "ok": response.status == 200,
                "status": response.status,
                "elapsed_s": round(time.monotonic() - started, 3),
                "completion_tokens": usage.get("completion_tokens"),
                "prompt_tokens": usage.get("prompt_tokens"),
                "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "text_prefix": text[:80],
            }
    except urllib.error.HTTPError as error:
        return {
            "index": index,
            "ok": False,
            "status": error.code,
            "elapsed_s": round(time.monotonic() - started, 3),
            "error_type": type(error).__name__,
            "error": error.read().decode("utf-8", errors="replace")[:500],
        }
    except (TimeoutError, urllib.error.URLError) as error:
        return {
            "index": index,
            "ok": False,
            "elapsed_s": round(time.monotonic() - started, 3),
            "error_type": type(error).__name__,
            "error": str(error),
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8001/v1/completions")
    parser.add_argument("--model", default="Qwen/Qwen3.8-27B")
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--repeat", type=int, default=8000)
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args()
    api_key = api_key_from_env_file(args.env_file)
    started_at = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [pool.submit(request_once, index, args, api_key) for index in range(args.concurrency)]
        results = [future.result() for future in concurrent.futures.as_completed(futures)]
    results.sort(key=lambda item: int(item["index"]))
    report = {
        "started_at_epoch_s": started_at,
        "elapsed_s": round(time.time() - started_at, 3),
        "configuration": {
            "concurrency": args.concurrency,
            "repeat": args.repeat,
            "max_tokens": args.max_tokens,
            "timeout_s": args.timeout,
        },
        "all_ok": all(bool(result["ok"]) for result in results),
        "results": results,
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["all_ok"] else 1)


if __name__ == "__main__":
    main()
