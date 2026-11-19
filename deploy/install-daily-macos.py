"""Install the daily job on the Mac hosting PitchRank's default SQLite database."""

import os
import plistlib
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
label = "com.pitchrank.daily"
directory = Path.home() / "Library/LaunchAgents"
directory.mkdir(parents=True, exist_ok=True)
path = directory / f"{label}.plist"
domain = f"gui/{os.getuid()}"
python = root / ".venv/bin/python"
if not python.is_file():
    raise SystemExit("Set up PitchRank's virtual environment before installing the job.")
log = root / "data/daily-refresh.log"
config = {
    "Label": label,
    "ProgramArguments": [str(python), "-m", "app.ingestion.daily"],
    "WorkingDirectory": str(root),
    "EnvironmentVariables": {"PYTHONPATH": str(root / "backend")},
    "StartCalendarInterval": {"Hour": 6, "Minute": 15},
    "StandardOutPath": str(log),
    "StandardErrorPath": str(log),
}
path.write_bytes(plistlib.dumps(config))
subprocess.run(["launchctl", "bootout", f"{domain}/{label}"], capture_output=True)
subprocess.run(["launchctl", "bootstrap", domain, str(path)], check=True)
subprocess.run(["launchctl", "kickstart", f"{domain}/{label}"], check=True)
print(f"Installed {label} at 06:15 host time. Logs: {log}")
