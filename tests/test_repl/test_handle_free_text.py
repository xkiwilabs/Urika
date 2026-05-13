"""``_handle_free_text`` runtime behavior (REPL free-text → orchestrator).

Pre-this-file only source-grepped (`test_package_i_parity.py:20-30` checks
for the presence of ``parse_suggestions`` in the source). The actual
runtime flow — chat call → response rendered → suggestions parsed into
``session.pending_suggestions`` → usage stats updated — was untested.
The TUI has equivalent dispatch-level coverage; the classic REPL did
not.
"""

from __future__ import annotations

from pathlib import Path


from urika.repl.session import ReplSession


def _setup(tmp_path: Path) -> ReplSession:
    from urika.core.models import ProjectConfig
    from urika.core.workspace import create_project_workspace

    proj = tmp_path / "p"
    create_project_workspace(
        proj, ProjectConfig(name="p", question="Q?", mode="exploratory")
    )
    session = ReplSession()
    session.load_project(path=proj, name="p")
    # The handler checks _private_endpoint_ok — open mode default.
    session._private_endpoint_ok = True
    return session


class _StubOrchestrator:
    def __init__(
        self,
        response: str,
        *,
        tokens_in: int = 50,
        tokens_out: int = 100,
        cost_usd: float = 0.001,
        model: str = "claude-test",
    ) -> None:
        self._response = response
        self._tokens_in = tokens_in
        self._tokens_out = tokens_out
        self._cost_usd = cost_usd
        self._model = model

    async def chat(self, text, *, on_output=None, **_):  # noqa: ANN001
        return {
            "response": self._response,
            "success": True,
            "tokens_in": self._tokens_in,
            "tokens_out": self._tokens_out,
            "cost_usd": self._cost_usd,
            "model": self._model,
            "error_category": None,
        }


def test_handle_free_text_renders_response_and_updates_usage(
    tmp_path, monkeypatch, capsys
) -> None:
    from urika.repl.main import _handle_free_text

    session = _setup(tmp_path)
    orch = _StubOrchestrator("Hello back!")
    monkeypatch.setattr("urika.repl.main._get_orchestrator", lambda _s: orch)

    _handle_free_text(session, "hi orchestrator")

    out = capsys.readouterr().out
    assert "Hello back!" in out
    # Usage stats accumulate on the session.
    assert session.total_tokens_in == 50
    assert session.total_tokens_out == 100
    assert session.agent_calls == 1
    assert session.model == "claude-test"


def test_handle_free_text_appends_to_conversation_history(
    tmp_path, monkeypatch
) -> None:
    from urika.repl.main import _handle_free_text

    session = _setup(tmp_path)
    monkeypatch.setattr(
        "urika.repl.main._get_orchestrator",
        lambda _s: _StubOrchestrator("Response text"),
    )
    _handle_free_text(session, "user message")
    # Both halves of the exchange land in session.conversation (each
    # message has either ``content`` or ``text`` depending on the
    # session's storage shape).
    convo = " | ".join(
        m.get("text", m.get("content", "")) for m in session.conversation
    )
    assert "user message" in convo
    assert "Response text" in convo


def test_handle_free_text_parses_suggestions_into_pending(
    tmp_path, monkeypatch, capsys
) -> None:
    from urika.repl.main import _handle_free_text

    session = _setup(tmp_path)
    response = (
        "Sure, here's what I'd try:\n"
        "```json\n"
        '{"suggestions": ['
        '{"name": "rf-baseline", "method": "random forest"},'
        '{"name": "xgb-tuned", "method": "xgboost"}'
        "]}\n"
        "```\n"
    )
    monkeypatch.setattr(
        "urika.repl.main._get_orchestrator", lambda _s: _StubOrchestrator(response)
    )
    _handle_free_text(session, "what next?")
    assert session.pending_suggestions, (
        "suggestions JSON in the orchestrator response was not parsed into "
        "session.pending_suggestions — /run won't pick them up"
    )
    names = [s.get("name") for s in session.pending_suggestions]
    assert names == ["rf-baseline", "xgb-tuned"]
    # One-line user hint mentions /run.
    out = capsys.readouterr().out
    assert "/run" in out


def test_handle_free_text_no_suggestions_does_not_pollute_pending(
    tmp_path, monkeypatch
) -> None:
    from urika.repl.main import _handle_free_text

    session = _setup(tmp_path)
    monkeypatch.setattr(
        "urika.repl.main._get_orchestrator",
        lambda _s: _StubOrchestrator("Just some prose, no JSON."),
    )
    _handle_free_text(session, "hi")
    assert session.pending_suggestions == []


def test_handle_free_text_short_circuits_when_endpoint_unreachable(
    tmp_path, monkeypatch, capsys
) -> None:
    """In hybrid/private mode with a downed local endpoint, the handler
    must NOT call the orchestrator — just print a clear message."""
    from urika.repl.main import _handle_free_text

    session = _setup(tmp_path)
    session._private_endpoint_ok = False

    called: list = []

    class _ShouldNotBeCalled:
        async def chat(self, *_a, **_k):
            called.append(True)
            return {}

    monkeypatch.setattr(
        "urika.repl.main._get_orchestrator", lambda _s: _ShouldNotBeCalled()
    )
    _handle_free_text(session, "hi")
    assert not called, "orchestrator was called despite endpoint being down"
    assert (
        "unreachable" in capsys.readouterr().out.lower()
        or "disabled" in capsys.readouterr().out.lower()
    )
