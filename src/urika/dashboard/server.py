"""Dashboard HTTP server — lightweight read-only project viewer."""

from __future__ import annotations

import json
import logging
import mimetypes
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from typing import Any

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "templates"


class DashboardServer(HTTPServer):
    """HTTP server bound to localhost serving a single project dashboard."""

    def __init__(self, project_dir: str | Path, port: int = 8420) -> None:
        self.project_dir = Path(project_dir).resolve()
        super().__init__(("127.0.0.1", port), DashboardHandler)


class DashboardHandler(BaseHTTPRequestHandler):
    """Route GET requests to dashboard API endpoints."""

    server: DashboardServer  # type narrowing

    # ── Routing ──────────────────────────────────────────────────

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        qs = parse_qs(parsed.query)

        routes: dict[str, Any] = {
            "/": self._serve_root,
            "/api/tree": self._api_tree,
            "/api/file": self._api_file,
            "/api/raw": self._api_raw,
            "/api/stats": self._api_stats,
            "/api/methods": self._api_methods,
            "/api/criteria": self._api_criteria,
        }

        handler = routes.get(path)
        if handler:
            handler(qs)
        else:
            self._send_error(404, "Not found")

    # ── Endpoints ────────────────────────────────────────────────

    def _serve_root(self, qs: dict) -> None:
        """Serve dashboard.html with project name injected."""
        template_path = _TEMPLATE_DIR / "dashboard.html"
        try:
            html = template_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            self._send_error(500, "Dashboard template not found")
            return

        project_name = self._get_project_name()
        html = html.replace("{{PROJECT_NAME}}", project_name)

        self._send_response(200, html.encode("utf-8"), "text/html; charset=utf-8")

    def _api_tree(self, qs: dict) -> None:
        """Return project tree as JSON."""
        from urika.dashboard.tree import build_project_tree

        sort_order = qs.get("sort", [None])[0]
        reverse = sort_order != "oldest"
        tree = build_project_tree(self.server.project_dir, reverse=reverse)
        self._send_json(tree)

    def _api_file(self, qs: dict) -> None:
        """Return rendered HTML for a file."""
        rel_path = qs.get("path", [None])[0]
        if not rel_path:
            self._send_error(400, "Missing path parameter")
            return

        resolved = self._validate_path(rel_path)
        if resolved is None:
            return  # 403 already sent

        if not resolved.is_file():
            self._send_error(404, "File not found")
            return

        try:
            content = resolved.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            self._send_error(500, "Cannot read file")
            return

        from urika.dashboard.renderer import render_file_content

        # Compute the directory containing this file, relative to project root
        try:
            base_dir = str(resolved.parent.relative_to(self.server.project_dir))
        except ValueError:
            base_dir = ""

        html = render_file_content(content, resolved.name, base_dir=base_dir)
        self._send_json({"html": html})

    def _api_raw(self, qs: dict) -> None:
        """Serve raw file bytes (for images etc.)."""
        rel_path = qs.get("path", [None])[0]
        if not rel_path:
            self._send_error(400, "Missing path parameter")
            return

        resolved = self._validate_path(rel_path)
        if resolved is None:
            return  # 403 already sent

        if not resolved.is_file():
            self._send_error(404, "File not found")
            return

        try:
            data = resolved.read_bytes()
        except OSError:
            self._send_error(500, "Cannot read file")
            return

        content_type = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
        self._send_response(200, data, content_type)

    def _api_stats(self, qs: dict) -> None:
        """Return project statistics as JSON."""
        project_dir = self.server.project_dir
        stats: dict[str, Any] = {}

        # Project name and question from urika.toml
        stats["project_name"] = self._get_project_name()
        toml_data = self._load_toml()
        if toml_data:
            stats["name"] = toml_data.get("project", {}).get("name", "")
            stats["question"] = toml_data.get("project", {}).get("question", "")

        # Count experiments
        exp_dir = project_dir / "experiments"
        if exp_dir.is_dir():
            stats["experiments"] = len(
                [d for d in exp_dir.iterdir() if d.is_dir()]
            )
        else:
            stats["experiments"] = 0

        # Methods count and best metric
        methods_data = self._load_json("methods.json")
        if methods_data and "methods" in methods_data:
            methods_list = methods_data["methods"]
            stats["methods"] = len(methods_list)

            # Find best metric
            best_val = None
            best_metric = None
            for m in methods_list:
                metrics = m.get("metrics", {})
                for metric_name, value in metrics.items():
                    if isinstance(value, (int, float)):
                        if best_val is None or value > best_val:
                            best_val = value
                            best_metric = metric_name
            if best_val is not None:
                stats["best"] = {"metric": best_metric, "value": best_val}
        else:
            stats["methods"] = 0

        self._send_json(stats)

    def _api_methods(self, qs: dict) -> None:
        """Return methods.json content."""
        data = self._load_json("methods.json")
        if data is None:
            data = {"methods": []}
        self._send_json(data)

    def _api_criteria(self, qs: dict) -> None:
        """Return criteria.json content."""
        data = self._load_json("criteria.json")
        if data is None:
            data = {"versions": []}
        self._send_json(data)

    # ── Helpers ──────────────────────────────────────────────────

    def _validate_path(self, rel_path: str) -> Path | None:
        """Resolve a relative path and check it stays within the project.

        Returns the resolved Path, or None if traversal detected (sends 403).
        """
        resolved = (self.server.project_dir / rel_path).resolve()
        if not resolved.is_relative_to(self.server.project_dir):
            self._send_error(403, "Forbidden")
            return None
        return resolved

    def _get_project_name(self) -> str:
        """Read project name from urika.toml."""
        toml_data = self._load_toml()
        if toml_data:
            return toml_data.get("project", {}).get("name", self.server.project_dir.name)
        return self.server.project_dir.name

    def _load_toml(self) -> dict | None:
        """Load urika.toml if it exists."""
        toml_path = self.server.project_dir / "urika.toml"
        if not toml_path.is_file():
            return None
        try:
            import tomllib

            with open(toml_path, "rb") as f:
                return tomllib.load(f)
        except Exception:
            return None

    def _load_json(self, filename: str) -> dict | None:
        """Load a JSON file from the project root."""
        path = self.server.project_dir / filename
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def _send_json(self, data: Any) -> None:
        """Send a JSON response."""
        body = json.dumps(data).encode("utf-8")
        self._send_response(200, body, "application/json")

    def _send_response(self, code: int, body: bytes, content_type: str) -> None:
        """Send an HTTP response."""
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, code: int, message: str) -> None:
        """Send an error response."""
        body = json.dumps({"error": message}).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        """Route request logs through Python logging instead of stderr."""
        logger.debug(format, *args)


def start_dashboard(
    project_dir: str | Path,
    port: int = 8420,
    open_browser: bool = True,
) -> None:
    """Start the dashboard HTTP server.

    Blocks until KeyboardInterrupt. Binds to 127.0.0.1 only.

    Args:
        project_dir: Path to the project directory.
        port: Port to bind to (default 8420).
        open_browser: Whether to open the browser automatically.
    """
    server = DashboardServer(project_dir, port=port)
    actual_port = server.server_address[1]
    url = f"http://127.0.0.1:{actual_port}"

    logger.info("Dashboard serving %s at %s", project_dir, url)
    print(f"  Dashboard: {url}")
    print("  Press Ctrl+C to stop.\n")

    if open_browser:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
