#!/usr/bin/env python3
"""Measure sustained single-NPU HBM traffic with copy and BF16 vector add."""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path


GIB = 2**30
MIB = 2**20
DEVICE_SELECTION_ENV_VARS = (
    "ASCEND_RT_VISIBLE_DEVICES",
    "ASCEND_VISIBLE_DEVICES",
    "SOURCE_DEV_NPU_DEVICES",
)


def parse_sizes(raw: str) -> list[int]:
    sizes = [int(item.strip()) for item in raw.split(",") if item.strip()]
    if not sizes or any(size <= 0 for size in sizes):
        raise argparse.ArgumentTypeError("sizes must be positive comma-separated MiB values")
    return sizes


def iterations_for(tensor_bytes: int, traffic_factor: int, target_traffic_gib: float) -> int:
    traffic_per_iteration = tensor_bytes * traffic_factor
    return max(3, min(500, int(target_traffic_gib * GIB / traffic_per_iteration)))


def measure(torch, operation, *, warmup: int, iterations: int, repeats: int) -> tuple[list[float], list[float]]:
    for _ in range(warmup):
        operation()
    torch.npu.synchronize()

    event_samples_ms: list[float] = []
    wall_samples_ms: list[float] = []
    for _ in range(repeats):
        torch.npu.synchronize()
        start_event = torch.npu.Event(enable_timing=True)
        end_event = torch.npu.Event(enable_timing=True)
        wall_start = time.perf_counter_ns()
        start_event.record()
        for _ in range(iterations):
            operation()
        end_event.record()
        torch.npu.synchronize()
        wall_ms = (time.perf_counter_ns() - wall_start) / 1e6 / iterations
        event_ms = float(start_event.elapsed_time(end_event)) / iterations
        event_samples_ms.append(event_ms)
        wall_samples_ms.append(wall_ms)
    return event_samples_ms, wall_samples_ms


def bandwidth_gbps(traffic_bytes: int, milliseconds: float) -> float:
    return traffic_bytes / (milliseconds / 1000) / 1e9


def physical_device_selection() -> str | None:
    """Return the first configured physical-device mapping."""
    for variable in DEVICE_SELECTION_ENV_VARS:
        value = os.getenv(variable)
        if value:
            return value
    return None


def make_record(
    *,
    operation: str,
    size_mib: int,
    traffic_factor: int,
    event_samples_ms: list[float],
    wall_samples_ms: list[float],
    iterations: int,
) -> dict[str, object]:
    tensor_bytes = size_mib * MIB
    event_median = statistics.median(event_samples_ms)
    event_best = min(event_samples_ms)
    return {
        "operation": operation,
        "dtype": "bfloat16",
        "tensor_mib": size_mib,
        "tensor_bytes": tensor_bytes,
        "traffic_model": {
            "factor": traffic_factor,
            "bytes_per_iteration": traffic_factor * tensor_bytes,
            "description": "one read + one write" if traffic_factor == 2 else "two reads + one write",
        },
        "iterations_per_sample": iterations,
        "event_samples_ms_per_iteration": event_samples_ms,
        "wall_samples_ms_per_iteration": wall_samples_ms,
        "event_median_ms": event_median,
        "event_best_ms": event_best,
        "payload_GBps_median": bandwidth_gbps(tensor_bytes, event_median),
        "estimated_HBM_traffic_GBps_median": bandwidth_gbps(traffic_factor * tensor_bytes, event_median),
        "estimated_HBM_traffic_GBps_best": bandwidth_gbps(traffic_factor * tensor_bytes, event_best),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sizes-mib", type=parse_sizes, default=parse_sizes("64,256,1024,2048,4096"))
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--target-traffic-gib", type=float, default=64.0)
    args = parser.parse_args()
    if args.warmup < 0 or args.repeats <= 0 or args.target_traffic_gib <= 0:
        parser.error("warmup must be non-negative; repeats and target traffic must be positive")

    import torch
    import torch_npu

    torch.npu.set_device(0)
    records: list[dict[str, object]] = []
    for size_mib in args.sizes_mib:
        tensor_bytes = size_mib * MIB
        elements = tensor_bytes // torch.tensor([], dtype=torch.bfloat16).element_size()
        a = torch.full((elements,), 1, dtype=torch.bfloat16, device="npu:0")
        b = torch.full((elements,), 2, dtype=torch.bfloat16, device="npu:0")
        output = torch.empty_like(a)

        cases = (
            ("copy", 2, 1.0, lambda: output.copy_(a)),
            ("add", 3, 3.0, lambda: torch.add(a, b, out=output)),
        )
        for name, traffic_factor, expected_value, operation in cases:
            iterations = iterations_for(tensor_bytes, traffic_factor, args.target_traffic_gib)
            event_samples, wall_samples = measure(
                torch,
                operation,
                warmup=args.warmup,
                iterations=iterations,
                repeats=args.repeats,
            )
            record = make_record(
                operation=name,
                size_mib=size_mib,
                traffic_factor=traffic_factor,
                event_samples_ms=event_samples,
                wall_samples_ms=wall_samples,
                iterations=iterations,
            )
            records.append(record)
            actual_value = float(output[0].cpu())
            if actual_value != expected_value:
                raise RuntimeError(
                    f"{name} produced {actual_value}, expected {expected_value}"
                )
            print(
                f"{name:4s} {size_mib:4d} MiB: "
                f"median={record['estimated_HBM_traffic_GBps_median']:.2f} GB/s "
                f"best={record['estimated_HBM_traffic_GBps_best']:.2f} GB/s",
                flush=True,
            )

        del a, b, output
        torch.npu.empty_cache()

    document = {
        "schema_version": 1,
        "probe": "single_npu_hbm",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "hostname": platform.node(),
        "torch_version": torch.__version__,
        "torch_npu_version": getattr(torch_npu, "__version__", "unknown"),
        "logical_device": 0,
        "physical_device_selection": physical_device_selection(),
        "method_note": (
            "GB/s uses decimal bytes. HBM traffic is an algorithmic estimate: copy counts "
            "one tensor read plus one write; add counts two reads plus one write."
        ),
        "records": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
