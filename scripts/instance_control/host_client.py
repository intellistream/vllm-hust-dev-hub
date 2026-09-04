"""Small AF_UNIX JSON client for the fixed host-broker protocol."""

import socket

from .host_broker import MAX_REQUEST, PROTOCOL
from .schema import canonical, decode, require


def request(socket_path: str, value: dict, *, timeout=3.0) -> dict:
    payload = canonical(value).encode()
    require(len(payload) <= MAX_REQUEST, "request_too_large")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout)
        client.connect(socket_path)
        client.sendall(payload)
        client.shutdown(socket.SHUT_WR)
        raw = client.recv(MAX_REQUEST + 1)
    require(raw and len(raw) <= MAX_REQUEST, "invalid_broker_response")
    result = decode(raw)
    require(isinstance(result, dict) and result.get("protocol") == PROTOCOL,
            "invalid_broker_response")
    return result
