from fastapi.testclient import TestClient

from urika.dashboard_v2.app import create_app


def test_app_serves_static_css():
    app = create_app(project_root=None)
    client = TestClient(app)
    r = client.get("/static/app.css")
    assert r.status_code == 200
    assert "text/css" in r.headers["content-type"]
    assert "--accent" in r.text  # design-system var present


def test_app_has_jinja_environment_attached():
    app = create_app(project_root=None)
    assert hasattr(app.state, "templates")
    # Template directory should resolve _base.html
    tpl = app.state.templates.get_template("_base.html")
    assert tpl is not None
