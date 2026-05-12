import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def _make_agent(tmp_path, *, enabled=True):
    with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
        with patch("hermes_cli.config.load_config", return_value={
            "compression": {
                "enabled": True,
                "threshold": 0.50,
                "pre_compaction_review": {
                    "enabled": enabled,
                    "margin": 0.03,
                    "max_message_chars": 10000,
                },
            },
            "model": {"context_length": 100000},
        }):
            with patch("run_agent.get_hermes_home", return_value=Path(tmp_path)):
                from run_agent import AIAgent

                agent = AIAgent(
                    api_key="test-key",
                    base_url="https://openrouter.ai/api/v1",
                    model="test/model",
                    quiet_mode=True,
                    session_db=None,
                    session_id="session-1",
                    skip_context_files=True,
                    skip_memory=True,
                )
    agent.context_compressor.context_length = 100000
    agent.context_compressor.threshold_tokens = 50000
    return agent


def test_pre_compaction_checkpoint_not_written_below_margin(tmp_path):
    agent = _make_agent(tmp_path, enabled=True)
    messages = [{"role": "user", "content": "important lesson"}]

    result = agent._capture_pre_compaction_review_checkpoint(
        messages,
        "sys",
        approx_tokens=46000,
        reason="near_threshold",
    )

    assert result is None
    assert not (Path(tmp_path) / "session-reviews" / "precompaction" / "session-1.md").exists()


def test_pre_compaction_checkpoint_written_inside_margin(tmp_path):
    agent = _make_agent(tmp_path, enabled=True)
    messages = [
        {"role": "user", "content": "Michael corrected the workflow."},
        {"role": "assistant", "content": "Captured the fix."},
    ]

    result = agent._capture_pre_compaction_review_checkpoint(
        messages,
        "sys override",
        approx_tokens=47000,
        reason="near_threshold",
    )

    assert result is not None
    assert result.name == "session-1.md"
    text = result.read_text(encoding="utf-8")
    assert "Pre-compaction session review checkpoint" in text
    assert "Assume this may be the last checkpoint" in text
    assert "Michael corrected the workflow." in text
    assert "sys override" in text


def test_pre_compaction_checkpoint_dedupes_same_snapshot(tmp_path):
    agent = _make_agent(tmp_path, enabled=True)
    messages = [{"role": "user", "content": "same content"}]

    path1 = agent._capture_pre_compaction_review_checkpoint(
        messages,
        "sys",
        approx_tokens=47000,
        reason="near_threshold",
    )
    path2 = agent._capture_pre_compaction_review_checkpoint(
        messages,
        "sys",
        approx_tokens=47000,
        reason="near_threshold",
    )

    assert path1 is not None
    assert path2 is None
    text = path1.read_text(encoding="utf-8")
    assert text.count("Pre-compaction session review checkpoint") == 1


def test_pre_compaction_checkpoint_uses_lineage_root(tmp_path):
    agent = _make_agent(tmp_path, enabled=True)

    class SessionDBStub:
        def get_session(self, session_id):
            rows = {
                "child": {"parent_session_id": "parent"},
                "parent": {"parent_session_id": None},
            }
            return rows.get(session_id)

    agent._session_db = SessionDBStub()
    agent.session_id = "child"

    assert agent._pre_compaction_review_path().name == "parent.md"


def test_compress_context_writes_checkpoint_before_lossy_compression(tmp_path):
    agent = _make_agent(tmp_path, enabled=True)
    compressor = SimpleNamespace(
        context_length=100000,
        threshold_tokens=50000,
        compression_count=0,
        last_prompt_tokens=0,
        last_completion_tokens=0,
        _last_summary_error=None,
        _last_aux_model_failure_model=None,
        _last_aux_model_failure_error=None,
    )

    def compress(messages, current_tokens=None, focus_topic=None):
        compressor.compression_count += 1
        return [{"role": "user", "content": "compressed summary"}]

    compressor.compress = compress
    agent.context_compressor = compressor

    agent._compress_context(
        [{"role": "user", "content": "detail that would be lost"}],
        "sys",
        approx_tokens=60000,
    )

    checkpoint = agent._pre_compaction_review_path()
    assert checkpoint.exists()
    assert "detail that would be lost" in checkpoint.read_text(encoding="utf-8")
