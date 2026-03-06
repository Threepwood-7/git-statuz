# git-statuz

A PySide6 desktop viewer for Git repository status, commit history, and diffs. Windows-first, with WinMerge integration for external diff comparison.

## Table of Contents

- [Features](#features)
- [UI Walkthrough](#ui-walkthrough)
- [Requirements](#requirements)
- [Installation](#installation)
- [Usage](#usage)
- [Configuration](#configuration)
- [Keyboard Shortcuts](#keyboard-shortcuts)
- [Menus](#menus)
- [Project Structure](#project-structure)
- [Architecture](#architecture)
- [Development](#development)
- [Troubleshooting](#troubleshooting)
- [Legal Disclaimer](#legal-disclaimer)

## Features

- **Repository status tree** - hierarchical view of modified, staged, untracked, ignored, conflicted, and deleted files, color-coded by status
- **Branch and tracking info** - current branch, detached HEAD state, upstream tracking, ahead/behind commit counts
- **Commit history** - repository-wide and per-file commit history (SHA, date, author, subject)
- **Diff viewer** - working tree and staged diffs displayed separately, with syntax highlighting for git diff output
- **File content preview** - text and binary file previews (up to 512KB), hex dumps for binary files
- **Multi-repository support** - recently accessed repositories stored in settings; open multiple instances
- **External diff launcher** - double-click files to open in WinMerge (Windows) or default system editor
- **Tree navigation** - expand/collapse directory levels (+1/+2 or -1/-2)
- **Filter controls** - toggle untracked and ignored files visibility to focus on actionable changes

## UI Walkthrough

1. Open a repository and review the status snapshot.

   ![Review repository snapshot](docs/images/ui-01-overview.png)

   Overview of changed files, branch context, and current repository health.

2. Inspect a selected file with commit history and diff details.

   ![Inspect history and diff](docs/images/ui-02-workflow.png)

   Workflow state for drilling into a file's evolution before acting.

3. Apply filters to triage noisy change sets.

   ![Apply triage filters](docs/images/ui-03-details.png)

   Focused view for prioritizing actionable files and reducing review noise.

## Requirements

- **Windows** (10 or later; also works on Linux/macOS via PySide6)
- **Python 3.13+**
- **Git** command-line tool installed and available in PATH
- **WinMerge** (optional, Windows) - for external diff comparison

Runtime dependency: `PySide6 >=6.10.2`.

## Installation

### First-time Setup

```bat
python scripts\windows\setup_env.py
```

Creates the `.venv` by running `uv sync --locked` (falls back to `uv sync` if no lockfile).

Manual alternative for development:

```bat
uv sync --group dev
```

## Usage

### Recommended (console-less)

```bat
pyw scripts\windows\run_app_gui.pyw
```

Launches the GUI without a console window. Auto-bootstraps the `.venv` via `setup_env.py` if not yet created.

### With console

```bat
python scripts\windows\run_app.py
```

Runs via `hatch run python -m git_statuz`. Requires `hatch` in PATH.

### Direct

```bat
python -m git_statuz
:: or, after installation:
git-statuz
```

### Command-line Options

```text
-i PATH, --input PATH          Path inside git working tree (defaults to current directory)
--winmerge PATH                Explicit path to WinMergeU.exe (auto-detected if omitted)
--history-limit N              Number of commit history rows to load (default: 30)
-h, --help                     Show help message and exit
```

### Examples

```bat
git-statuz
git-statuz -i D:\repos\myproject
git-statuz --history-limit 50
git-statuz -i D:\repos\myproject --winmerge "C:\Program Files\WinMerge\WinMergeU.exe"
```

## Configuration

Runtime settings are stored via QSettings:

- Backend: `QSettings(IniFormat, UserScope, "gitstatuz", "gitstatuz")`
- No config files or environment variables required.

### Persisted Settings

| Key | Description |
|---|---|
| `ui/tree_column_widths` | Last used column widths in file tree |
| `ui/history_column_widths` | History table column widths |
| `ui/main_splitter_sizes` | Main splitter proportions |
| `ui/right_splitter_sizes` | Right panel splitter proportions |
| `ui/show_untracked` | Toggle for untracked files visibility |
| `ui/show_ignored` | Toggle for ignored files visibility |
| `recent/paths` | List of recently opened repository paths (max 10) |

## Keyboard Shortcuts

| Key | Action |
|---|---|
| F5 | Refresh repository snapshot and diffs |
| Alt+X | Exit application |

## Menus

**Files**:
- **Open Directory...** - Browse and open a git repository in a new instance
- **Recents** - Submenu with up to 10 recently opened repository paths
- **Exit** (Alt+X)

## Project Structure

```text
git-statuz/
|-- pyproject.toml
|-- uv.lock
|-- src/
|   `-- git_statuz/
|       |-- __init__.py
|       |-- __main__.py              # Entry point (imports cli.main)
|       |-- cli.py                   # Argument parsing, app initialization
|       |-- models.py                # Dataclasses: BranchStatus, FileStatus, CommitEntry, etc.
|       |-- git_adapter.py           # Git command execution and output parsing
|       |-- services/
|       |   `-- diff_launcher.py     # Platform-specific diff/editor launching
|       `-- ui/
|           |-- main_window.py       # Main GUI: layout, events, worker orchestration
|           |-- tree_model.py        # Qt tree model for file status display
|           |-- history_model.py     # Qt table model for commit history
|           `-- diff_highlighter.py  # Syntax highlighting for diff output
|-- scripts/
|   |-- policy/
|   |   `-- check_standard.py
|   `-- windows/
|       |-- setup_env.py              # Create/verify .venv via uv sync
|       |-- run_app.py               # Launch app via hatch run
|       |-- run_app_gui.pyw          # Launch GUI without console window
|       `-- run_tests.py             # Run tests via hatch run test
|-- tests/
|   `-- ...                          # pytest suite with pytest-qt
`-- .pre-commit-config.yaml
```

## Architecture

- `src/` layout with `git_statuz` package.
- `cli.py` handles argument parsing and `QApplication` setup.
- `GitAdapter` wraps `git` subprocess calls and parses status/log/diff output.
- Background operations use `QThreadPool.globalInstance()` with custom `_FunctionWorker(QRunnable)` wrappers and signal-based completion callbacks.
- `ui/` contains the main window, tree/history models, and diff syntax highlighter.
- `services/diff_launcher.py` provides platform-aware file opening (WinMerge on Windows, `xdg-open` on Linux/macOS, `os.startfile()` fallback).
- Temporary diff files are cleaned up via `atexit` hooks.

## Development

### Windows Helpers

| Script | Description |
|---|---|
| `python scripts\windows\setup_env.py` | Create/verify `.venv` via `uv sync --locked` |
| `pyw scripts\windows\run_app_gui.pyw` | Launch GUI without console window (auto-bootstraps venv) |
| `python scripts\windows\run_app.py` | Launch app via `hatch run` (requires hatch in PATH) |
| `python scripts\windows\run_tests.py` | Run test suite via `hatch run test` |

### Testing

```bat
hatch run test
```

### Quality Checks

```bat
hatch run lint:all
hatch run test-cov
```

Individual checks:

```bat
hatch run lint:check
hatch run lint:fmt
hatch run lint:types
hatch run lint:policy
```

### Lockfile Workflow

```bat
uv lock
uv lock --check
```

`uv lock` must be run whenever dependencies change, and the updated `uv.lock` must be committed.

## Troubleshooting

### Git not found

Ensure `git` is installed and available in PATH:

```bat
git --version
```

### Not a git repository

If the specified path is not inside a git working tree, the app exits with an error message at startup. Verify the path contains a `.git` directory.

### WinMerge not detected

The app searches for `WinMergeU.exe` in: provided `--winmerge` path, system PATH, then default install locations. If not found, double-clicking files falls back to the system default editor.

### Settings corruption

Invalid column widths or splitter sizes are automatically reset to defaults. Delete the QSettings INI file to fully reset all settings.

### Large repositories

- File content preview is capped at 512KB.
- History is limited to 30 commits by default (override with `--history-limit`).
- Tree expand/collapse operations can be slow on very large repositories.

---

<!-- legal-disclaimer:start -->
## Legal Disclaimer

THIS SOFTWARE IS PROVIDED "AS IS" AND "AS AVAILABLE," WITHOUT WARRANTIES OF ANY KIND, WHETHER EXPRESS, IMPLIED, STATUTORY, OR OTHERWISE, INCLUDING, WITHOUT LIMITATION, ANY IMPLIED WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, TITLE, NON-INFRINGEMENT, ACCURACY, OR QUIET ENJOYMENT. TO THE MAXIMUM EXTENT PERMITTED BY APPLICABLE LAW, THE AUTHORS, CONTRIBUTORS, MAINTAINERS, DISTRIBUTORS, AND AFFILIATED PARTIES SHALL NOT BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, EXEMPLARY, OR PUNITIVE DAMAGES, OR FOR ANY LOSS OF DATA, PROFITS, GOODWILL, BUSINESS OPPORTUNITY, OR SERVICE INTERRUPTION, ARISING OUT OF OR RELATING TO THE USE OF, OR INABILITY TO USE, THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGES. THIS SOFTWARE HAS BEEN DEVELOPED, IN WHOLE OR IN PART, BY "INTELLIGENT TOOLS"; ACCORDINGLY, OUTPUTS MAY CONTAIN ERRORS OR OMISSIONS, AND YOU ASSUME FULL RESPONSIBILITY FOR INDEPENDENT VALIDATION, TESTING, LEGAL COMPLIANCE, AND SAFE OPERATION PRIOR TO ANY RELIANCE OR DEPLOYMENT.
<!-- legal-disclaimer:end -->
