"""Allocate real NPU memory, remain observable briefly, then fail deliberately."""

from __future__ import annotations

import os
import time

import torch
import torch_npu  # noqa: F401


device = os.environ.get("VLLM_TEST_NPU_DEVICE", "npu:0")
hold_seconds = float(os.environ.get("VLLM_TEST_NPU_HOLD_SECONDS", "10"))
allocation_mib = int(os.environ.get("VLLM_TEST_NPU_ALLOCATION_MIB", "256"))

torch.npu.set_device(device)
element_count = allocation_mib * 1024 * 1024 // 2
allocation = torch.ones(element_count, dtype=torch.bfloat16, device=device)
torch.npu.synchronize()
print(
    "VLLM_TEST_NPU_ALLOCATION_READY "
    f"device={device} bytes={allocation.numel() * allocation.element_size()}",
    flush=True,
)
time.sleep(hold_seconds)
raise SystemExit(42)
