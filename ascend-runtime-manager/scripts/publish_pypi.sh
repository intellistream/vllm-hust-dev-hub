#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if [[ -z "${PYPI_TOKEN:-}" ]]; then
  echo "[ERROR] Missing PYPI_TOKEN env"
  echo "[ERROR] Example: PYPI_TOKEN=pypi-xxxx bash scripts/publish_pypi.sh"
  exit 1
fi

python -m pip install --upgrade build twine
rm -rf dist build *.egg-info src/*.egg-info src/*/*.egg-info
python -m build
python -m twine check dist/*
python -m twine upload --non-interactive -u __token__ -p "${PYPI_TOKEN}" dist/*

echo "[OK] Published to PyPI"
