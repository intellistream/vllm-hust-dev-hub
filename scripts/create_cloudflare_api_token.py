#!/usr/bin/env python3
"""create_cloudflare_api_token.py — Generate a scoped Cloudflare API token for DNS/CDN management."""
import argparse
import json
import os
from pathlib import Path
from typing import Dict, List

import requests

API_BASE = "https://api.cloudflare.com/client/v4"


def _get_headers(api_token: str | None, global_key: str | None, email: str | None) -> Dict[str, str]:
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    if api_token:
        headers["Authorization"] = f"Bearer {api_token}"
        return headers
    if global_key and email:
        headers["X-Auth-Key"] = global_key
        headers["X-Auth-Email"] = email
        return headers
    raise RuntimeError(
        "Missing Cloudflare auth. Provide CLOUDFLARE_BOOTSTRAP_TOKEN or CLOUDFLARE_GLOBAL_API_KEY + CLOUDFLARE_EMAIL"
    )


def _api_get(api_token: str | None, global_key: str | None, email: str | None, path: str) -> dict:
    resp = requests.get(
        f"{API_BASE}{path}",
        headers=_get_headers(api_token=api_token, global_key=global_key, email=email),
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(f"Cloudflare API GET {path} failed: {data}")
    return data


def _api_post(
    api_token: str | None,
    global_key: str | None,
    email: str | None,
    path: str,
    payload: dict,
) -> dict:
    resp = requests.post(
        f"{API_BASE}{path}",
        headers=_get_headers(api_token=api_token, global_key=global_key, email=email),
        data=json.dumps(payload),
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(f"Cloudflare API POST {path} failed: {data}")
    return data


def _load_permission_groups(
    api_token: str | None,
    global_key: str | None,
    email: str | None,
) -> Dict[str, str]:
    data = _api_get(api_token, global_key, email, "/user/tokens/permission_groups")
    groups = data.get("result", [])
    return {g.get("name", ""): g.get("id", "") for g in groups if g.get("name") and g.get("id")}


def _pick_group_id(groups: Dict[str, str], candidates: List[str], required: bool = True) -> str | None:
    for name in candidates:
        if name in groups:
            return groups[name]
    if required:
        raise RuntimeError(f"No permission group matched candidates: {candidates}")
    return None


def _upsert_env(path: Path, key: str, value: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    prefix = f"{key}="
    for idx, line in enumerate(lines):
        if line.startswith(prefix):
            lines[idx] = f"{key}={value}"
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return
    lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _looks_like_api_token(value: str) -> bool:
    return value.startswith("cf") and "_" in value


def main() -> int:
    parser = argparse.ArgumentParser(description="Create Cloudflare API token and write it to .env")
    parser.add_argument("--env-file", default=".env", help="Path to .env file")
    parser.add_argument("--token-name", default="vllm-hust-cloudflare-token", help="Name for the new token")
    parser.add_argument("--zone-id", default=os.getenv("CLOUDFLARE_ZONE_ID", ""), help="Cloudflare Zone ID")
    parser.add_argument(
        "--account-id", default=os.getenv("CLOUDFLARE_ACCOUNT_ID", ""), help="Cloudflare Account ID"
    )
    parser.add_argument(
        "--enable-workers",
        action="store_true",
        help="Also grant Workers Scripts Edit permission at account scope",
    )
    args = parser.parse_args()

    bootstrap_token = os.getenv("CLOUDFLARE_BOOTSTRAP_TOKEN", "").strip()
    global_api_key = os.getenv("CLOUDFLARE_GLOBAL_API_KEY", "").strip()
    cloudflare_email = os.getenv("CLOUDFLARE_EMAIL", "").strip()

    # Compatibility fallback: if user accidentally put an API token in CLOUDFLARE_API_TOKEN,
    # allow using it as bootstrap auth for token creation.
    if not bootstrap_token:
        maybe_token = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
        if _looks_like_api_token(maybe_token):
            bootstrap_token = maybe_token

    if not bootstrap_token and not (global_api_key and cloudflare_email):
        raise RuntimeError(
            "Need CLOUDFLARE_BOOTSTRAP_TOKEN, or CLOUDFLARE_GLOBAL_API_KEY + CLOUDFLARE_EMAIL"
        )

    if global_api_key and not cloudflare_email:
        raise RuntimeError("CLOUDFLARE_EMAIL is required when CLOUDFLARE_GLOBAL_API_KEY is set")

    if not args.zone_id:
        raise RuntimeError("--zone-id or CLOUDFLARE_ZONE_ID is required")

    groups = _load_permission_groups(bootstrap_token or None, global_api_key or None, cloudflare_email or None)
    dns_group_id = _pick_group_id(
        groups,
        candidates=[
            "Zone DNS Edit",
            "DNS Write",
        ],
        required=True,
    )

    policies: List[dict] = [
        {
            "effect": "allow",
            "resources": {f"com.cloudflare.api.account.zone.{args.zone_id}": "*"},
            "permission_groups": [{"id": dns_group_id}],
        }
    ]

    if args.enable_workers:
        if not args.account_id:
            raise RuntimeError("--account-id or CLOUDFLARE_ACCOUNT_ID is required when --enable-workers is set")
        workers_group_id = _pick_group_id(
            groups,
            candidates=[
                "Workers Scripts Edit",
                "Workers Scripts Write",
                "Workers AI Edit",
            ],
            required=False,
        )
        if workers_group_id:
            policies.append(
                {
                    "effect": "allow",
                    "resources": {f"com.cloudflare.api.account.{args.account_id}": "*"},
                    "permission_groups": [{"id": workers_group_id}],
                }
            )

    payload = {
        "name": args.token_name,
        "policies": policies,
    }

    created = _api_post(
        bootstrap_token or None,
        global_api_key or None,
        cloudflare_email or None,
        "/user/tokens",
        payload,
    )
    result = created.get("result", {})
    token_value = result.get("value")
    if not token_value:
        raise RuntimeError(f"Token created but no token value returned: {created}")

    env_path = Path(args.env_file)
    if not env_path.exists():
        env_path.write_text("", encoding="utf-8")

    _upsert_env(env_path, "CLOUDFLARE_API_TOKEN", token_value)
    _upsert_env(env_path, "CLOUDFLARE_ZONE_ID", args.zone_id)
    if args.account_id:
        _upsert_env(env_path, "CLOUDFLARE_ACCOUNT_ID", args.account_id)

    print("Created Cloudflare API token and wrote CLOUDFLARE_API_TOKEN to", env_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
