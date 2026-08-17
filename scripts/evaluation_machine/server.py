from __future__ import annotations

import argparse
import json
import os
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .common import ContractError, load_json, validate_request, verify_signature
from .store import JobStore

JOB_PATH = re.compile(r"^/v1/jobs/([a-zA-Z0-9-]+)(/cancel)?$")


class EvaluationHandler(BaseHTTPRequestHandler):
    server: EvaluationServer

    def reply(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authenticate(self, body: bytes) -> None:
        authorization = self.headers.get("Authorization", "")
        if authorization != f"Bearer {self.server.token}":
            raise ContractError("invalid bearer token")
        verify_signature(
            self.server.hmac_secret,
            self.headers.get("X-Evaluation-Timestamp", ""),
            body,
            self.headers.get("X-Evaluation-Signature", ""),
        )

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self.reply(
                HTTPStatus.OK,
                {"status": "ok", "maintenance": self.server.maintenance.exists()},
            )
            return
        match = JOB_PATH.fullmatch(self.path)
        if not match or match.group(2):
            self.reply(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        try:
            self.authenticate(b"")
            self.reply(HTTPStatus.OK, self.server.store.get(match.group(1)))
        except KeyError:
            self.reply(HTTPStatus.NOT_FOUND, {"error": "job not found"})
        except ContractError as exc:
            self.reply(HTTPStatus.UNAUTHORIZED, {"error": str(exc)})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1024 * 1024:
            self.reply(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "request too large"}
            )
            return
        body = self.rfile.read(length)
        try:
            self.authenticate(body)
            if self.server.maintenance.exists():
                self.reply(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {"error": "evaluation machine is in maintenance"},
                )
                return
            match = JOB_PATH.fullmatch(self.path)
            if match and match.group(2):
                self.reply(HTTPStatus.OK, self.server.store.cancel(match.group(1)))
                return
            if self.path != "/v1/jobs":
                self.reply(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return
            idempotency_key = self.headers.get("Idempotency-Key", "")
            if not re.fullmatch(r"[A-Za-z0-9._:/+-]{12,200}", idempotency_key):
                raise ContractError("invalid or missing idempotency key")
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ContractError("request body must be an object")
            request = validate_request(payload, self.server.allowed_repositories)
            job, created = self.server.store.submit(idempotency_key, request)
            self.reply(HTTPStatus.CREATED if created else HTTPStatus.OK, job)
        except KeyError:
            self.reply(HTTPStatus.NOT_FOUND, {"error": "job not found"})
        except (ContractError, ValueError, json.JSONDecodeError) as exc:
            self.reply(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def log_message(self, format: str, *args: object) -> None:
        print(
            f"evaluation-api client={self.client_address[0]} {format % args}",
            flush=True,
        )


class EvaluationServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], config: dict[str, Any]):
        super().__init__(address, EvaluationHandler)
        state_dir = Path(config["state_dir"])
        self.store = JobStore(state_dir / "queue.sqlite3")
        self.maintenance = state_dir / "MAINTENANCE"
        self.allowed_repositories = set(config["allowed_repositories"])
        self.token = os.environ[config.get("token_env", "EVALUATION_API_TOKEN")]
        self.hmac_secret = os.environ[
            config.get("hmac_secret_env", "EVALUATION_HMAC_SECRET")
        ].encode()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    config = load_json(args.config)
    host, port = config.get("listen", "127.0.0.1:9112").rsplit(":", 1)
    EvaluationServer((host, int(port)), config).serve_forever()


if __name__ == "__main__":
    main()
