from __future__ import annotations

from hust_ascend_manager.launch import _apply_prefill_compat_args


def test_apply_prefill_compat_args_appends_safe_defaults():
    args = _apply_prefill_compat_args([], enable_prefill_compat_mode=True)

    assert "--no-enable-prefix-caching" in args
    assert "--no-enable-chunked-prefill" in args


def test_apply_prefill_compat_args_respects_user_prefill_flags():
    args = _apply_prefill_compat_args(
        ["--enable-prefix-caching", "--no-enable-chunked-prefill"],
        enable_prefill_compat_mode=True,
    )

    assert args == ["--enable-prefix-caching", "--no-enable-chunked-prefill"]


def test_apply_prefill_compat_args_can_be_disabled():
    args = _apply_prefill_compat_args([], enable_prefill_compat_mode=False)

    assert args == []
