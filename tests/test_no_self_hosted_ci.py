from pathlib import Path


def test_workflows_do_not_target_self_hosted_runners() -> None:
    offenders: list[str] = []
    for workflow in Path(".github/workflows").glob("*.y*ml"):
        if "self-hosted" in workflow.read_text():
            offenders.append(str(workflow))
    assert offenders == []
