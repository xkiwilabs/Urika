import json
from pathlib import Path

from urika.core.advisor_memory import (
    append_exchange,
    format_recent_history,
    load_context_summary,
    load_history,
    save_context_summary,
)


class TestAdvisorMemory:
    def test_append_and_load(self, tmp_path):
        append_exchange(tmp_path, role="user", text="What should we try next?")
        append_exchange(tmp_path, role="advisor", text="Try random forest.")
        history = load_history(tmp_path)
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[1]["role"] == "advisor"
        assert "timestamp" in history[0]

    def test_load_last_n(self, tmp_path):
        for i in range(10):
            append_exchange(tmp_path, role="user", text=f"Message {i}")
        history = load_history(tmp_path, last_n=3)
        assert len(history) == 3
        assert "Message 7" in history[0]["text"]

    def test_load_empty(self, tmp_path):
        assert load_history(tmp_path) == []

    def test_context_summary_roundtrip(self, tmp_path):
        save_context_summary(tmp_path, "# Current Strategy\nExploring trees.")
        summary = load_context_summary(tmp_path)
        assert "Current Strategy" in summary
        assert "Exploring trees" in summary

    def test_context_summary_empty(self, tmp_path):
        assert load_context_summary(tmp_path) == ""

    def test_append_with_suggestions(self, tmp_path):
        append_exchange(
            tmp_path,
            role="advisor",
            text="Try this",
            suggestions=[{"name": "exp-1", "method": "RF"}],
        )
        history = load_history(tmp_path)
        assert history[0]["suggestions"][0]["name"] == "exp-1"

    def test_append_with_source(self, tmp_path):
        append_exchange(tmp_path, role="user", text="Hello", source="telegram")
        history = load_history(tmp_path)
        assert history[0]["source"] == "telegram"

    def test_format_recent_history(self):
        entries = [
            {"role": "user", "text": "What next?", "source": "repl"},
            {"role": "advisor", "text": "Try RF.", "source": "repl"},
        ]
        formatted = format_recent_history(entries)
        assert "User: What next?" in formatted
        assert "Advisor: Try RF." in formatted

    def test_format_truncates_long(self):
        entries = [{"role": "user", "text": "x" * 500, "source": "repl"}]
        formatted = format_recent_history(entries)
        assert len(formatted) < 400
        assert "..." in formatted
