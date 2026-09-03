"""Strict, JSON-only immutable deployment snapshots; never an executable manifest."""

from dataclasses import dataclass
import hashlib
import json
import re


class ControlError(ValueError):
    """Credential-free public error code."""


def require(condition, code):
    if not condition:
        raise ControlError(code)


def canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ControlError("invalid_json") from exc


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate_json_key")
        result[key] = value
    return result


def decode(raw):
    try:
        return json.loads(raw, object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(ControlError("nonfinite_json")))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ControlError("invalid_json") from exc


def fields(value, names):
    require(isinstance(value, dict) and set(value) == set(names.split()), "invalid_fields")


def text(value):
    require(isinstance(value, str) and 0 < len(value) <= 4096
            and all(ord(c) >= 32 for c in value), "invalid_text")


def identifier(value):
    require(isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9-]{0,63}", value), "invalid_id")


def hash_value(value, size=64):
    require(isinstance(value, str) and re.fullmatch(r"[a-f0-9]{%d}" % size, value), "invalid_hash")


def path(value):
    text(value)
    require(value.startswith("/") and ".." not in value.split("/")
            and value != "/", "invalid_absolute_path")


def artifact(value):
    fields(value, "source_sha wheel_sha256")
    hash_value(value["source_sha"], 40)
    hash_value(value["wheel_sha256"])


@dataclass(frozen=True)
class DeploymentSpec:
    """Canonical bytes prevent caller mutation after validation/approval.

    This is a complete *declared* snapshot. A registered backend must also prove
    resolution/capture completeness against its actual runtime before planning.
    JSON schema validation alone cannot prove a real deployment is recoverable.
    """

    encoded: str

    def __post_init__(self):
        value = decode(self.encoded)
        fields(value, "schema image core ascend manager witness mods model resources launch provider secrets")
        require(value["schema"] == "vllm-hust.deployment-spec/v1", "spec_version")
        fields(value["image"], "id digest platform")
        for name in ("id", "digest"):
            item = value["image"][name]
            require(isinstance(item, str) and item.startswith("sha256:"), "immutable_image_required")
            hash_value(item[7:])
        text(value["image"]["platform"])
        for name in ("core", "ascend", "manager"):
            artifact(value[name])
        if value["witness"] is not None:
            artifact(value["witness"])
        require(isinstance(value["mods"], list) and len(value["mods"]) <= 1, "composition_not_qualified")
        for mod in value["mods"]:
            fields(mod, "id artifact manifest")
            text(mod["id"])
            artifact(mod["artifact"])
            require(isinstance(mod["manifest"], dict), "original_manifest_required")
            require(mod["manifest"].get("extension_id") == mod["id"]
                    and mod["manifest"].get("schema_version") == "0.2-experimental", "manifest_identity")
        fields(value["model"], "id revision path files_sha256")
        text(value["model"]["id"])
        hash_value(value["model"]["revision"], 40)
        hash_value(value["model"]["files_sha256"])
        path(value["model"]["path"])
        resources = value["resources"]
        fields(resources, "devices tp pp graph ports mounts")
        require(isinstance(resources["devices"], list) and resources["devices"], "devices_required")
        for device in resources["devices"]:
            require(type(device) is int and device >= 0, "invalid_device")
        require(len(set(resources["devices"])) == len(resources["devices"]), "duplicate_device")
        for name in ("tp", "pp"):
            require(type(resources[name]) is int and resources[name] > 0, "invalid_parallelism")
        require(resources["tp"] * resources["pp"] == len(resources["devices"]), "topology_mismatch")
        fields(resources["graph"], "mode configuration")
        require(resources["graph"]["mode"] == "graph", "graph_required")
        require(isinstance(resources["graph"]["configuration"], dict), "graph_configuration_required")
        require(isinstance(resources["ports"], list) and isinstance(resources["mounts"], list), "invalid_resources")
        for port in resources["ports"]:
            fields(port, "address host container protocol")
            text(port["address"])
            require(port["protocol"] in {"tcp", "udp"}, "invalid_port")
            for name in ("host", "container"):
                require(type(port[name]) is int and 1 <= port[name] <= 65535, "invalid_port")
        for mount in resources["mounts"]:
            fields(mount, "source target read_only content_sha256")
            path(mount["source"])
            path(mount["target"])
            require(type(mount["read_only"]) is bool, "invalid_mount")
            hash_value(mount["content_sha256"])
        launch = value["launch"]
        fields(launch, "interpreter argv environment working_directory plugin_allowlist resolved_options")
        path(launch["interpreter"])
        path(launch["working_directory"])
        require(isinstance(launch["argv"], list) and launch["argv"], "argv_required")
        for arg in launch["argv"]:
            text(arg)
            require(not any(flag in arg.lower() for flag in
                            ("--enforce-eager", "--api-key", "--password", "--token")), "unsafe_launch_argument")
        require(isinstance(launch["environment"], dict), "invalid_environment")
        for key, val in launch["environment"].items():
            require(re.fullmatch(r"[A-Z][A-Z0-9_]*", key), "invalid_environment")
            require(not re.search(r"SECRET|PASSWORD|TOKEN|API_KEY", key), "use_versioned_secret_reference")
            require(key not in {"VLLM_EXTENSION_MANIFESTS", "VLLM_EXTENSION_BUNDLES"}, "manager_owned_environment")
            require(isinstance(val, str), "invalid_environment")
        require(isinstance(launch["plugin_allowlist"], list), "allowlist_required")
        for name in launch["plugin_allowlist"]:
            text(name)
        require(len(set(launch["plugin_allowlist"])) == len(launch["plugin_allowlist"]), "duplicate_plugin")
        require(isinstance(launch["resolved_options"], dict) and launch["resolved_options"], "resolved_options_required")
        resolved = launch["resolved_options"]
        require(resolved.get("enforce_eager") is False
                and type(resolved.get("tensor_parallel_size")) is int
                and resolved["tensor_parallel_size"] == resources["tp"]
                and type(resolved.get("pipeline_parallel_size")) is int
                and resolved["pipeline_parallel_size"] == resources["pp"]
                and resolved.get("model") == value["model"]["id"]
                and resolved.get("compilation_config") == resources["graph"]["configuration"], "resolved_launch_mismatch")
        provider = value["provider"]
        fields(provider, "id source_sha configuration rendered rendered_sha256 qualification")
        identifier(provider["id"])
        hash_value(provider["source_sha"], 40)
        require(isinstance(provider["configuration"], dict) and isinstance(provider["rendered"], dict), "provider_snapshot_required")
        require(digest(provider["rendered"]) == provider["rendered_sha256"], "render_drift")
        fields(provider["qualification"], "receipt_sha256 status")
        hash_value(provider["qualification"]["receipt_sha256"])
        require(provider["qualification"]["status"] == "qualified", "qualification_required")
        require(isinstance(value["secrets"], list), "secret_references_required")
        for secret in value["secrets"]:
            fields(secret, "id version target")
            identifier(secret["id"])
            text(secret["version"])
            require(secret["version"] not in {"latest", "main", "current"}, "secret_version_required")
            text(secret["target"])
        object.__setattr__(self, "encoded", canonical(value))

    @classmethod
    def freeze(cls, value):
        return cls(canonical(value))

    @property
    def sha256(self):
        return hashlib.sha256(self.encoded.encode()).hexdigest()

    def value(self):
        return decode(self.encoded)

    def invariant(self):
        value = self.value()
        return {"model": value["model"], "resources": value["resources"]}
