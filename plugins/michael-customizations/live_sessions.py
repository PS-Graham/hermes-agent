"""Live Hermes session control helpers.

This module deliberately controls only tmux-managed Hermes processes. A plain interactive process
attached to a raw TTY is listed for visibility, but stdin injection into that TTY is not safe
enough for a first-class command.

tmux and ``ps -eo`` are POSIX tools: on native Windows nothing is controllable and ``list`` says so.
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

_TMUX_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.:@-]{1,80}$")


@dataclass(frozen=True)
class LiveProcess:
    pid: str
    tty: str
    state: str
    elapsed_seconds: str
    cwd: str
    command: str
    tmux_session: str = ""
    tmux_pane: str = ""

    @property
    def controllable(self) -> bool:
        return bool(self.tmux_session and self.tmux_pane)


def _run(args: List[str], *, check: bool = False) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(args, text=True, capture_output=True, check=check)
    except FileNotFoundError:
        if check:
            raise
        return subprocess.CompletedProcess(args, 127, "", f"{args[0]}: not found")


def _tmux_available() -> bool:
    return _run(["bash", "-lc", "command -v tmux >/dev/null 2>&1"]).returncode == 0


def _tmux_panes() -> List[dict[str, str]]:
    if not _tmux_available():
        return []
    fmt = "#{session_name}\t#{pane_id}\t#{pane_current_command}\t#{pane_current_path}"
    result = _run(["tmux", "list-panes", "-a", "-F", fmt])
    if result.returncode != 0:
        return []
    panes: List[dict[str, str]] = []
    for line in result.stdout.splitlines():
        parts = line.split("\t", 3)
        if len(parts) != 4:
            continue
        panes.append({
            "session": parts[0],
            "pane": parts[1],
            "command": parts[2],
            "cwd": parts[3],
        })
    return panes


def _tmux_process_index() -> dict[str, tuple[str, str]]:
    index: dict[str, tuple[str, str]] = {}
    for pane in _tmux_panes():
        result = _run([
            "tmux",
            "display-message",
            "-p",
            "-t",
            pane["pane"],
            "#{pane_pid}",
        ])
        if result.returncode != 0:
            continue
        pid = result.stdout.strip()
        if pid:
            index[pid] = (pane["session"], pane["pane"])
    return index


def _read_cwd(pid: str) -> str:
    try:
        return str(Path(f"/proc/{pid}/cwd").resolve())
    except Exception:
        return ""


def _iter_processes() -> Iterable[LiveProcess]:
    tmux_index = _tmux_process_index()
    result = _run(["ps", "-eo", "pid=,tty=,stat=,etimes=,args="])
    if result.returncode != 0:
        return []
    rows: list[LiveProcess] = []
    current_pid = str(os.getpid())
    for raw in result.stdout.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split(None, 4)
        if len(parts) < 5:
            continue
        pid, tty, state, elapsed, command = parts
        if pid == current_pid:
            continue
        if (
            "hermes_cli.main gateway run" not in command
            and "bin/hermes" not in command
            and not command.endswith(" hermes")
        ):
            continue
        if "live_sessions" in command or "tmux new-session" in command:
            continue
        tmux_session, tmux_pane = tmux_index.get(pid, ("", ""))
        rows.append(
            LiveProcess(
                pid=pid,
                tty=tty,
                state=state,
                elapsed_seconds=elapsed,
                cwd=_read_cwd(pid),
                command=command,
                tmux_session=tmux_session,
                tmux_pane=tmux_pane,
            )
        )
    return rows


def _print_table(rows: list[LiveProcess]) -> None:
    if not rows:
        print("No live Hermes processes found.")
        return
    print(f"{'PID':<8} {'Control':<11} {'Tmux':<18} {'TTY':<8} {'Age':<8} {'CWD'}")
    print("-" * 100)
    for row in rows:
        control = "tmux" if row.controllable else "read-only"
        tmux = row.tmux_session or "-"
        cwd = row.cwd or "-"
        print(
            f"{row.pid:<8} {control:<11} {tmux:<18} {row.tty:<8} {row.elapsed_seconds:<8} {cwd}"
        )
        print(f"  cmd: {row.command[:180]}")


def list_live(_: argparse.Namespace) -> int:
    rows = list(_iter_processes())
    if not rows and os.name == "nt" and not _tmux_available():
        print("tmux is not available on this machine, so live sessions cannot be listed or controlled.")
        return 0
    _print_table(rows)
    return 0


def _resolve_tmux_target(target: str) -> tuple[str, str]:
    matches = []
    for row in _iter_processes():
        if not row.controllable:
            continue
        if target in {
            row.pid,
            row.tmux_session,
            row.tmux_pane,
        } or row.tmux_session.startswith(target):
            matches.append(row)
    if not matches:
        raise SystemExit(f"No controllable tmux Hermes session matches '{target}'.")
    if len(matches) > 1:
        names = ", ".join(f"{m.tmux_session}({m.pid})" for m in matches)
        raise SystemExit(f"Ambiguous target '{target}': {names}")
    return matches[0].tmux_session, matches[0].tmux_pane


def send_message(args: argparse.Namespace) -> int:
    _, pane = _resolve_tmux_target(args.target)
    text = " ".join(args.text).strip()
    if not text:
        raise SystemExit("Message text is required.")
    _run(["tmux", "send-keys", "-t", pane, text, "Enter"], check=True)
    print(f"Sent to {args.target}.")
    return 0


def capture(args: argparse.Namespace) -> int:
    _, pane = _resolve_tmux_target(args.target)
    lines = str(max(1, args.lines))
    result = _run(["tmux", "capture-pane", "-t", pane, "-p", "-S", f"-{lines}"])
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip() or "tmux capture failed")
    print(result.stdout.rstrip())
    return 0


def start(args: argparse.Namespace) -> int:
    if not _tmux_available():
        raise SystemExit("tmux is required for managed live sessions.")
    name = args.name.strip()
    if not _TMUX_NAME_PATTERN.match(name):
        raise SystemExit(
            "Session name must be 1-80 chars: letters, numbers, '.', '_', ':', '@', '-'."
        )
    existing = _run(["tmux", "has-session", "-t", name])
    if existing.returncode == 0:
        raise SystemExit(f"tmux session '{name}' already exists.")
    hermes_executable = shutil.which("hermes") or "hermes"
    command = [hermes_executable]
    if args.resume:
        command.extend(["--resume", args.resume])
    elif args.continue_session:
        command.append("--continue")
    if args.worktree:
        command.append("--worktree")
    workdir = str(Path(args.cwd).expanduser().resolve()) if args.cwd else os.getcwd()
    tmux_command = shlex.join(["bash", "-lc", f"exec {shlex.join(command)}"])
    _run(
        ["tmux", "new-session", "-d", "-s", name, "-c", workdir, tmux_command],
        check=True,
    )
    print(f"Started tmux Hermes session '{name}'.")
    return 0


def attach(args: argparse.Namespace) -> int:
    session, _ = _resolve_tmux_target(args.target)
    os.execvp("tmux", ["tmux", "attach-session", "-t", session])
    return 0


def configure_parser(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="live_action")
    sub.add_parser(
        "list",
        aliases=["ls"],
        help="List live Hermes processes and controllable tmux sessions",
    ).set_defaults(live_func=list_live)
    start_parser = sub.add_parser(
        "start", help="Start a new controllable Hermes session in tmux"
    )
    start_parser.add_argument("name", help="tmux session name")
    start_parser.add_argument("--resume", help="Resume a persisted Hermes session ID")
    start_parser.add_argument(
        "--continue",
        dest="continue_session",
        action="store_true",
        help="Continue the most recent Hermes session",
    )
    start_parser.add_argument(
        "--worktree", action="store_true", help="Start Hermes in worktree mode"
    )
    start_parser.add_argument("--cwd", help="Working directory for the tmux session")
    start_parser.set_defaults(live_func=start)
    send_parser = sub.add_parser(
        "send", help="Send a message to a tmux-managed Hermes session"
    )
    send_parser.add_argument("target", help="tmux session name, pane ID, or Hermes PID")
    send_parser.add_argument("text", nargs="+", help="Message text")
    send_parser.set_defaults(live_func=send_message)
    capture_parser = sub.add_parser(
        "capture", help="Capture recent output from a tmux-managed Hermes session"
    )
    capture_parser.add_argument(
        "target", help="tmux session name, pane ID, or Hermes PID"
    )
    capture_parser.add_argument(
        "--lines", type=int, default=80, help="Lines to capture, default 80"
    )
    capture_parser.set_defaults(live_func=capture)
    attach_parser = sub.add_parser(
        "attach", help="Attach to a tmux-managed Hermes session"
    )
    attach_parser.add_argument(
        "target", help="tmux session name, pane ID, or Hermes PID"
    )
    attach_parser.set_defaults(live_func=attach)


def dispatch(args: argparse.Namespace) -> int:
    return int(getattr(args, "live_func", list_live)(args) or 0)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hermes live",
        description="Inspect and control tmux-managed live Hermes sessions",
    )
    configure_parser(parser)
    return dispatch(parser.parse_args(argv))
