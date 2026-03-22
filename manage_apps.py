#!/usr/bin/env python3
"""
Manage multiple applications that are started with `uv run app.py`.
Cross‑platform (Windows & Unix).
"""

import os
import sys
import time
import signal
import argparse
import subprocess
from pathlib import Path
from typing import Dict, Optional

# -------------------------------
# Configuration
# -------------------------------
# Base directory where app subfolders are located (default: current working directory)
BASE_DIR = Path(os.environ.get("OPENALGO_BASE", ".")).resolve()

# Store logs and PID files in a subfolder of the script's own directory
SCRIPT_DIR = Path(__file__).parent.resolve()
DATA_DIR = SCRIPT_DIR / ".app_data"
LOG_DIR = DATA_DIR / "logs"
PID_DIR = DATA_DIR / "pids"

# Create directories if they don't exist
LOG_DIR.mkdir(parents=True, exist_ok=True)
PID_DIR.mkdir(parents=True, exist_ok=True)

GRACEFUL_TIMEOUT = 5  # seconds to wait before force‑kill

# Detect OS
IS_WINDOWS = sys.platform == "win32"

# -------------------------------
# Process management helpers (cross‑platform)
# -------------------------------
def pid_file(app_name: str) -> Path:
    return PID_DIR / f"{app_name}.pid"

def log_file(app_name: str) -> Path:
    return LOG_DIR / f"{app_name}.log"

def is_running(app_name: str) -> Optional[int]:
    """Return PID if process is alive, else None."""
    pid_path = pid_file(app_name)
    if not pid_path.exists():
        return None
    try:
        pid = int(pid_path.read_text().strip())
        # Check existence without sending a signal
        if IS_WINDOWS:
            # On Windows, we can use OpenProcess via ctypes, but simpler: run `tasklist`
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, text=True
            )
            if str(pid) in result.stdout:
                return pid
        else:
            os.kill(pid, 0)  # Unix
            return pid
    except (ValueError, ProcessLookupError, OSError, subprocess.SubprocessError):
        pass
    # Process not running → clean up stale PID file
    pid_path.unlink(missing_ok=True)
    return None

def start_app(app_name: str, app_path: Path, verbose: bool = False) -> bool:
    """Start the app in the background."""
    if is_running(app_name):
        print(f"App '{app_name}' is already running (PID {is_running(app_name)}).")
        return False

    log_path = log_file(app_name)
    pid_path = pid_file(app_name)

    try:
        with open(log_path, "a", encoding="utf-8") as log_f:
            # Determine creation flags
            creation_flags = 0
            preexec_fn = None
            if IS_WINDOWS:
                # Create a new process group so we can send CTRL_BREAK_EVENT
                creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                # Unix: start a new session (process group)
                preexec_fn = os.setsid

            proc = subprocess.Popen(
                ["uv", "run", "app.py"],
                cwd=app_path,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                creationflags=creation_flags,
                preexec_fn=preexec_fn,
                text=True,
            )

        pid_path.write_text(str(proc.pid))
        if verbose:
            print(f"Started {app_name} (PID {proc.pid}). Logs: {log_path}")
        else:
            print(f"Started {app_name}.")
        return True
    except Exception as e:
        print(f"Failed to start {app_name}: {e}")
        return False

def stop_app(app_name: str, verbose: bool = False) -> bool:
    """Stop the app gracefully, force kill if needed."""
    pid = is_running(app_name)
    if pid is None:
        print(f"App '{app_name}' is not running.")
        return False

    try:
        # Graceful termination
        if IS_WINDOWS:
            # Send CTRL_BREAK_EVENT (works on console apps created with CREATE_NEW_PROCESS_GROUP)
            os.kill(pid, signal.CTRL_BREAK_EVENT)
        else:
            # Send SIGTERM to the whole process group
            os.killpg(os.getpgid(pid), signal.SIGTERM)

        if verbose:
            print(f"Sent termination signal to {app_name} (PID {pid}).")

        # Wait for termination
        for _ in range(GRACEFUL_TIMEOUT * 2):
            if not is_running(app_name):
                break
            time.sleep(0.5)
        else:
            # Still running → force kill
            if IS_WINDOWS:
                subprocess.run(["taskkill", "/F", "/PID", str(pid)], check=False, capture_output=True)
            else:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            if verbose:
                print(f"Force killed {app_name}.")
            time.sleep(1)

        # Clean up PID file
        pid_file(app_name).unlink(missing_ok=True)
        print(f"Stopped {app_name}.")
        return True
    except Exception as e:
        print(f"Failed to stop {app_name}: {e}")
        pid_file(app_name).unlink(missing_ok=True)
        return False

# ========== LOG FUNCTIONS WITH ENCODING ERROR HANDLING ==========
def tail_log(app_name: str):
    """Tail the log file of a single app: show existing content then follow new lines."""
    log_path = log_file(app_name)
    if not log_path.exists():
        print(f"No log file for {app_name}.")
        return

    try:
        # Open with utf-8 and replace decoding errors
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            # Print existing content
            for line in f:
                print(line, end="")
            # Now follow new lines
            f.seek(0, os.SEEK_END)
            while True:
                line = f.readline()
                if not line:
                    time.sleep(0.1)
                    continue
                print(line, end="")
    except KeyboardInterrupt:
        pass

def tail_all_logs(apps: Dict[str, Path]):
    """Tail all log files concurrently, prefixing each line with the app name."""
    # Dictionary to store last read position for each app
    last_pos = {name: 0 for name in apps}
    missing_warned = set()

    try:
        while True:
            for name in apps:
                log_path = log_file(name)
                if not log_path.exists():
                    if name not in missing_warned:
                        print(f"[{name}] Log file not found (waiting...)")
                        missing_warned.add(name)
                    continue
                else:
                    missing_warned.discard(name)

                # Open and read new lines with encoding error handling
                try:
                    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                        f.seek(last_pos[name])
                        for line in f:
                            print(f"[{name}] {line.rstrip()}")
                        last_pos[name] = f.tell()
                except Exception as e:
                    # If file is temporarily locked or other error, just skip
                    pass
            time.sleep(0.1)  # Polling interval
    except KeyboardInterrupt:
        pass

# -------------------------------
# App discovery
# -------------------------------
def find_apps(base_dir: Path) -> Dict[str, Path]:
    """Scan for any subdirectory containing app.py."""
    apps = {}
    if not base_dir.is_dir():
        return apps
    for item in base_dir.iterdir():
        if item.is_dir() and (item / "app.py").exists():
            apps[item.name] = item.resolve()
    return apps

def show_status(apps: Dict[str, Path]):
    print("App Status")
    print("----------")
    for name, path in apps.items():
        pid = is_running(name)
        if pid:
            print(f"{name:20} RUNNING (PID {pid})")
        else:
            print(f"{name:20} STOPPED")
    print()

def list_apps(apps: Dict[str, Path]):
    print("Discovered apps:")
    for name, path in apps.items():
        print(f"  {name} -> {path}")

# -------------------------------
# CLI
# -------------------------------
def main():
    parser = argparse.ArgumentParser(description="Manage multiple uv‑run applications.")
    parser.add_argument("--base", "-b", type=Path, default=BASE_DIR,
                        help=f"Base directory containing app folders (default: {BASE_DIR})")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed output")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # start
    start_parser = subparsers.add_parser("start", help="Start an app")
    start_parser.add_argument("app", help="App name or 'all'")

    # stop
    stop_parser = subparsers.add_parser("stop", help="Stop an app")
    stop_parser.add_argument("app", help="App name or 'all'")

    # restart
    restart_parser = subparsers.add_parser("restart", help="Restart an app")
    restart_parser.add_argument("app", help="App name or 'all'")

    # status
    subparsers.add_parser("status", help="Show status of all apps")

    # list
    subparsers.add_parser("list", help="List discovered apps")

    # logs (accepts "all")
    logs_parser = subparsers.add_parser("logs", help="Tail the log file of an app (or all apps)")
    logs_parser.add_argument("app", help="App name or 'all'")

    args = parser.parse_args()

    # Resolve base directory
    base_dir = args.base.resolve()
    if not base_dir.is_dir():
        print(f"Error: Base directory '{base_dir}' does not exist.")
        sys.exit(1)

    apps = find_apps(base_dir)
    if not apps:
        print("No apps found (no subdirectory containing app.py).")
        sys.exit(1)

    def get_apps(app_arg):
        if app_arg == "all":
            return apps.items()
        if app_arg not in apps:
            print(f"Error: App '{app_arg}' not found.")
            sys.exit(1)
        return [(app_arg, apps[app_arg])]

    if args.command == "start":
        for name, path in get_apps(args.app):
            start_app(name, path, verbose=args.verbose)

    elif args.command == "stop":
        for name, _ in get_apps(args.app):
            stop_app(name, verbose=args.verbose)

    elif args.command == "restart":
        for name, path in get_apps(args.app):
            if stop_app(name, verbose=args.verbose):
                start_app(name, path, verbose=args.verbose)

    elif args.command == "status":
        show_status(apps)

    elif args.command == "list":
        list_apps(apps)

    elif args.command == "logs":
        if args.app == "all":
            tail_all_logs(apps)
        else:
            if args.app not in apps:
                print(f"Error: App '{args.app}' not found.")
                sys.exit(1)
            tail_log(args.app)

    else:
        parser.print_help()

if __name__ == "__main__":
    main()