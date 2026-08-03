from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).parents[1]
SCRIPTS = (
    REPO_ROOT / "scripts" / "run_vllm_hust_engine.sh",
    REPO_ROOT / "scripts" / "cleanup_vllm_hust_engine.sh",
)


def test_in_progress_launcher_cleanup_is_scoped_to_requested_port() -> None:
    for script in SCRIPTS:
        source = script.read_text()
        assert 'grep -Fq -- "--port \\"$port\\"" "$launcher_script"' in source
        assert "launcher_script=${launcher_args#bash }" in source


def test_cleanup_no_longer_collects_every_in_progress_launcher() -> None:
    unconditional_filter = """/bash \\/tmp\\/vllm-hust-engine\\.[A-Za-z0-9]+\\.sh/ {
      print $1
    }"""
    for script in SCRIPTS:
        assert unconditional_filter not in script.read_text()
