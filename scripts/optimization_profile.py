"""Resolve an optimization manifest into launcher environment variables."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
from pathlib import Path
from string import Template
from typing import Any


ENV_KEY = re.compile(r"^[A-Z][A-Z0-9_]*$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--container-repo")
    parser.add_argument("--param", action="append", default=[])
    parser.add_argument("--format", choices=("shell", "json"), default="shell")
    return parser.parse_args()


def load_manifest(args: argparse.Namespace) -> tuple[Path, dict[str, Any]]:
    if args.profile and "," in args.profile:
        raise ValueError(
            "multiple optimization profiles are not supported in one service; "
            "use a separate service instance for each profile"
        )
    if args.manifest:
        candidates = [args.manifest]
    else:
        if not args.profile:
            raise ValueError("--profile is required when --manifest is not provided")
        workspace_root = args.workspace_root or Path(__file__).resolve().parents[2]
        candidates = sorted(workspace_root.glob("*/.vllm-hust/optimization.json"))

    matches: list[tuple[Path, dict[str, Any]]] = []
    for path in candidates:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if args.profile is None or payload.get("id") == args.profile:
            matches.append((path, payload))

    if not matches:
        raise ValueError(f"optimization profile {args.profile!r} was not found")
    if len(matches) > 1:
        paths = ", ".join(str(path) for path, _payload in matches)
        raise ValueError(f"optimization profile {args.profile!r} is ambiguous: {paths}")
    return matches[0]


def parse_parameters(raw_params: list[str]) -> dict[str, str]:
    parameters: dict[str, str] = {}
    for item in raw_params:
        if "=" not in item:
            raise ValueError(f"optimization parameter must be NAME=VALUE: {item!r}")
        name, value = item.split("=", 1)
        if not name or not value:
            raise ValueError(f"optimization parameter must be NAME=VALUE: {item!r}")
        parameters[name] = value
    return parameters


def render(value: Any, parameters: dict[str, str]) -> Any:
    if isinstance(value, str):
        return Template(value).substitute(parameters)
    if isinstance(value, list):
        return [render(item, parameters) for item in value]
    if isinstance(value, dict):
        return {key: render(item, parameters) for key, item in value.items()}
    return value


def merge_csv(existing: str, additions: list[str]) -> str:
    values = [item.strip() for item in existing.split(",") if item.strip()]
    for item in additions:
        if item and item not in values:
            values.append(item)
    return ",".join(values)


def build_environment(
    manifest: dict[str, Any],
    raw_params: list[str],
    *,
    container_repo: str | None = None,
) -> dict[str, str]:
    if manifest.get("schema_version") != 1:
        raise ValueError("optimization manifest schema_version must be 1")

    profile_id = str(manifest.get("id") or "").strip()
    repository = str(manifest.get("repository") or "").strip()
    entrypoint = manifest.get("entrypoint") or {}
    group = str(entrypoint.get("group") or "").strip()
    plugin = str(entrypoint.get("name") or "").strip()
    if not all((profile_id, repository, group, plugin)):
        raise ValueError("manifest requires id, repository, and entrypoint group/name")

    supplied = parse_parameters(raw_params)
    declared = manifest.get("parameters") or {}
    unknown = sorted(set(supplied) - set(declared))
    if unknown:
        raise ValueError(f"unknown optimization parameter(s): {', '.join(unknown)}")

    parameters: dict[str, str] = {}
    for name, specification in declared.items():
        value = supplied.get(name)
        if value is None and "default" in specification:
            value = str(specification["default"])
        if value is None and specification.get("required"):
            flag = specification.get("flag") or f"--optimization-param {name}=..."
            raise ValueError(f"profile {profile_id!r} requires {flag}")
        if value is not None:
            parameters[name] = value

    activation = render(manifest.get("activation") or {}, parameters)
    environment: dict[str, str] = {
        "VLLM_OPTIMIZATION_PROFILE": profile_id,
        "VLLM_OPTIMIZATION_REPO_CONTAINER": (
            container_repo
            or os.environ.get("VLLM_OPTIMIZATION_REPO_CONTAINER")
            or f"/workspace/{repository}"
        ),
        "VLLM_OPTIMIZATION_SRC_SUBDIR": str(manifest.get("source_subdir") or ""),
        "VLLM_OPTIMIZATION_PLUGIN": plugin,
        "VLLM_OPTIMIZATION_ENTRYPOINT_GROUP": group,
        "VLLM_OPTIMIZATION_AUTO_INSTALL": os.environ.get(
            "VLLM_OPTIMIZATION_AUTO_INSTALL", "true"
        ),
    }

    for key, value in (activation.get("environment") or {}).items():
        if not ENV_KEY.fullmatch(key):
            raise ValueError(f"invalid environment key in manifest: {key!r}")
        environment[key] = os.environ.get(key, str(value))

    vllm_plugins = [str(item) for item in activation.get("vllm_plugins") or []]
    if vllm_plugins:
        environment["VLLM_PLUGINS"] = ",".join(vllm_plugins)

    extra_keys = [str(item) for item in activation.get("extra_env_keys") or []]
    extra_prefixes = [
        str(item) for item in activation.get("extra_env_prefixes") or []
    ]
    if extra_keys:
        environment["VLLM_ENGINE_EXTRA_ENV_KEYS"] = merge_csv(
            os.environ.get("VLLM_ENGINE_EXTRA_ENV_KEYS", ""), extra_keys
        )
    if extra_prefixes:
        environment["VLLM_ENGINE_EXTRA_ENV_PREFIXES"] = merge_csv(
            os.environ.get("VLLM_ENGINE_EXTRA_ENV_PREFIXES", ""), extra_prefixes
        )

    profile_args = activation.get("extra_args") or []
    existing_args_raw = os.environ.get("VLLM_ENGINE_EXTRA_ARGS_JSON", "")
    existing_args = json.loads(existing_args_raw) if existing_args_raw else []
    if not isinstance(existing_args, list) or not all(
        isinstance(item, str) for item in existing_args
    ):
        raise ValueError("VLLM_ENGINE_EXTRA_ARGS_JSON must be a JSON list of strings")
    serialized_profile_args = [
        json.dumps(item, separators=(",", ":")) if isinstance(item, dict) else str(item)
        for item in profile_args
    ]
    if serialized_profile_args or existing_args:
        environment["VLLM_ENGINE_EXTRA_ARGS_JSON"] = json.dumps(
            serialized_profile_args + existing_args,
            separators=(",", ":"),
        )

    incompatible = (manifest.get("compatibility") or {}).get("incompatible_with") or []
    if incompatible:
        environment["VLLM_OPTIMIZATION_INCOMPATIBLE_WITH"] = ",".join(
            str(item) for item in incompatible
        )
    return environment


def main() -> None:
    args = parse_args()
    try:
        _path, manifest = load_manifest(args)
        environment = build_environment(
            manifest,
            args.param,
            container_repo=args.container_repo,
        )
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"ERROR: {exc}") from exc

    if args.format == "json":
        print(json.dumps(environment, ensure_ascii=False, sort_keys=True))
        return
    for key in sorted(environment):
        print(f"export {key}={shlex.quote(environment[key])}")


if __name__ == "__main__":
    main()
