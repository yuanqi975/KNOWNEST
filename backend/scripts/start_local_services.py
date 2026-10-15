"""Start the local services using the configured PostgreSQL database."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

root = Path(__file__).resolve().parents[2]
logs = root / "data" / "runtime-check"
logs.mkdir(parents=True, exist_ok=True)
environment = dict(os.environ)
environment["PYTHONPATH"] = str(root / "backend")
flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
npm = shutil.which("npm.cmd")
if not npm:
    raise SystemExit("npm.cmd unavailable")
commands = {
    "backend": ([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"], root),
    "frontend": ([os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe"), "/c", npm, "run", "dev", "--", "--host", "127.0.0.1", "--port", "5173", "--strictPort"], root / "frontend"),
}
for name, (command, cwd) in commands.items():
    with (logs / f"{name}.log").open("a", encoding="utf-8") as stdout, (logs / f"{name}.err.log").open("a", encoding="utf-8") as stderr:
        process = subprocess.Popen(command, cwd=cwd, env=environment, stdout=stdout, stderr=stderr, stdin=subprocess.DEVNULL, creationflags=flags)
    print(json.dumps({"service": name, "pid": process.pid, "log": str(logs / f"{name}.log")}))
print("Local development uses the configured PostgreSQL database; SQLite is only used by isolated tests.")
