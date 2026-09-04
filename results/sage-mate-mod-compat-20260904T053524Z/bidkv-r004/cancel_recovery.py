#!/usr/bin/env python3
"""Verify client cancellation, queue drain, health, and deterministic recovery."""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path


BASE = "http://127.0.0.1:8001"
MODEL = "Qwen/Qwen3.8-27B"
ENV_FILE = Path("/home/shuhao/sage-mate/.env")
OUTPUT = Path(__file__).with_name("cancel-recovery.json")


def api_key() -> str:
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("VLLM_HUST_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("API key missing")


def post(path: str, body: dict[str, object], timeout: float) -> dict[str, object]:
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key()}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def queue_depth() -> tuple[int, int]:
    metrics = urllib.request.urlopen(BASE + "/metrics", timeout=5).read().decode("utf-8")
    values = []
    for metric in ("num_requests_running", "num_requests_waiting"):
        match = re.search(rf'^vllm:{metric}{{[^}}]+}} ([0-9.]+)$', metrics, re.MULTILINE)
        if match is None:
            raise RuntimeError(f"missing metric {metric}")
        values.append(int(float(match.group(1))))
    return values[0], values[1]


def main() -> None:
    cancellation_error = None
    started = time.monotonic()
    try:
        post(
            "/v1/completions",
            {
                "model": MODEL,
                "prompt": "cancel recovery pressure " * 10000,
                "temperature": 0,
                "max_tokens": 2048,
                "ignore_eos": True,
            },
            timeout=2,
        )
    except (TimeoutError, urllib.error.URLError) as error:
        cancellation_error = type(error).__name__

    queue_samples = []
    drained = False
    for _ in range(60):
        running, waiting = queue_depth()
        queue_samples.append({"elapsed_s": round(time.monotonic() - started, 3), "running": running, "waiting": waiting})
        if running == 0 and waiting == 0:
            drained = True
            break
        time.sleep(1)

    health = urllib.request.urlopen(BASE + "/health", timeout=5).status
    outputs = []
    for _ in range(2):
        response = post(
            "/v1/chat/completions",
            {
                "model": MODEL,
                "messages": [{"role": "user", "content": "Reply with exactly BIDKV_R004_RECOVERY_OK and nothing else."}],
                "temperature": 0,
                "max_tokens": 32,
            },
            timeout=60,
        )
        text = str(response["choices"][0]["message"]["content"]).strip()
        outputs.append({"text": text, "sha256": hashlib.sha256(text.encode()).hexdigest()})

    report = {
        "cancellation_error": cancellation_error,
        "drained": drained,
        "queue_samples": queue_samples,
        "health_status": health,
        "outputs": outputs,
        "deterministic": outputs[0]["sha256"] == outputs[1]["sha256"],
        "exact": all(item["text"] == "BIDKV_R004_RECOVERY_OK" for item in outputs),
    }
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if cancellation_error and drained and health == 200 and report["deterministic"] and report["exact"] else 1)


if __name__ == "__main__":
    main()
