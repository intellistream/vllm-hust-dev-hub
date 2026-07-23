import importlib.util, json, pathlib, sys
cfg = json.loads('{"cann_setup":"/usr/local/Ascend/ascend-toolkit/set_env.sh","engine_entry":"/workspace/vllm-hust-dev-container-env/bin/vllm-hust","model_path":"/data/shared_models/Qwen2.5-7B-Instruct","required_modules":["torch","torch_npu","vllm","vllm_ascend","vllm_kvdelta.connector"]}')
missing = []
for name in cfg["required_modules"]:
    try:
        visible = importlib.util.find_spec(name) is not None
    except (ImportError, AttributeError, ValueError):
        visible = False
    if not visible:
        missing.append(name)
if missing:
    raise SystemExit("managed compatibility gate: missing modules: " + ",".join(missing))
model = pathlib.Path(cfg["model_path"])
if not model.is_dir() or not (model / "config.json").is_file():
    raise SystemExit("managed compatibility gate: model/config.json unavailable")
cann = pathlib.Path(cfg["cann_setup"])
if not cann.is_file():
    raise SystemExit("managed compatibility gate: CANN setup unavailable")
engine = pathlib.Path(cfg["engine_entry"])
if not engine.is_file():
    raise SystemExit("managed compatibility gate: engine entry unavailable")
python = pathlib.Path(sys.executable)
if not python.is_absolute() or not python.is_file():
    raise SystemExit("managed compatibility gate: Python executable unavailable")
print(json.dumps({"status":"PASS","gate":"managed-container-software-compatibility-v1","modules":cfg["required_modules"]}, sort_keys=True))
