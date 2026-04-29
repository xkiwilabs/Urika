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


def test_modal_macro_renders(tmp_path):
    from jinja2 import Environment, FileSystemLoader
    env = Environment(loader=FileSystemLoader("src/urika/dashboard/templates"))
    src = (
        '{% from "_macros.html" import modal %}'
        '{% call modal("test-modal", "Test") %}'
        '<p>body content</p>'
        '{% endcall %}'
    )
    out = env.from_string(src).render()
    assert "modal-backdrop" in out
    assert "modal-title" in out
    assert ">Test</h2>" in out
    assert "body content" in out


def test_action_label_first_run_uses_verb():
    env = Environment(loader=FileSystemLoader("src/urika/dashboard/templates"))
    src = (
        '{% from "_macros.html" import action_label %}'
        '{{ action_label("Generate", "report", false) }}'
    )
    assert env.from_string(src).render().strip() == "Generate report"


def test_action_label_existing_artifact_prefixes_re():
    env = Environment(loader=FileSystemLoader("src/urika/dashboard/templates"))
    cases = [
        ("Generate", "report", "Re-generate report"),
        ("Generate", "presentation", "Re-generate presentation"),
        ("Finalize", "project", "Re-finalize project"),
        ("Summarize", "project", "Re-summarize project"),
    ]
    for verb, noun, expected in cases:
        src = (
            '{% from "_macros.html" import action_label %}'
            f'{{{{ action_label("{verb}", "{noun}", true) }}}}'
        )
        assert env.from_string(src).render().strip() == expected
