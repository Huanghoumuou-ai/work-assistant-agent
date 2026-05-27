from __future__ import annotations

import os
import subprocess
from pathlib import Path
import shutil
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _run_version(command: list[str]) -> str:
    if command[0].lower() in {"npm", "npm.cmd"} and os.name == "nt":
        command = ["cmd", "/c", *command]
    try:
        completed = subprocess.run(command, capture_output=True, check=False, text=True, timeout=10)
    except Exception as error:
        return f"error: {error}"
    output = (completed.stdout or completed.stderr).strip()
    return output or f"exit {completed.returncode}"


def _status(label: str, ok: bool, detail: str) -> bool:
    marker = "OK" if ok else "MISSING"
    print(f"[{marker}] {label}: {detail}")
    return ok


def main() -> int:
    checks: list[bool] = []

    python_path = shutil.which("python")
    node_path = shutil.which("node")
    npm_path = shutil.which("npm")
    checks.append(_status("python", python_path is not None, python_path or "not found"))
    if python_path:
        print(f"       version: {_run_version(['python', '--version'])}")
    checks.append(_status("node", node_path is not None, node_path or "not found"))
    if node_path:
        print(f"       version: {_run_version(['node', '--version'])}")
    checks.append(_status("npm", npm_path is not None, npm_path or "not found"))
    if npm_path:
        print(f"       version: {_run_version(['npm', '--version'])}")

    required_paths = [
        ".env.example",
        "backend/requirements.txt",
        "backend/app/main.py",
        "apps/desktop/package.json",
        "package.json",
    ]
    for relative_path in required_paths:
        path = PROJECT_ROOT / relative_path
        checks.append(_status(relative_path, path.exists(), str(path)))

    venv_python = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    checks.append(_status(".venv", venv_python.exists(), str(venv_python)))

    node_modules = PROJECT_ROOT / "node_modules"
    checks.append(_status("node_modules", node_modules.exists(), str(node_modules)))

    runtime_dirs = ["data", "data/files", "data/parsed", "data/sqlite", "data/vector_db", "data/logs", "data/cache"]
    for relative_path in runtime_dirs:
        path = PROJECT_ROOT / relative_path
        checks.append(_status(relative_path, path.exists(), str(path)))

    if os.environ.get("OPENAI_API_KEY"):
        print("[WARN] OPENAI_API_KEY is set in the current shell. Do not commit real keys.")

    return 0 if all(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
