# Multi‑App Manager for `uv run app.py`

A cross‑platform process manager that starts, stops, and monitors multiple Openalgo Python applications, each located in a separate subdirectory and launched with `uv run app.py`. All output is automatically saved to per‑app log files, and you can view logs on‑demand.

---

## Features

- **Start / Stop / Restart** individual apps or all apps at once
- **Status** – quickly see which apps are running and their PIDs
- **List** – show all discovered apps and their paths
- **Logs** – tail the log file of a single app or all apps simultaneously
- **Cross‑platform** – works on Windows (using `tasklist` and `CTRL_BREAK_EVENT`) and Unix‑like systems (using process groups and `SIGTERM`)
- **Clean state** – PID files are automatically cleaned when a process is no longer running
- **Configurable base directory** – look for app folders in any location via `--base`
- **Verbose mode** – get extra details during start/stop operations

---

## How It Works

The manager scans a **base directory** (default: current working directory) for subfolders that contain an `app.py` file. Each such subfolder is considered an app. When you start an app, the manager:

1. Checks if it’s already running (via PID file and process list).
2. Launches `uv run app.py` in the app’s folder, redirecting `stdout` and `stderr` to a dedicated log file (located in `.app_data/logs/`).
3. Stores the process ID in a PID file (`.app_data/pids/`).

When stopping an app, the manager:
- Sends a graceful termination signal (`CTRL_BREAK_EVENT` on Windows, `SIGTERM` to the whole process group on Unix).
- Waits up to 5 seconds for the process to exit.
- If it’s still alive, forces termination (`taskkill /F` on Windows, `SIGKILL` on Unix).
- Removes the PID file.

The log tailing functionality (`logs`) shows existing content first and then follows new lines (like `tail -f`). The `logs all` command polls all log files every 0.1 seconds and prints new lines with a `[appname]` prefix.

---

## Installation

1. Make sure you have **Python 3.6+** and **uv** installed (`pip install uv`).
2. Place `manage_apps.py` in the directory **above** your app folders, or set the `OPENALGO_BASE` environment variable to point to the folder containing your apps.
3. Ensure each app subfolder contains an `app.py` file that can be run with `uv run app.py`.

No other dependencies are required – everything uses the Python standard library.

---

## Usage

All commands are executed with:

```bash
uv run manage_apps.py <command> [options]
```

### Commands

| Command                 | Description                                                                                     |
|-------------------------|-------------------------------------------------------------------------------------------------|
| `start <app\|all>`      | Start one app or all apps. If an app is already running, it prints a message and does nothing.  |
| `stop <app\|all>`       | Stop one app or all apps gracefully (force‑kill after 5 seconds).                               |
| `restart <app\|all>`    | Stop and then start the specified app(s).                                                       |
| `status`                | Show the running status and PID (if any) for all discovered apps.                               |
| `list`                  | List all discovered apps and their full paths.                                                  |
| `logs <app\|all>`       | Tail the log file of a specific app or all apps. Press `Ctrl+C` to exit.                        |
| `git-pull <app\|all>`   | Update the code of the specified app(s). (Only works for manage_apps_advance.py file code)      |

### Options

| Option               | Description                                                                                   |
|----------------------|-----------------------------------------------------------------------------------------------|
| `--base DIR`, `-b DIR` | Base directory where app folders are located (default: current working directory).            |
| `--verbose`, `-v`    | Show detailed information (e.g., PID when starting, force‑kill message when stopping).        |

---

## Examples

### 1. Basic usage

```bash
# List all discovered apps
uv run manage_apps.py list

# Start any single apps
uv run manage_apps.py start myapp

OR

# Start all apps
uv run manage_apps.py start all

# Check status
uv run manage_apps.py status

# Stop a single app
uv run manage_apps.py stop myapp

OR

# Stop all apps
uv run manage_apps.py stop all

# Restart a single app
uv run manage_apps.py restart myapp

OR

# Restart all apps
uv run manage_apps.py restart all
```

### 2. Viewing logs

```bash
# Tail logs of a single app
uv run manage_apps.py logs myapp

# Tail logs of all apps (with prefixes)
uv run manage_apps.py logs all
```

### 3. Using a different base directory

If your apps are not in the current directory, point to them:

```bash
uv run manage_apps.py --base /path/to/apps start all
```

### 4. Verbose output

```bash
uv run manage_apps.py --verbose start myapp
```

This will print the PID and the log file path.

### 5. Suppressing output entirely (silent mode)

If you want to hide the manager’s own messages (e.g., in scripts), redirect stdout and stderr:

**Windows:**
```bash
uv run manage_apps.py start all > nul 2>&1
```

**Unix / Linux / macOS:**
```bash
uv run manage_apps.py start all > /dev/null 2>&1
```

### 6. Advance commands to update the codes of each app using manage_apps_advance.py file.

If you want to the code of any or all apps from the github:

```bash
# Skip strategy (default) - safe, no changes if conflicts
python manage_apps_advance.py git-pull openalgo2
python manage_apps_advance.py git-pull openalgo2 --strategy skip

# Backup strategy - backup conflicts, then update
python manage_apps_advance.py git-pull openalgo2 --strategy backup
python manage_apps_advance.py -v git-pull all --strategy backup

# Overwrite strategy - force overwrite local changes
python manage_apps_advance.py git-pull openalgo2 --strategy overwrite
python manage_apps_advance.py -v git-pull all --strategy overwrite
```

*Note:* The apps’ logs are still written to their respective log files; only the manager’s console output is suppressed.

---

## File Structure

When you run the manager for the first time, it creates a hidden folder `.app_data` in the same directory as `manage_apps.py`:

```
.
├── manage_apps.py
├── .app_data/
│   ├── logs/
│   │   ├── myapp.log
│   │   └── otherapp.log
│   └── pids/
│       ├── myapp.pid
│       └── otherapp.pid
└── myapp/                 # your app folder
    └── app.py
```

- **Logs** – Contains all output (stdout + stderr) from each app.
- **PID files** – Store the process ID of the running app; they are automatically removed when the app stops.

---

## Environment Variables

You can override the base directory and state directory using environment variables (useful for scripting):

- `OPENALGO_BASE` – Base directory containing app folders.
- `OPENALGO_STATE` – Directory where logs and PID files are stored (default is `~/.openalgo_manager`). If you set this, the manager will use that location instead of the `.app_data` folder.

*Note:* If both the environment variable and the `--base` option are provided, the command‑line option takes precedence.

---

## Advanced Notes

### How the Manager Detects Running Processes

- **Unix:** Uses `os.kill(pid, 0)` to check if the process exists.
- **Windows:** Runs `tasklist /FI "PID eq <pid>"` and looks for the PID in the output.  
  *Potential limitation:* If the PID appears as part of another number (e.g., 1234 is a substring of 12345), it might be a false positive – but this is extremely unlikely because `tasklist` formats output in columns.

### Graceful Shutdown

- **Unix:** Sends `SIGTERM` to the whole **process group** (using `os.killpg`) so that child processes also receive the signal.
- **Windows:** Sends `CTRL_BREAK_EVENT` – this only works for console applications that were started with `CREATE_NEW_PROCESS_GROUP`. If the app is a GUI application, it will fall back to `taskkill /F` after 5 seconds.

### Log Encoding

Log files are opened with `encoding="utf-8"` and `errors="replace"`. Any invalid UTF‑8 bytes are replaced with the `�` character, ensuring the manager never crashes due to encoding issues.

### Tail‑All Implementation

The `logs all` command polls all log files every 0.1 seconds. This is simple, cross‑platform, and works well for a small number of apps. For very high‑frequency logging, you may notice a slight delay, but it remains functional.

---

## Troubleshooting

| Problem                                      | Solution                                                                                             |
|----------------------------------------------|------------------------------------------------------------------------------------------------------|
| `App 'myapp' not found.`                     | Make sure the app’s folder contains an `app.py` file and that you’re using the correct base directory. |
| `Failed to start myapp: [Errno 2] No such file or directory: 'uv'` | Ensure `uv` is installed and in your PATH. Run `uv --version` to verify.                             |
| Log files are empty or missing                | Check that the app actually produces output. If it does, verify that the log file location is writable. |
| `UnicodeDecodeError` when viewing logs       | The script now uses `errors="replace"` – upgrade to the latest version of the script.                |
| App won’t stop gracefully                     | Some apps may ignore termination signals. The manager will force‑kill after 5 seconds. You can adjust `GRACEFUL_TIMEOUT` in the script. |
| `logs all` shows “Log file not found (waiting...)” | The app hasn’t created its log file yet (maybe it’s not running). Once it starts, the message will disappear. |

---

## License

This script is provided “as is”, without warranty of any kind. You are free to use, modify, and distribute it under the terms of the MIT License (or your preferred open‑source license).

---

## Contributing

Feel free to open issues or pull requests for improvements. Some ideas:
- Add a configuration file to set per‑app timeouts.
- Implement log rotation to prevent large log files.
- Add a `--clean` command to remove old logs.
- Use `psutil` for more robust process checks (optional).

Happy managing!
