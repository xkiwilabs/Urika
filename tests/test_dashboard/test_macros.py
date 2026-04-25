"""Smoke test the tabs macro renders correctly."""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader


def test_tabs_macro_renders_tab_buttons():
    template_dir = Path("src/urika/dashboard/templates")
    env = Environment(loader=FileSystemLoader(str(template_dir)))
    src = (
        '{% from "_macros.html" import tabs %}'
        '{% call(active) tabs("test", [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]) %}'
        '<div x-show="active === \'a\'">panel-a</div>'
        '<div x-show="active === \'b\'">panel-b</div>'
        "{% endcall %}"
    )
    tpl = env.from_string(src)
    out = tpl.render()
    assert "tab-button" in out
    assert ">A</button>" in out
    assert ">B</button>" in out
    assert "panel-a" in out
    assert "active === 'a'" in out
