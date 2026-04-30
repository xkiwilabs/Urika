# Notifications Polish — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to execute this plan task-by-task.

**Goal:** Tighten the notifications subsystem so it can graduate from `dev`-only to default-on. Fix the event-vocabulary fragmentation, give the dashboard a Send-test affordance, surface auth failures clearly, expose the missing Slack inbound config, reduce channel formatter duplication, and write troubleshooting docs.

**Architecture:** No new modules. Event-type vocabulary becomes canonical in `events.py`. Channels reference that canonical set. Dashboard gains a `/api/settings/notifications/test-send` endpoint that reuses the CLI's existing `_send_test_notification` helper. The `bus._map_progress_event()` mapper grows to emit all the events the channels know about. Slack form gains the missing inbound-config fields.

**Tech stack:** Existing FastAPI + HTMX + Alpine. Existing `urika.notifications` package. No new deps.

**Out of scope (decided):** rewriting how channels are configured, adding new channel types (Discord/Mattermost/etc.), per-event opt-in toggles (those exist as priority-level filtering already).

---

## Verified findings (audit 2026-04-28)

### Real bugs

1. **Event-vocabulary fragmentation.** Three vocabularies coexist:
   - `cli/run.py` (direct `notify()`): `experiment_completed`, `experiment_failed`, `experiment_paused`, `experiment_stopped`, `meta_completed`, `meta_paused`.
   - `bus._map_progress_event` (from on_progress): `criteria_met`, `paused`, `experiment_started`.
   - Slack channel knows: `criteria_met`, `experiment_failed`, `experiment_completed`, `paused` (everything else falls through to low-priority).
   - Telegram emoji map knows: `criteria_met`, `experiment_failed`, `experiment_completed`, `meta_completed`.

   Result: `experiment_paused`, `experiment_stopped`, `meta_paused` get default formatting on Slack and Telegram. `paused` (from on_progress) and `experiment_started` get inconsistent treatment between channels.

### UX gaps

2. **No dashboard test-send.** `urika notifications --test` exists in CLI (`config_notifications.py:170`) but the dashboard global settings page has no equivalent button. Users have to drop to the terminal to validate creds.

3. **Auth failures are silently logged.** Slack `_socket_client.connect()` exceptions (slack_channel.py:343-344) and Telegram `app.initialize()` exceptions (telegram_channel.py:178-180) are caught → logged as warnings → the listener thread dies → user sees "Telegram channel enabled" with no inbound, no signal.

### Config gaps

4. **Slack dashboard form missing `app_token_env` field** (global_settings.html:567-591) — inbound Socket Mode commands can't be enabled from the dashboard without manually editing TOML. Also missing `allowed_channels` / `allowed_users` fields, which the channel logs a warning about when unset (slack_channel.py:67-72).

### Code quality

5. **Formatter duplication.** All three channels build very similar "header + summary + experiment + metrics" structures. Each owns its own `_build_*` helpers with copy-pasted shape.

### Docs

6. **`docs/17-notifications.md` has no troubleshooting and no caveats sections** — covered setup but not "what to do when X breaks".

### Non-issues (audit revised these claims)

- `email_channel.stop_listener()` was claimed to "not flush in all paths" — re-read shows it correctly flushes when pending is non-empty. Email channel has no listener thread, so divergent paths aren't possible. **Drop this claim.**
- `telegram polling never gives up on bad token` — re-read shows ApplicationBuilder().build() raises InvalidToken, _poll_loop logs and exits. The thread DOES end. The real gap is no surfacing to the user, not infinite polling. **Reframe as item 3.**

---

## Phase A — Event-vocabulary unification

### Task A.1: Canonical event types in `events.py`

**Files:**
- Modify: `src/urika/notifications/events.py` — add `EVENT_TYPES` frozenset + per-type metadata (priority hint, emoji, human label).
- Test: `tests/test_notifications/test_events.py` (new or extend) — `test_canonical_event_set_matches_emitters`.

**Step 1: Failing test**

```python
from urika.notifications.events import CANONICAL_EVENT_TYPES, EVENT_METADATA

def test_canonical_event_set_covers_all_emitters():
    """Every event_type emitted by the codebase must be canonical."""
    expected = {
        "experiment_started",
        "experiment_completed",
        "experiment_failed",
        "experiment_paused",
        "experiment_stopped",
        "meta_completed",
        "meta_paused",
        "criteria_met",
        "paused",   # legacy from on_progress mapper — keep for back-compat
        "test",     # used by --test sends
    }
    assert expected.issubset(CANONICAL_EVENT_TYPES)


def test_event_metadata_has_emoji_priority_label_for_each():
    for evt in CANONICAL_EVENT_TYPES:
        meta = EVENT_METADATA.get(evt)
        assert meta is not None, f"missing metadata for {evt}"
        assert meta.get("emoji"), f"missing emoji for {evt}"
        assert meta.get("priority") in {"low", "medium", "high"}
        assert meta.get("label"), f"missing label for {evt}"
```

**Step 2: Implement**

Add to `events.py`:

```python
CANONICAL_EVENT_TYPES: frozenset[str] = frozenset({
    "experiment_started",
    "experiment_completed",
    "experiment_failed",
    "experiment_paused",
    "experiment_stopped",
    "meta_completed",
    "meta_paused",
    "criteria_met",
    "paused",
    "test",
})

EVENT_METADATA: dict[str, dict[str, str]] = {
    "experiment_started":   {"emoji": "🚀", "priority": "medium", "label": "Experiment Started"},
    "experiment_completed": {"emoji": "🏁", "priority": "high",   "label": "Experiment Completed"},
    "experiment_failed":    {"emoji": "❌", "priority": "high",   "label": "Experiment Failed"},
    "experiment_paused":    {"emoji": "⏸",  "priority": "medium", "label": "Experiment Paused"},
    "experiment_stopped":   {"emoji": "⏹",  "priority": "medium", "label": "Experiment Stopped"},
    "meta_completed":       {"emoji": "🏁", "priority": "high",   "label": "Autonomous Run Complete"},
    "meta_paused":          {"emoji": "⏸",  "priority": "medium", "label": "Autonomous Run Paused"},
    "criteria_met":         {"emoji": "✅", "priority": "high",   "label": "Criteria Met"},
    "paused":               {"emoji": "⏸",  "priority": "medium", "label": "Paused"},
    "test":                 {"emoji": "🔔", "priority": "medium", "label": "Test Notification"},
}
```

**Step 3: Tests pass.**

**Step 4: Commit** — `feat(notifications): canonical event-type vocabulary in events.py`

### Task A.2: Channels reference canonical metadata

**Files:**
- Modify: `src/urika/notifications/slack_channel.py:30-39` — replace local `_HIGH_PRIORITY_TYPES` / `_MEDIUM_PRIORITY_TYPES` / `_EMOJI_MAP` with lookups into `EVENT_METADATA`.
- Modify: `src/urika/notifications/telegram_channel.py:31-37` — same.
- Test: extend `tests/test_notifications/test_slack_channel.py` and `test_telegram_channel.py` — `test_all_canonical_events_format_without_falling_through`.

**Step 1: Failing test (per channel)**

```python
def test_slack_formats_every_canonical_event_with_emoji_not_default():
    from urika.notifications.events import CANONICAL_EVENT_TYPES, NotificationEvent
    from urika.notifications.slack_channel import SlackChannel

    ch = SlackChannel({"channel": "#test", "bot_token_env": ""})
    for evt_type in CANONICAL_EVENT_TYPES:
        event = NotificationEvent(
            event_type=evt_type, project_name="p", summary="s",
            priority="high",  # force high path
        )
        blocks = ch._build_blocks(event)
        # Header text must NOT contain the default fallback emoji ℹ️
        header_text = next(
            (b["text"]["text"] for b in blocks if b.get("type") == "header"),
            "",
        )
        assert "ℹ" not in header_text, f"{evt_type} fell through to default emoji"
```

**Step 2: Implement**

In `slack_channel.py`, drop `_EMOJI_MAP` literal; replace `_EMOJI_MAP.get(event.event_type, "ℹ️")` with `EVENT_METADATA.get(event.event_type, {}).get("emoji", "ℹ️")`. Drive priority routing from metadata too:

```python
from urika.notifications.events import EVENT_METADATA

def _priority_for(event):
    return EVENT_METADATA.get(event.event_type, {}).get("priority", event.priority)
```

Telegram channel: same swap. Drop the local `_EMOJI` dict.

**Step 3: Tests pass.**

**Step 4: Commit** — `refactor(notifications): channels read canonical event metadata`

### Task A.3: Bus mapper covers run-status events

**Files:**
- Modify: `src/urika/notifications/bus.py:267-309` — `_map_progress_event` extends to emit `experiment_completed`, `experiment_failed`, `experiment_paused`, `experiment_stopped` from the appropriate `on_progress` events. Today these only flow via direct `notify()` from `cli/run.py`, so non-CLI surfaces (TUI, dashboard) miss them.
- Test: extend `tests/test_notifications/test_bus.py` — assert each run-status event is mapped.

**Step 1: Failing test**

```python
@pytest.mark.parametrize("phase_text,expected_event_type", [
    ("Experiment completed", "experiment_completed"),
    ("Experiment failed: ...", "experiment_failed"),
    ("Experiment paused after ...", "experiment_paused"),
    ("Experiment stopped", "experiment_stopped"),
])
def test_map_progress_event_covers_run_status(phase_text, expected_event_type):
    bus = NotificationBus(project_name="p")
    notif = bus._map_progress_event("phase", phase_text)
    assert notif is not None
    assert notif.event_type == expected_event_type
```

**Step 2: Implement** — add the four new branches to `_map_progress_event`. Use `startswith` / `in` matches consistent with the existing mapper style.

**Step 3: Tests pass.**

**Step 4: Commit** — `feat(notifications): bus mapper emits run-status events for non-CLI surfaces`

---

## Phase B — Dashboard test-send + missing Slack fields

### Task B.1: Extract test-send helper into reusable function

**Files:**
- Modify: `src/urika/cli/config_notifications.py:170-260` — extract the per-channel test-send logic into a module-level `send_test_through_bus(bus) -> dict[str, str]` that returns `{channel_class_name: "ok" | "error: <msg>"}`.
- Test: new `tests/test_notifications/test_send_test.py` — `test_send_test_returns_per_channel_status`.

The CLI's existing `_send_test_notification` already does the right thing in interactive context; we want a non-printing version that returns structured results so the dashboard can render them.

**Step 1: Failing test**

```python
def test_send_test_returns_per_channel_status(monkeypatch):
    bus = NotificationBus(project_name="p")
    fake_ok = MagicMock(spec=NotificationChannel)
    fake_fail = MagicMock(spec=NotificationChannel)
    fake_fail.send.side_effect = RuntimeError("bad token")
    bus.add_channel(fake_ok)
    bus.add_channel(fake_fail)

    results = send_test_through_bus(bus)
    assert results["MagicMock_0"]["status"] == "ok"
    assert results["MagicMock_1"]["status"] == "error"
    assert "bad token" in results["MagicMock_1"]["message"]
```

**Step 2: Implement** the helper. Update `_send_test_notification` to call it and pretty-print.

**Step 3: Commit** — `refactor(notifications): extract send_test_through_bus helper`

### Task B.2: Dashboard `/api/settings/notifications/test-send` endpoint

**Files:**
- Modify: `src/urika/dashboard/routers/api.py` — new `POST /api/settings/notifications/test-send` endpoint. Accepts the form data (un-saved values), builds a transient bus, calls `send_test_through_bus`, returns JSON `{channels: [{name, status, message}]}`.
- Test: new `tests/test_dashboard/test_notifications_test_send.py`.

The endpoint must work on UN-SAVED form data so the user can validate before clicking Save.

**Step 1: Failing test**

```python
def test_notifications_test_send_returns_per_channel_status(client_global):
    r = client_global.post(
        "/api/settings/notifications/test-send",
        data={
            "notifications_email_from": "bot@example.com",
            "notifications_email_to": "alice@example.com",
            "notifications_email_smtp_host": "localhost",
            "notifications_email_smtp_port": "25",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert "channels" in body
    # SMTP to localhost:25 should fail in CI — that's a valid result
    assert any(ch["status"] == "error" for ch in body["channels"])
```

**Step 2: Implement** the endpoint. Build a per-channel config dict from the form fields (mirror what the Save endpoint does); construct each channel; call `send_test_through_bus`. Return JSON.

**Step 3: Commit** — `feat(dashboard): notifications test-send endpoint`

### Task B.3: Dashboard test-send button

**Files:**
- Modify: `src/urika/dashboard/templates/global_settings.html:509-617` — add a "Send test notification" button at the bottom of the Notifications tab, plus an Alpine x-data block that POSTs the form to the new endpoint and renders `{channels: [...]}` results inline.
- Test: extend `tests/test_dashboard/test_pages_settings.py` — assert button rendered.

Reuse the existing `endpoint-test` styling (lines 137-170 already define `endpoint-test-result`, `endpoint-test-result--ok`, `endpoint-test-result--fail`).

**Step 1: Failing test** — assert Notifications tab contains the test-send button.

**Step 2: Implement** the Alpine block + button. Mirror the existing endpoint-test pattern; render a small list of channel results (one row per channel: green tick + name, or red cross + error message).

**Step 3: Commit** — `feat(dashboard): test-send button on global notifications tab`

### Task B.4: Slack form missing fields

**Files:**
- Modify: `src/urika/dashboard/templates/global_settings.html:567-591` — add three fields to the Slack channel block:
  - `notifications_slack_app_token_env` (text)
  - `notifications_slack_allowed_channels` (text, comma-separated)
  - `notifications_slack_allowed_users` (text, comma-separated)
- Modify: `src/urika/dashboard/routers/api.py` — Save endpoint reads these fields and writes them into `notif_slack` dict.
- Test: extend `tests/test_dashboard/test_pages_settings.py` — assert fields render and round-trip.

**Step 1: Failing test** — assert the three fields render.

**Step 2: Implement** — add the form rows + Save handler.

**Step 3: Commit** — `feat(dashboard): expose Slack inbound config fields (app_token, allowed_channels, allowed_users)`

---

## Phase C — Auth-failure surfacing

### Task C.1: Slack channel `health_check()` method

**Files:**
- Modify: `src/urika/notifications/base.py` — add `health_check() -> tuple[bool, str]` to base class with default `(True, "")`.
- Modify: `src/urika/notifications/slack_channel.py` — implement `health_check()` calls `self._client.auth_test()` and returns `(True, "")` on success or `(False, err_msg)` on failure.
- Modify: `src/urika/notifications/telegram_channel.py` — implement `health_check()` calls `Bot(token).get_me()` synchronously.
- Modify: `src/urika/notifications/email_channel.py` — `health_check()` does an SMTP connect + `noop()`.
- Test: per-channel `test_health_check_returns_false_on_bad_creds`.

**Step 1: Failing tests** — assert each channel's `health_check()` reports false on misconfigured creds.

**Step 2: Implement** the per-channel checks. Use existing channel API objects.

**Step 3: Commit** — `feat(notifications): per-channel health_check() surfaces auth failures`

### Task C.2: Wire health checks into test-send + bus startup

**Files:**
- Modify: `src/urika/notifications/bus.py:212-230` — `start()` runs `health_check()` on each channel before starting listeners; logs a clear error for any failing channel; channels that fail health check are removed from the dispatch list.
- Modify: `send_test_through_bus` (Phase B.1) — calls `health_check()` first and reports the result alongside the test-send result.
- Test: bus integration test — `test_start_excludes_channels_that_fail_health_check`.

**Step 1: Failing test.**

**Step 2: Implement.**

**Step 3: Commit** — `feat(notifications): bus skips channels that fail startup health check`

---

## Phase D — Code quality + docs

### Task D.1: Extract shared formatter helpers

**Files:**
- Create: `src/urika/notifications/formatting.py` — `format_event_summary(event) -> str`, `format_event_label(event) -> str`, `format_event_emoji(event) -> str` reading from `EVENT_METADATA`.
- Modify: each channel — replace local copies with calls into the shared module.
- Test: new `tests/test_notifications/test_formatting.py`.

Shared helpers cover the ~70% of formatting logic that's identical across channels. Channel-specific structure (Slack Block Kit, HTML email, Telegram HTML) stays in the channel.

**Step 1: Failing tests** — assert the three helpers return expected strings for each canonical event.

**Step 2: Implement.** Strip duplication from channels.

**Step 3: Commit** — `refactor(notifications): shared formatting helpers`

### Task D.2: Troubleshooting + caveats sections in docs

**Files:**
- Modify: `docs/17-notifications.md` — append two sections at end:
  - `## Troubleshooting`: covers each channel's common errors (Slack: invalid bot token / app token; Telegram: invalid bot token / chat ID; Email: SMTP auth failure / wrong port). Each error → symptom → fix.
  - `## Caveats`: pause/stop buttons only appear on `experiment_started` events; per-channel priority filtering rules; what events the bus emits; why some events take a few seconds to surface.

**Step 1: No test (docs).**

**Step 2: Write the sections.**

**Step 3: Commit** — `docs(notifications): troubleshooting + caveats`

---

## Phase E — Smoke + graduate from dev-only

### Task E.1: Manual smoke checklist

Create `dev/plans/2026-04-28-notifications-polish-smoke.md` with:
- Configure email + Slack + Telegram with real creds via the dashboard.
- Click Send-test → confirm all three deliver and report success.
- Set bad bot token → click Send-test → confirm the failure surfaces with the SDK's actual error message.
- Run an experiment → confirm `experiment_started` lands on Slack with emoji + Telegram with keyboard.
- Pause via Telegram button → confirm orchestrator pauses; resume; confirm `experiment_paused` and `experiment_completed` events both deliver with non-default emoji.
- Verify the same end-to-end flow from CLI (`urika notifications --test`) still works.

### Task E.2: Remove dev-only flag

**Files:**
- Modify: `~/.claude/projects/.../memory/project_pause_notifications.md` (memory entry) — flip status from "dev-only until tested" to "shipping in v0.3".
- Modify: any CHANGELOG / README mention of "dev-only" for notifications.

This task only after all of Phase A-D + smoke pass.

**Step 1: Confirm smoke passed.**

**Step 2: Update flags + memory.**

**Step 3: Commit** — `chore(notifications): graduate from dev-only`

---

## Effort

- Phase A (event vocab unification): ~6 hours
- Phase B (dashboard test-send + missing fields): ~6 hours
- Phase C (health checks + auth surfacing): ~4 hours
- Phase D (formatter dedup + docs): ~4 hours
- Phase E (smoke + graduate): ~2 hours

**Total: ~3 days** of focused work.

---

## Open questions (none — proceed)

Prior open questions on Resume semantics and `keep=N` belong to the orchestrator-memory plan, not this one. Notifications design is settled.
