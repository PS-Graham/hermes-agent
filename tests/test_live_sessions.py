from __future__ import annotations

import subprocess

import pytest

from hermes_cli import live_sessions


def completed(
    stdout: str = "", returncode: int = 0
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=""
    )


def test_live_list_marks_plain_tty_sessions_read_only(monkeypatch, capsys):
    monkeypatch.setattr(live_sessions, "_tmux_process_index", lambda: {})
    monkeypatch.setattr(live_sessions, "_read_cwd", lambda pid: "/work")

    def fake_run(args, *, check=False):
        if args[:2] == ["ps", "-eo"]:
            return completed(
                "123 pts/3 Sl+ 42 /home/me/.local/bin/hermes --resume abc\n"
            )
        return completed(returncode=1)

    monkeypatch.setattr(live_sessions, "_run", fake_run)

    assert live_sessions.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "123" in out
    assert "read-only" in out


def test_send_refuses_non_tmux_target(monkeypatch):
    monkeypatch.setattr(
        live_sessions,
        "_iter_processes",
        lambda: [
            live_sessions.LiveProcess(
                pid="123",
                tty="pts/3",
                state="S",
                elapsed_seconds="1",
                cwd="/work",
                command="hermes",
            )
        ],
    )

    with pytest.raises(SystemExit, match="No controllable tmux Hermes session"):
        live_sessions.main(["send", "123", "hello"])


def test_start_rejects_unsafe_tmux_name(monkeypatch):
    monkeypatch.setattr(live_sessions, "_tmux_available", lambda: True)

    with pytest.raises(SystemExit, match="Session name"):
        live_sessions.main(["start", "bad name;rm"])


def test_start_honors_cwd_option_after_name(monkeypatch):
    calls = []
    monkeypatch.setattr(live_sessions, "_tmux_available", lambda: True)
    monkeypatch.setattr(
        live_sessions.shutil, "which", lambda name: "/usr/local/bin/hermes"
    )

    def fake_run(args, *, check=False):
        calls.append(args)
        if args[:3] == ["tmux", "has-session", "-t"]:
            return completed(returncode=1)
        return completed()

    monkeypatch.setattr(live_sessions, "_run", fake_run)

    assert live_sessions.main(["start", "agent", "--cwd", "/tmp"]) == 0
    assert calls[-1][:7] == ["tmux", "new-session", "-d", "-s", "agent", "-c", "/tmp"]
    assert "--cwd" not in calls[-1][-1]


def test_capture_uses_resolved_tmux_pane(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(
        live_sessions,
        "_iter_processes",
        lambda: [
            live_sessions.LiveProcess(
                pid="123",
                tty="pts/3",
                state="S",
                elapsed_seconds="1",
                cwd="/work",
                command="hermes",
                tmux_session="agent1",
                tmux_pane="%7",
            )
        ],
    )

    def fake_run(args, *, check=False):
        calls.append(args)
        return completed("recent output\n")

    monkeypatch.setattr(live_sessions, "_run", fake_run)

    assert live_sessions.main(["capture", "agent1", "--lines", "5"]) == 0
    assert calls == [["tmux", "capture-pane", "-t", "%7", "-p", "-S", "-5"]]
    assert "recent output" in capsys.readouterr().out
