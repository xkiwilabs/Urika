import json
import threading
import urllib.request
import urllib.error
from pathlib import Path

import pytest

from urika.dashboard.server import DashboardServer


class TestDashboardServer:
    def _start_server(self, project_dir):
        """Start server on a random port, return (server, port)."""
        server = DashboardServer(project_dir, port=0)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, port

    def test_serves_root(self, dashboard_project):
        server, port = self._start_server(dashboard_project)
        try:
            resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/")
            html = resp.read().decode()
            assert "urika" in html.lower()
            assert "test-project" in html
        finally:
            server.shutdown()

    def test_api_tree(self, dashboard_project):
        server, port = self._start_server(dashboard_project)
        try:
            resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/tree")
            data = json.loads(resp.read())
            labels = [s["label"] for s in data]
            assert "Experiments" in labels
        finally:
            server.shutdown()

    def test_api_file_markdown(self, dashboard_project):
        server, port = self._start_server(dashboard_project)
        try:
            resp = urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/file?path=experiments/exp-001-baseline/labbook/notes.md"
            )
            html = resp.read().decode()
            assert "Notes" in html
        finally:
            server.shutdown()

    def test_api_file_json(self, dashboard_project):
        server, port = self._start_server(dashboard_project)
        try:
            resp = urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/file?path=methods.json"
            )
            html = resp.read().decode()
            assert "linear_regression" in html
        finally:
            server.shutdown()

    def test_api_file_rejects_traversal(self, dashboard_project):
        server, port = self._start_server(dashboard_project)
        try:
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/file?path=../../etc/passwd"
                )
            assert exc_info.value.code == 403
        finally:
            server.shutdown()

    def test_api_stats(self, dashboard_project):
        server, port = self._start_server(dashboard_project)
        try:
            resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/stats")
            data = json.loads(resp.read())
            assert "experiments" in data
            assert "methods" in data
            assert data["project_name"] == "test-project"
        finally:
            server.shutdown()

    def test_api_raw_image(self, dashboard_project):
        server, port = self._start_server(dashboard_project)
        try:
            resp = urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/raw?path=experiments/exp-001-baseline/artifacts/results.png"
            )
            data = resp.read()
            assert data == b"fake-png"
        finally:
            server.shutdown()

    def test_api_methods(self, dashboard_project):
        server, port = self._start_server(dashboard_project)
        try:
            resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/methods")
            data = json.loads(resp.read())
            assert "methods" in data
        finally:
            server.shutdown()

    def test_api_criteria(self, dashboard_project):
        server, port = self._start_server(dashboard_project)
        try:
            resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/criteria")
            data = json.loads(resp.read())
            assert "versions" in data
        finally:
            server.shutdown()

    def test_404_unknown_route(self, dashboard_project):
        server, port = self._start_server(dashboard_project)
        try:
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/nonexistent")
            assert exc_info.value.code == 404
        finally:
            server.shutdown()
