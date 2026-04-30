# Notifications Polish — Manual Smoke Checklist

> **Status:** Run after the implementation plan in `2026-04-28-notifications-polish.md` lands. All Phase A–D work must be on `dev` first. After smoke passes, Phase E.2 graduates the feature from dev-only.

**Goal:** Validate the polished notifications subsystem end-to-end with real credentials before flipping the dev-only guard.

**Pre-reqs:**

- Real Slack workspace with bot installed + bot token + (optional) app token
- Telegram bot token + chat ID
- Email account with SMTP access + app password (Gmail, Outlook, etc.)
- A throwaway Urika project to run experiments against

---

## 1. Dashboard test-send button

For each channel, verify the Send-test button surfaces both success and failure cleanly.

- [ ] Open `urika dashboard` → `/settings` → Notifications tab.
- [ ] Email: fill in valid credentials → click **Send test notification** → see green tick + "EmailChannel — sent". Inbox receives one email with the canonical 🔔 emoji and "Test Notification" subject.
- [ ] Email: deliberately put wrong SMTP password env var → click Send-test → see red cross + "EmailChannel — failed: health check failed: …" with the actual SMTP auth error string.
- [ ] Slack: fill in bot token env var → Send-test → green tick + message in the configured Slack channel with "🔔 Test Notification — Test notification from Urika".
- [ ] Slack: invalidate bot token → Send-test → red cross + message containing `invalid_auth`.
- [ ] Telegram: fill in valid bot token + chat ID → Send-test → green tick + message in Telegram chat.
- [ ] Telegram: corrupt bot token → Send-test → red cross + `Unauthorized` or `InvalidToken`.
- [ ] Empty form (no channels configured) → Send-test → "No channels configured" message rendered.

## 2. CLI parity

- [ ] `urika notifications --show` lists the configured channels.
- [ ] `urika notifications --test` (no project) sends through the global config and prints per-channel success/error.
- [ ] `urika notifications --test --project <p>` sends through the project's resolved bus and prints per-channel results (uses the new `send_test_through_bus` helper).

## 3. Slack inbound config (added in Phase B.4)

- [ ] On the dashboard Slack block, the three new fields render: **App token env var (Socket Mode)**, **Allowed channels (comma-separated)**, **Allowed users (comma-separated)**.
- [ ] Save with values for all three → reload the dashboard → values persist.
- [ ] Save with empties → reload → fields are blank (no `[""]` artifacts in `urika.toml`).
- [ ] With `app_token_env=SLACK_APP_TOKEN` set and Socket Mode enabled in the Slack app, sending `/status` from Slack to the bot returns project status. Without the app token, the bot's outbound notifications still work but `/status` does not (correct degradation).

## 4. Bus startup health-check filtering (Phase C)

- [ ] Run any experiment (`urika run`) with a deliberately bad bot token. Confirm the run starts and runs to completion. Look at logs — see a `WARNING` line: `Channel SlackChannel failed health check: invalid_auth — will not dispatch`. No exception. The run does NOT receive Slack notifications. Email + Telegram (if configured) still work.
- [ ] Fix the token → restart Urika → no warning, Slack notifications resume.

## 5. End-to-end run with all canonical events

- [ ] Configure a project with a fast-converging fake dataset.
- [ ] Run `urika run --turns 1` with email + Slack + Telegram all enabled.
- [ ] Verify each channel receives a notification for `experiment_started` (🚀), `experiment_completed` or `criteria_met` (🏁/✅), with the correct emoji per the canonical EVENT_METADATA. No ℹ default emoji on any event.
- [ ] Pause via Telegram inline keyboard (button on `experiment_started` message) → orchestrator pauses → `experiment_paused` (⏸) event delivers.
- [ ] Resume via `urika run --resume` → completion event delivers.
- [ ] Stop via dashboard Stop button mid-run → `experiment_stopped` (⏹) event delivers.

## 6. Vocabulary unification (Phase A) sanity

- [ ] On Slack, the previously-broken events (`experiment_paused`, `experiment_stopped`, `meta_paused`, `meta_completed`) all render with their proper emoji, not the default ℹ.
- [ ] On Telegram, those same events route through `_format_high` for high-priority events (canonical metadata-driven routing) and show the canonical emoji.

## 7. Docs

- [ ] `docs/17-notifications.md` has Troubleshooting and Caveats sections at the bottom.
- [ ] Each per-channel troubleshooting table has at least 4 rows. Diagnostics list and Caveats list match the actual implemented behaviour.

---

## Sign-off

When all checkboxes pass, dispatch Phase E.2:

- Update memory `project_pause_notifications.md` from "dev branch only" to "shipping in v0.3".
- CHANGELOG entry on `dev` for the polish work.
- Run release script when ready to merge to `main`.

If anything fails, file the failure as a follow-up task, fix on `dev`, re-smoke, and only THEN graduate.
