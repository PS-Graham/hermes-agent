from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PLUGIN_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def plugin():
    spec = importlib.util.spec_from_file_location(
        "michael_customizations", PLUGIN_DIR / "__init__.py",
        submodule_search_locations=[str(PLUGIN_DIR)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def live(plugin):
    return plugin.live_sessions


@pytest.fixture
def review(plugin):
    return plugin.pre_compaction_review


def completed(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


def test_live_list_marks_plain_tty_sessions_read_only(live, monkeypatch, capsys):
    monkeypatch.setattr(live, "_tmux_process_index", lambda: {})
    monkeypatch.setattr(live, "_read_cwd", lambda pid: "/work")
    monkeypatch.setattr(live, "_run", lambda args, *, check=False: (
        completed("123 pts/3 Sl+ 42 /home/me/.local/bin/hermes --resume abc\n")
        if args[:2] == ["ps", "-eo"] else completed(returncode=1)))

    assert live.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "123" in out and "read-only" in out


def test_send_refuses_non_tmux_target(live, monkeypatch):
    monkeypatch.setattr(live, "_iter_processes", lambda: [live.LiveProcess(
        pid="123", tty="pts/3", state="S", elapsed_seconds="1", cwd="/work", command="hermes")])
    with pytest.raises(SystemExit, match="No controllable tmux Hermes session"):
        live.main(["send", "123", "hello"])


def test_start_rejects_unsafe_tmux_name(live, monkeypatch):
    monkeypatch.setattr(live, "_tmux_available", lambda: True)
    with pytest.raises(SystemExit, match="Session name"):
        live.main(["start", "bad name;rm"])


def test_start_honors_cwd_option_after_name(live, monkeypatch):
    calls = []
    monkeypatch.setattr(live, "_tmux_available", lambda: True)
    monkeypatch.setattr(live.shutil, "which", lambda name: "/usr/local/bin/hermes")

    def fake_run(args, *, check=False):
        calls.append(args)
        return completed(returncode=1 if args[:3] == ["tmux", "has-session", "-t"] else 0)

    monkeypatch.setattr(live, "_run", fake_run)
    cwd = str(Path.cwd())
    assert live.main(["start", "agent", "--cwd", cwd]) == 0
    assert calls[-1][:7] == ["tmux", "new-session", "-d", "-s", "agent", "-c", cwd]
    assert "--cwd" not in calls[-1][-1]


def test_capture_uses_resolved_tmux_pane(live, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(live, "_iter_processes", lambda: [live.LiveProcess(
        pid="123", tty="pts/3", state="S", elapsed_seconds="1", cwd="/work", command="hermes",
        tmux_session="agent1", tmux_pane="%7")])

    def fake_run(args, *, check=False):
        calls.append(args)
        return completed("recent output\n")

    monkeypatch.setattr(live, "_run", fake_run)
    assert live.main(["capture", "agent1", "--lines", "5"]) == 0
    assert calls == [["tmux", "capture-pane", "-t", "%7", "-p", "-S", "-5"]]
    assert "recent output" in capsys.readouterr().out


def test_missing_binary_is_a_failed_result_not_a_crash(live):
    assert live._run(["definitely-not-a-binary-xyz"]).returncode == 127


def test_list_is_the_default_action(live, monkeypatch, capsys):
    monkeypatch.setattr(live, "_iter_processes", lambda: [])
    monkeypatch.setattr(live, "_tmux_available", lambda: True)
    assert live.main([]) == 0
    assert "No live Hermes processes found." in capsys.readouterr().out


def _agent(session_db=None, session_id="session-1"):
    return SimpleNamespace(
        session_id=session_id,
        context_compressor=SimpleNamespace(context_length=100000, threshold_tokens=50000),
        _session_db=session_db,
    )


def _reviewer(review, monkeypatch, tmp_path):
    monkeypatch.setattr(review, "get_hermes_home", lambda: tmp_path)
    return review.PreCompactionReview(review.Settings(enabled=True, max_message_chars=10000))


def _snapshot(review, messages, *, tokens=47000, session_id="session-1", agent=None):
    return review._Snapshot(
        session_id=session_id, messages=messages, system_message="sys override",
        approx_tokens=tokens, model="test/model", provider="test", agent=agent or _agent())


def _checkpoint(tmp_path, name="session-1.md"):
    return tmp_path / "session-reviews" / "precompaction" / name


def test_checkpoint_not_written_below_margin(review, monkeypatch, tmp_path):
    reviewer = _reviewer(review, monkeypatch, tmp_path)
    snapshot = _snapshot(review, [{"role": "user", "content": "lesson"}], tokens=46000)
    assert reviewer.capture(snapshot, reason="near_threshold") is None
    assert not _checkpoint(tmp_path).exists()


def test_checkpoint_written_inside_margin(review, monkeypatch, tmp_path):
    reviewer = _reviewer(review, monkeypatch, tmp_path)
    snapshot = _snapshot(review, [
        {"role": "user", "content": "Michael corrected the workflow."},
        {"role": "assistant", "content": "Captured the fix."},
    ])
    path = reviewer.capture(snapshot, reason="near_threshold")
    text = path.read_text(encoding="utf-8")
    assert path.name == "session-1.md"
    assert "Pre-compaction session review checkpoint" in text
    assert "Assume this may be the last checkpoint" in text
    assert "Michael corrected the workflow." in text
    assert "sys override" in text


def test_checkpoint_dedupes_same_snapshot(review, monkeypatch, tmp_path):
    reviewer = _reviewer(review, monkeypatch, tmp_path)
    messages = [{"role": "user", "content": "same content"}]
    assert reviewer.capture(_snapshot(review, messages), reason="near_threshold") is not None
    assert reviewer.capture(_snapshot(review, messages), reason="near_threshold") is None
    assert _checkpoint(tmp_path).read_text(encoding="utf-8").count("session review checkpoint:") == 1


def test_checkpoint_uses_lineage_root(review, monkeypatch, tmp_path):
    reviewer = _reviewer(review, monkeypatch, tmp_path)

    class SessionDBStub:
        def get_session(self, session_id):
            return {"child": {"parent_session_id": "parent"}, "parent": {"parent_session_id": None}}.get(session_id)

    snapshot = _snapshot(review, [], session_id="child", agent=_agent(SessionDBStub()))
    assert reviewer.checkpoint_path(snapshot).name == "parent.md"


def test_compression_call_checkpoints_latest_history_even_below_margin(review, monkeypatch, tmp_path):
    reviewer = _reviewer(review, monkeypatch, tmp_path)
    agent = _agent()  # the hook locates this through the waiting thread's frames
    reviewer.on_pre_api_request(
        session_id="session-1", conversation_history=[{"role": "user", "content": "detail that would be lost"}],
        system_prompt="sys", approx_input_tokens=1000, model="m", provider="p")
    assert reviewer._snapshots["session-1"].agent is agent
    assert not _checkpoint(tmp_path).exists()

    reviewer.on_pre_auxiliary_call(aux_task="title_generation", session_id="session-1")
    assert not _checkpoint(tmp_path).exists()

    reviewer.on_pre_auxiliary_call(aux_task="compression", session_id="")
    text = _checkpoint(tmp_path).read_text(encoding="utf-8")
    assert "detail that would be lost" in text
    assert "- Reason: compression" in text


def test_real_hook_dispatch_reaches_the_review(review, monkeypatch, tmp_path):
    from hermes_cli import plugins as hermes_plugins
    from hermes_cli.lifecycle import invoke_hook

    reviewer = _reviewer(review, monkeypatch, tmp_path)
    manager = hermes_plugins.get_plugin_manager()
    monkeypatch.setitem(manager._hooks, "pre_api_request", [reviewer.on_pre_api_request])
    agent = _agent()
    invoke_hook("pre_api_request", session_id="session-1", conversation_history=[
        {"role": "user", "content": "through the real dispatcher"}],
        system_prompt="sys", approx_input_tokens=47000, model="m", provider="p")
    assert reviewer._snapshots["session-1"].agent is agent
    assert "through the real dispatcher" in _checkpoint(tmp_path).read_text(encoding="utf-8")


def test_agent_of_another_session_is_not_used(review, monkeypatch, tmp_path):
    reviewer = _reviewer(review, monkeypatch, tmp_path)
    agent = _agent(session_id="other-session")
    reviewer.on_pre_api_request(
        session_id="session-1", conversation_history=[], system_prompt="", approx_input_tokens=47000,
        model="m", provider="p")
    assert agent is not None and reviewer._snapshots["session-1"].agent is None


def test_settings_default_off_and_clamp(review, monkeypatch):
    from hermes_cli import config

    monkeypatch.setattr(config, "load_config", lambda: {})
    assert review.load_settings().enabled is False
    monkeypatch.setattr(config, "load_config", lambda: {"compression": {"pre_compaction_review": {
        "enabled": True, "margin": 9, "max_message_chars": "bad"}}})
    settings = review.load_settings()
    assert (settings.enabled, settings.margin, settings.max_message_chars) == (True, 0.25, 120000)


def test_hooks_register_only_when_enabled(plugin, monkeypatch):
    hooks, commands = [], []
    ctx = SimpleNamespace(
        register_hook=lambda name, cb: hooks.append(name),
        register_cli_command=lambda name, **kw: commands.append(name))
    review = plugin.pre_compaction_review
    monkeypatch.setattr(review, "load_settings", lambda: review.Settings())
    plugin.register(ctx)
    assert hooks == [] and commands == ["live"]
    monkeypatch.setattr(review, "load_settings", lambda: review.Settings(enabled=True))
    plugin.register(ctx)
    assert hooks == ["pre_api_request", "pre_auxiliary_call"]


def test_managed_nous_switch(plugin, monkeypatch):
    from tools import tool_backend_helpers as helpers
    import types

    # A copy, so the real function stays untouched for the rest of the process.
    original = helpers.managed_nous_tools_enabled
    copy = types.FunctionType(original.__code__, original.__globals__, original.__name__,
                              original.__defaults__, original.__closure__)
    copy.__kwdefaults__ = original.__kwdefaults__
    monkeypatch.setattr(helpers, "managed_nous_tools_enabled", copy)
    bound_by_importer = copy

    monkeypatch.delenv("HERMES_DISABLE_MANAGED_NOUS_TOOLS", raising=False)
    assert plugin._apply_managed_nous_switch() is False

    monkeypatch.setenv("HERMES_DISABLE_MANAGED_NOUS_TOOLS", "1")
    assert plugin._apply_managed_nous_switch() is True
    assert bound_by_importer() is False
    assert bound_by_importer(force_fresh=True) is False
