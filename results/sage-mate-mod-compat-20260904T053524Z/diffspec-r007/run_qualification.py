#!/usr/bin/env python3
import concurrent.futures
import json
import time
import urllib.error
import urllib.request
from pathlib import Path


BASE = "http://127.0.0.1:8001"
MODEL = "Qwen/Qwen3.8-27B"


def chat(prompt, max_tokens=24, model=MODEL):
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": max_tokens,
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode()
    request = urllib.request.Request(
        f"{BASE}/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            body = json.load(response)
            return {
                "status": response.status,
                "latency_s": time.perf_counter() - started,
                "text": body["choices"][0]["message"]["content"],
                "finish_reason": body["choices"][0]["finish_reason"],
                "usage": body.get("usage"),
            }
    except urllib.error.HTTPError as error:
        return {
            "status": error.code,
            "latency_s": time.perf_counter() - started,
            "error": error.read().decode("utf-8", errors="replace"),
        }


def cancel_after_first_chunk():
    payload = json.dumps({
        "model": MODEL,
        "messages": [{
            "role": "user",
            "content": "Write a detailed 1000-word explanation of distributed consensus.",
        }],
        "temperature": 0,
        "max_tokens": 512,
        "stream": True,
    }).encode()
    request = urllib.request.Request(
        f"{BASE}/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    response = urllib.request.urlopen(request, timeout=300)
    first_data = None
    for raw_line in response:
        line = raw_line.decode("utf-8").strip()
        if line.startswith("data: ") and line != "data: [DONE]":
            first_data = line[6:]
            break
    response.close()
    return {
        "first_chunk_received": first_data is not None,
        "client_closed_after_s": time.perf_counter() - started,
    }


def running_requests():
    with urllib.request.urlopen(f"{BASE}/metrics", timeout=10) as response:
        metrics = response.read().decode("utf-8")
    return sum(
        float(line.rsplit(" ", 1)[1])
        for line in metrics.splitlines()
        if line.startswith("vllm:num_requests_running{")
    )


def main():
    prompts = [
        "Compute 11 * 13. Give only the integer.",
        "Compute 17 * 23. Give only the integer.",
        "Name the chemical symbol for gold. Give only the symbol.",
        "Translate distributed systems into Chinese. Give only the translation.",
    ]
    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        concurrent_results = list(executor.map(chat, prompts))
    concurrent_wall_s = time.perf_counter() - started

    cancellation = cancel_after_first_chunk()
    drain_started = time.monotonic()
    drain_samples = []
    while time.monotonic() - drain_started < 30:
        running = running_requests()
        drain_samples.append({
            "elapsed_s": time.monotonic() - drain_started,
            "running": running,
        })
        if running == 0:
            break
        time.sleep(0.5)

    malformed = chat("This request must fail before inference.", model="missing-model")
    recovery = chat("Reply with exactly: DIFFSPEC_R007_RECOVERY_OK")
    long_context = chat(
        ("token consistency evidence " * 1800)
        + "\nReply with exactly: DIFFSPEC_R007_LONG_OK",
        max_tokens=24,
    )
    result = {
        "concurrency": 4,
        "concurrent_wall_s": concurrent_wall_s,
        "concurrent_results": concurrent_results,
        "cancellation": cancellation,
        "drain_samples": drain_samples,
        "drained": bool(drain_samples and drain_samples[-1]["running"] == 0),
        "malformed": malformed,
        "recovery": recovery,
        "long_context": long_context,
    }
    output = Path("/data/codex-build-artifacts/sage-mate-mod-compat-20260904T053524Z/diffspec-r007/qualification.json")
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
