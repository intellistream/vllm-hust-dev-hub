import argparse
import sys

from .doctor import build_shell_env_exports, collect_report, print_human, print_json
from .launch import launch_vllm
from .setup import setup_environment


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hust-ascend-manager", description="Ascend runtime manager")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_doctor = sub.add_parser("doctor", help="Collect runtime compatibility report")
    p_doctor.add_argument("--json", action="store_true", help="Output JSON format")

    p_setup = sub.add_parser("setup", help="Reconcile Ascend runtime dependencies")
    p_setup.add_argument("--manifest", default=None, help="Path to manager manifest JSON")
    p_setup.add_argument("--apply-system", action="store_true", help="Apply system-level install steps")
    p_setup.add_argument("--install-python-stack", action="store_true", help="Install torch/torch-npu from manifest targets")
    p_setup.add_argument("--dry-run", action="store_true", help="Plan only, do not execute")

    p_env = sub.add_parser("env", help="Emit shell exports for a unified Ascend runtime")
    p_env.add_argument("--ascend-root", default=None, help="Explicit Ascend runtime root")
    p_env.add_argument("--shell", action="store_true", help="Emit shell export statements")

    p_launch = sub.add_parser("launch", help="Run vllm serve with manager-controlled Ascend env")
    p_launch.add_argument("model", help="Model ID or local model path")
    p_launch.add_argument("--manifest", default=None, help="Path to manager manifest JSON")
    p_launch.add_argument("--skip-setup", action="store_true", help="Skip manager setup step")
    p_launch.add_argument("--host", default="0.0.0.0", help="Host for vllm serve")
    p_launch.add_argument("--port", type=int, default=8000, help="Port for vllm serve")
    p_launch.add_argument("--served-model-name", default=None, help="Served model name")
    p_launch.add_argument("--install-python-stack", action="store_true", help="Install torch/torch-npu before launch")
    p_launch.add_argument("--apply-system", dest="apply_system", action="store_true", help="Apply system-level setup before launch")
    p_launch.add_argument("--no-apply-system", dest="apply_system", action="store_false", help="Skip system-level setup before launch")
    p_launch.set_defaults(apply_system=True)
    return parser


def main() -> int:
    parser = build_parser()
    args, unknown_args = parser.parse_known_args()

    if args.cmd == "doctor":
        report = collect_report()
        if args.json:
            print_json(report)
        else:
            print_human(report)
        return 0

    if args.cmd == "setup":
        return setup_environment(
            manifest_path=args.manifest,
            apply_system=args.apply_system,
            install_python_stack=args.install_python_stack,
            dry_run=args.dry_run,
        )

    if args.cmd == "env":
        exports = build_shell_env_exports(ascend_root=args.ascend_root)
        if args.shell:
            print(exports)
        else:
            print(exports)
        return 0

    if args.cmd == "launch":
        return launch_vllm(
            model_ref=args.model,
            manifest_path=args.manifest,
            apply_system=bool(args.apply_system),
            install_python_stack=bool(args.install_python_stack),
            skip_setup=bool(args.skip_setup),
            host=args.host,
            port=args.port,
            served_model_name=args.served_model_name,
            extra_args=list(unknown_args),
        )

    if unknown_args:
        parser.error("unrecognized arguments: " + " ".join(unknown_args))

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
