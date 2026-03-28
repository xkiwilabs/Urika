"""Integration tests for remote command flow in the REPL."""

from __future__ import annotations

from urika.repl_session import ReplSession


class TestRemoteCommandFlow:
    def test_queue_and_pop(self):
        """Basic queue/pop cycle."""
        session = ReplSession()
        session.queue_remote_command("status", "")
        assert session.has_remote_command
        cmd, args = session.pop_remote_command()
        assert cmd == "status"
        assert args == ""
        assert not session.has_remote_command

    def test_queue_order_preserved(self):
        """Commands execute in FIFO order."""
        session = ReplSession()
        session.queue_remote_command("advisor", "what next?")
        session.queue_remote_command("results", "")
        session.queue_remote_command("run", "")

        cmd1, _ = session.pop_remote_command()
        cmd2, _ = session.pop_remote_command()
        cmd3, _ = session.pop_remote_command()
        assert cmd1 == "advisor"
        assert cmd2 == "results"
        assert cmd3 == "run"

    def test_clear_on_stop(self):
        """clear_remote_queue empties everything."""
        session = ReplSession()
        session.queue_remote_command("advisor", "test")
        session.queue_remote_command("run", "")
        session.clear_remote_queue()
        assert not session.has_remote_command

    def test_load_project_clears_queue(self, tmp_path):
        """Loading a new project clears the queue."""
        session = ReplSession()
        session.queue_remote_command("run", "")
        session.load_project(tmp_path, "new-project")
        assert not session.has_remote_command

    def test_agent_active_prevents_concurrent(self):
        """When agent is active, state reflects it."""
        session = ReplSession()
        session.set_agent_active("run")
        assert session.agent_active
        assert session.active_command == "run"
        session.set_agent_idle()
        assert not session.agent_active
        assert session.active_command == ""

    def test_bus_classify_all_commands(self):
        """Verify all remote commands are correctly classified."""
        from urika.notifications.bus import classify_remote_command

        # Read-only
        for cmd in [
            "status",
            "results",
            "methods",
            "criteria",
            "experiments",
            "logs",
            "usage",
            "help",
        ]:
            assert classify_remote_command(cmd) == "read_only", (
                f"{cmd} should be read_only"
            )

        # Run control
        for cmd in ["pause", "stop", "resume"]:
            assert classify_remote_command(cmd) == "run_control", (
                f"{cmd} should be run_control"
            )

        # Agent
        for cmd in [
            "run",
            "advisor",
            "evaluate",
            "plan",
            "report",
            "present",
            "finalize",
            "build-tool",
        ]:
            assert classify_remote_command(cmd) == "agent", f"{cmd} should be agent"

        # Rejected
        for cmd in [
            "config",
            "new",
            "quit",
            "project",
            "notifications",
            "update",
            "inspect",
        ]:
            assert classify_remote_command(cmd) == "rejected", (
                f"{cmd} should be rejected"
            )
