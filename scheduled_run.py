"""
Entry point for Windows Task Scheduler. Computes a trailing 30-day window
ending yesterday (so a run on Oct 7 covers 07 Sep - 06 Oct) and calls
run_pipeline.py for the given brand. Logs to logs/<brand>_<date>.log since
scheduled runs have no one watching the terminal.
"""
import argparse
import os
import subprocess
import sys
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(ROOT, "logs")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--brand", required=True)
    args = parser.parse_args()

    os.makedirs(LOG_DIR, exist_ok=True)
    yesterday = datetime.now() - timedelta(days=1)
    start = yesterday - timedelta(days=29)
    start_str = start.strftime("%d-%m-%Y")
    end_str = yesterday.strftime("%d-%m-%Y")

    log_path = os.path.join(LOG_DIR, f"{args.brand}_{yesterday.strftime('%Y-%m-%d')}.log")
    python_exe = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
    cmd = [python_exe, os.path.join(ROOT, "run_pipeline.py"), "--start", start_str, "--end", end_str, "--brand", args.brand]

    # Session/page checks occasionally flake transiently (confirmed live -
    # a login that failed once passed immediately on retry with the exact
    # same saved session). A real expired session needing fresh 2FA would
    # fail all 3 attempts too, so this doesn't mask that - it just avoids
    # losing a whole day's data to a one-off blip with nobody watching.
    result = None
    with open(log_path, "w", encoding="utf-8") as log_file:
        log_file.write(f"Running: {' '.join(cmd)}\n\n")
        for attempt in range(1, 4):
            log_file.write(f"--- attempt {attempt}/3 ---\n")
            log_file.flush()
            result = subprocess.run(
                cmd, cwd=ROOT, stdout=log_file, stderr=subprocess.STDOUT,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
            if result.returncode == 0:
                break
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
