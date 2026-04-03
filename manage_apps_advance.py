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
import shutil
from pathlib import Path
from typing import Dict, Optional, List, Tuple
from datetime import datetime

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
BACKUP_DIR = DATA_DIR / "backups"  # New directory for backups

# Create directories if they don't exist
LOG_DIR.mkdir(parents=True, exist_ok=True)
PID_DIR.mkdir(parents=True, exist_ok=True)
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

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

# ========== GIT PULL FUNCTIONALITY WITH CONFLICT HANDLING ==========
def backup_file(file_path: Path, app_name: str, app_path: Path) -> Optional[Path]:
    """Create a backup of a file before overwriting with clean filename."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Get relative path from app directory
    try:
        rel_path = file_path.relative_to(app_path)
    except ValueError:
        # If for some reason the file is outside app_path, use absolute path
        rel_path = file_path
    
    # Create a safe filename by replacing path separators
    safe_name = str(rel_path).replace('\\', '_').replace('/', '_')
    
    # Remove any problematic characters for Windows filenames
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        safe_name = safe_name.replace(char, '_')
    
    # Limit filename length (Windows has 255 char limit, but keep reasonable)
    if len(safe_name) > 150:
        # Keep file extension
        name_parts = safe_name.rsplit('.', 1)
        if len(name_parts) == 2:
            ext = name_parts[1]
            safe_name = safe_name[:140] + '...' + ext
        else:
            safe_name = safe_name[:147] + '...'
    
    backup_name = f"{app_name}_{safe_name}_{timestamp}"
    backup_path = BACKUP_DIR / backup_name
    
    # Ensure backup directory exists
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    
    try:
        # Copy the file with metadata preservation
        shutil.copy2(file_path, backup_path)
        
        # Verify backup was created
        if backup_path.exists():
            return backup_path
        else:
            return None
    except Exception as e:
        print(f"      ❌ Failed to backup {file_path.name}: {e}")
        return None

def get_conflicting_files(app_path: Path) -> List[Path]:
    """Get list of files that would conflict during git pull."""
    try:
        # Get list of modified files
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=app_path,
            capture_output=True,
            text=True,
            timeout=10
        )
        
        conflicting_files = []
        for line in result.stdout.split('\n'):
            if line.strip():
                status = line[:2]
                filename = line[3:].strip()
                
                # Modified files
                if status in [' M', 'MM', 'AM', ' M']:
                    file_path = app_path / filename
                    if file_path.exists():
                        conflicting_files.append(file_path)
                
                # Untracked files that exist in repo
                elif status == '??':
                    # Check if this file exists in git
                    check_result = subprocess.run(
                        ["git", "ls-tree", "HEAD", filename],
                        cwd=app_path,
                        capture_output=True,
                        text=True
                    )
                    if check_result.returncode == 0:
                        file_path = app_path / filename
                        if file_path.exists():
                            conflicting_files.append(file_path)
        
        return conflicting_files
    except Exception:
        return []

def git_pull_with_strategy(app_name: str, app_path: Path, strategy: str, verbose: bool = False) -> bool:
    """
    Perform git pull with specified conflict resolution strategy.
    
    Strategies:
    - 'skip': Skip update if there are conflicts
    - 'backup': Backup conflicting files, then pull
    - 'overwrite': Overwrite local changes without backup
    """
    # Check if .git directory exists
    git_dir = app_path / ".git"
    if not git_dir.exists():
        print(f"Error: '{app_name}' is not a git repository (no .git directory found).")
        return False
    
    # Check for conflicting files
    conflicting_files = get_conflicting_files(app_path)
    
    if conflicting_files and strategy != 'overwrite':
        print(f"\n  ⚠️  Found {len(conflicting_files)} file(s) with local changes in '{app_name}':")
        for f in conflicting_files[:10]:  # Show first 10
            try:
                rel_path = f.relative_to(app_path)
                print(f"      - {rel_path}")
            except:
                print(f"      - {f.name}")
        if len(conflicting_files) > 10:
            print(f"      ... and {len(conflicting_files) - 10} more")
    
    try:
        # Check current branch before pull
        if verbose:
            branch_result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=app_path,
                capture_output=True,
                text=True,
                timeout=10
            )
            if branch_result.returncode == 0:
                current_branch = branch_result.stdout.strip()
                print(f"  Current branch: {current_branch}")
        
        # Handle conflicts based on strategy
        if strategy == 'skip' and conflicting_files:
            print(f"\n  ⏭️  Skipping update for '{app_name}' due to {len(conflicting_files)} local change(s)")
            print(f"  Use --strategy backup or --strategy overwrite to update, or resolve conflicts manually")
            return False
        
        elif strategy == 'backup' and conflicting_files:
            print(f"\n  💾 Backing up {len(conflicting_files)} file(s) before update...")
            backups = []
            success_count = 0
            
            for file_path in conflicting_files:
                if file_path.exists():
                    backup_path = backup_file(file_path, app_name, app_path)
                    if backup_path:
                        try:
                            rel_path = file_path.relative_to(app_path)
                            print(f"      ✓ Backed up: {rel_path}")
                        except:
                            print(f"      ✓ Backed up: {file_path.name}")
                        backups.append((file_path, backup_path))
                        success_count += 1
                    else:
                        try:
                            rel_path = file_path.relative_to(app_path)
                            print(f"      ✗ Failed to backup: {rel_path}")
                        except:
                            print(f"      ✗ Failed to backup: {file_path.name}")
            
            if success_count == 0:
                print(f"  ❌ No files were backed up. Aborting update.")
                return False
            
            # Stash changes to allow pull (using a unique stash message)
            stash_message = f"auto-stash-{app_name}-{datetime.now().timestamp()}"
            stash_result = subprocess.run(
                ["git", "stash", "push", "--include-untracked", "-m", stash_message],
                cwd=app_path,
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if stash_result.returncode != 0:
                print(f"  ⚠️  Could not stash changes, but continuing with pull...")
            
            # Perform pull
            print(f"  📥 Pulling updates from repository...")
            pull_result = subprocess.run(
                ["git", "pull"],
                cwd=app_path,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            # Try to apply stash back
            if pull_result.returncode == 0:
                unstash_result = subprocess.run(
                    ["git", "stash", "pop"],
                    cwd=app_path,
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
                if unstash_result.returncode != 0:
                    print(f"  ⚠️  Could not re-apply local changes. They are saved in stash.")
                    print(f"      To recover: cd {app_path} && git stash pop")
                else:
                    print(f"  ✅ Re-applied local changes successfully")
                
                print(f"\n  ✅ Successfully updated '{app_name}'")
                if backups:
                    backup_dir_display = BACKUP_DIR.resolve()
                    print(f"  💾 Backups saved to: {backup_dir_display}")
                    print(f"     Total {len(backups)} file(s) backed up")
                return True
            else:
                # Restore from backup if pull failed
                print(f"  ❌ Pull failed!")
                print(f"  Error: {pull_result.stderr}")
                print(f"  Restoring from backup...")
                
                # Try to restore stash
                subprocess.run(["git", "stash", "pop"], cwd=app_path, capture_output=True)
                return False
        
        elif strategy == 'overwrite':
            if conflicting_files:
                print(f"\n  ⚠️  Overwriting {len(conflicting_files)} local file(s)...")
            
            # Force reset to discard local changes
            reset_result = subprocess.run(
                ["git", "reset", "--hard", "HEAD"],
                cwd=app_path,
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if reset_result.returncode != 0:
                print(f"  ❌ Failed to reset local changes")
                return False
            
            # Clean untracked files
            clean_result = subprocess.run(
                ["git", "clean", "-fd"],
                cwd=app_path,
                capture_output=True,
                text=True,
                timeout=10
            )
            
            # Perform pull
            print(f"  📥 Pulling updates from repository...")
            pull_result = subprocess.run(
                ["git", "pull"],
                cwd=app_path,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if pull_result.returncode == 0:
                if "Already up to date" in pull_result.stdout:
                    print(f"  ✓ '{app_name}' was already up to date")
                else:
                    print(f"  ✅ Successfully updated '{app_name}' (local changes overwritten)")
                    if verbose and pull_result.stdout:
                        lines = pull_result.stdout.strip().split('\n')[-3:]
                        for line in lines:
                            if line.strip():
                                print(f"      {line}")
                return True
            else:
                print(f"  ❌ Failed to pull '{app_name}'")
                if pull_result.stderr:
                    print(f"      {pull_result.stderr}")
                return False
        
        else:  # No conflicts or default pull
            print(f"  📥 Pulling updates from repository...")
            result = subprocess.run(
                ["git", "pull"],
                cwd=app_path,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode == 0:
                if "Already up to date" in result.stdout or "Already up to date" in result.stderr:
                    print(f"  ✓ '{app_name}' is already up to date.")
                else:
                    print(f"  ✅ Successfully updated '{app_name}'")
                    if verbose and result.stdout:
                        lines = result.stdout.strip().split('\n')[-3:]
                        for line in lines:
                            if line.strip():
                                print(f"      {line}")
                return True
            else:
                print(f"  ❌ Failed to pull '{app_name}':")
                if result.stderr:
                    print(f"      {result.stderr}")
                
                # Suggest using backup strategy if there are conflicts
                if "would be overwritten by merge" in result.stderr:
                    print(f"\n  💡 Tip: Use --strategy backup to backup your changes before pulling")
                    print(f"     Example: python manage_apps.py git-pull {app_name} --strategy backup")
                
                return False
            
    except subprocess.TimeoutExpired:
        print(f"  ❌ Git pull timed out for '{app_name}' after 60 seconds.")
        return False
    except FileNotFoundError:
        print(f"  ❌ 'git' command not found. Please ensure Git is installed and in PATH.")
        return False
    except Exception as e:
        print(f"  ❌ Unexpected error: {e}")
        return False

def git_pull_all(apps: Dict[str, Path], strategy: str, verbose: bool = False) -> Dict[str, bool]:
    """
    Perform git pull on all apps with specified strategy.
    """
    results = {}
    print(f"\n{'='*70}")
    print(f"Updating all applications via git pull")
    print(f"Strategy: {strategy.upper()}")
    print(f"{'='*70}")
    
    for name, path in apps.items():
        print(f"\n📦 [{name}]")
        success = git_pull_with_strategy(name, path, strategy, verbose)
        results[name] = success
    
    # Summary
    print(f"\n{'='*70}")
    print("Update Summary:")
    print(f"{'='*70}")
    success_count = sum(1 for v in results.values() if v)
    total_count = len(results)
    print(f"✅ Successful: {success_count}/{total_count}")
    print(f"❌ Failed: {total_count - success_count}/{total_count}")
    
    if success_count < total_count:
        print("\n❌ Failed apps:")
        for name, success in results.items():
            if not success:
                print(f"  - {name}")
    
    return results

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
    
    # git pull with strategies
    git_parser = subparsers.add_parser("git-pull", help="Update app code via git pull with conflict resolution")
    git_parser.add_argument("app", help="App name or 'all'")
    git_parser.add_argument("--strategy", "-s", choices=['skip', 'backup', 'overwrite'], 
                           default='skip', 
                           help="Conflict resolution strategy: skip (default), backup, or overwrite")

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
    
    # Git pull with strategy
    elif args.command == "git-pull":
        if args.app == "all":
            git_pull_all(apps, strategy=args.strategy, verbose=args.verbose)
        else:
            for name, path in get_apps(args.app):
                git_pull_with_strategy(name, path, strategy=args.strategy, verbose=args.verbose)

    else:
        parser.print_help()

if __name__ == "__main__":
    main()
