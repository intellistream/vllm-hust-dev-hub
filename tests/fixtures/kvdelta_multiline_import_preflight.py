import importlib.util, json, os, pathlib, stat, sys
cfg = json.loads('{"cann_setup":"/usr/local/Ascend/ascend-toolkit/set_env.sh","engine_entry":"/usr/local/python3.12.13/bin/vllm","model_path":"/data/shared_models/Qwen2.5-7B-Instruct","python_entry":"/usr/local/python3.12.13/bin/python3","required_module_origins":{"vllm_kvdelta.connector":"/opt/vllm-optimization/fixture/delta-producer/src/vllm_kvdelta/connector.py"},"required_modules":["torch","torch_npu","vllm","vllm_ascend","vllm_kvdelta.connector"]}')

def fail(label, path, detail):
    raise SystemExit("managed compatibility gate: " + label + " unavailable: " + path + " (" + detail + ")")

def require_file(label, raw_path, executable=False):
    path = pathlib.Path(raw_path)
    try:
        mode = path.stat().st_mode
        if not stat.S_ISREG(mode):
            fail(label, raw_path, "not a regular file")
        if executable and not os.access(path, os.X_OK):
            fail(label, raw_path, "not executable by exact container user")
    except OSError as exc:
        fail(label, raw_path, type(exc).__name__ + ": " + str(exc))
    return path

missing = []
for name in cfg["required_modules"]:
    try:
        spec = importlib.util.find_spec(name)
    except (ImportError, AttributeError, OSError, ValueError):
        spec = None
    if spec is None:
        missing.append(name)
if missing:
    raise SystemExit("managed compatibility gate: missing modules: " + ",".join(missing))
model = pathlib.Path(cfg["model_path"])
try:
    if not model.is_dir():
        fail("model directory", cfg["model_path"], "not a directory")
except OSError as exc:
    fail("model directory", cfg["model_path"], type(exc).__name__ + ": " + str(exc))
require_file("model config", str(model / "config.json"))
require_file("CANN setup", cfg["cann_setup"])
require_file("engine entry", cfg["engine_entry"], executable=True)
require_file("Python executable", cfg["python_entry"], executable=True)
print(json.dumps({"status":"PASS","gate":"managed-container-software-compatibility-v2","modules":cfg["required_modules"]}, sort_keys=True))
