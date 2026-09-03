"""Documented v1 trusted backend interface; no registry or product implementation."""

from typing import Protocol

from .schema import ControlError, DeploymentSpec

ERROR_CODES = frozenset({
    "backend_unqualified", "identity_drift", "ownership_lost", "deadline_exceeded",
    "configuration_drift", "evidence_incomplete", "old_executor_live",
    "nested_owner_entry", "backend_failed",
})


class BackendFailure(ControlError):
    """Only a closed code leaves the adapter; never reflect raw private details."""

    def __init__(self, code="backend_failed"):
        self.code = code if isinstance(code, str) and code in ERROR_CODES else "backend_failed"
        super().__init__(self.code)


class Backend(Protocol):
    """Same call signatures as the initial b6e56e1 transaction fixture.

    This protocol is structural documentation, not qualification or authorization.
    See docs/instance-backend-contract-proposal.md for identity and effect rules.
    """

    def qualify(self, registration: dict, spec: DeploymentSpec) -> bool: ...

    def inspect(self, registration: dict) -> dict: ...

    def owns(self, registration: dict, operation: dict, expected_identity: dict,
             *, restore: bool) -> bool: ...

    def deploy(self, registration: dict, spec: DeploymentSpec, operation: dict,
               deadline: float, *, restore: bool) -> None: ...

    def verify(self, registration: dict, spec_hash: str, operation: dict,
               deadline: float) -> dict: ...

    def quiescent(self, registration: dict, operation: dict) -> bool: ...
