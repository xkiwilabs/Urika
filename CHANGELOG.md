# Changelog

All notable changes to Urika will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- **Dashboard now shows the "Final report" link for finalized
  projects.** ``urika finalize`` writes the project report to
  ``projectbook/final-report.md``, but the dashboard only looked for
  ``report.md`` / ``narrative.md`` — so finalized projects showed no
  report link and the report route 404'd even though the report
  existed. The dashboard now recognizes ``final-report.md`` (preferred)
  with ``report.md`` / ``narrative.md`` kept as fallbacks.

## [0.9.0] – 2026-06-13

Publication-ready outputs. Finalized projects now ship with
per-method model cards, a plain-language metrics glossary, and a
runnable Jupyter reproduce notebook — all generated deterministically
by pure code from artifacts the agents already wrote (no extra API
cost). Reports and the final report can be exported to LaTeX or PDF
via pandoc, and metrics gain bootstrap confidence intervals that flow
from the run record into the labbook, reports, model cards, and the
notebook.

### Added

- **Bootstrap confidence intervals on metrics** —
  ``IMetric.compute_with_ci`` (concrete method on the metric ABC in
  ``urika.evaluation.metrics.base``, inherited by every metric)
  computes a pairwise bootstrap-percentile interval over
  ``(y_true, y_pred)`` resamples: deterministic for a given seed,
  ``ValueError`` on short/mismatched inputs or when >20% of resamples
  fail, with a documented caveat that percentile intervals can
  undercover near a boundary (R²/AUC ≈ 1.0). Run records carry the
  intervals in the new ``RunRecord.metrics_with_uncertainty`` field
  (``{"value", "ci_lower", "ci_upper", "confidence"}`` per metric;
  legacy records load with ``{}``), the task agent is instructed to
  report a CI for every primary metric where resampling is feasible
  (and the CI of the effect size — not the p-value — for statistical
  tests), the labbook renders them inline
  (``r2=0.75 [95% CI 0.72–0.78] — <interpretation>``), and the report
  agent must quote the interval whenever one exists — never a bare
  point estimate.

- **Deterministic model cards per finalized method** — ``urika
  finalize`` now writes ``methods/<name>_model_card.md`` for every
  ``final_methods[]`` entry in findings.json
  (``urika.core.model_cards``, versioned via ``write_versioned``):
  intended use (research question + mode), training data (paths +
  shape from the data profile), metrics incl. CIs from the run record
  matched by ``run_id``, assumptions from the evaluator's persisted
  ``assumptions_detail`` (falling back to findings.json
  ``limitations``), and known limitations. Sections without recorded
  data render "Not recorded for this run." — the generator never
  invents content. Novice audience adds the method-glossary explainer
  line. Pure code, no agent call; best-effort (a failure never blocks
  finalize).

- **Per-project ``projectbook/METRICS.md`` glossary** —
  ``urika.core.metrics_glossary`` (same finalize hook) writes one
  section per metric name observed across the project's runs:
  plain-language definition, range, and how-to-read from a ~15-entry
  static glossary (r2, rmse, mse, mae, accuracy, precision, recall,
  f1, auc, p_value, cohens_d, log_loss, silhouette, aic, bic — with
  alias and suffix matching; unknown metrics render as
  "project-specific" with observed values only), ranking direction
  (signed-magnitude effect sizes like Cohen's d say so instead of
  "higher is better"), observed range + best value across runs, and
  CIs when recorded.

- **Persisted evaluations** — the orchestrator loop now writes each
  experiment's latest parsed evaluation to
  ``experiments/<id>/labbook/evaluation.json`` (overwrite-latest,
  atomic, non-fatal on failure), so the evaluator's
  ``assumptions_detail`` survives the process and reaches the model
  cards and the report agent (whose prompt now points at the on-disk
  path) instead of dying with the run.

- **PDF/LaTeX export** — new ``export`` extra
  (``pip install 'urika[export]'`` → pypandoc; deliberately not
  ``pypandoc_binary`` — no bundled pandoc, no magic downloads) and a
  ``--format markdown|latex|pdf`` option on ``urika report`` and
  ``urika finalize`` (and the REPL/TUI ``/report`` + ``/finalize``
  slashes). Markdown stays the default and the agents stay
  format-agnostic: latex/pdf post-process the markdown artifact the
  normal flow just wrote (``urika.core.export.export_markdown``,
  pandoc with a small margins/sans-headings header include and the
  project on the resource path so relative figure links resolve).
  Three distinct actionable errors: pypandoc missing → install the
  extra; pandoc binary missing → distro install hint (apt/brew/choco);
  PDF without a TeX engine → texlive hint plus the note that
  ``--format latex`` works without one. On any export failure the
  command exits non-zero but the markdown artifact stays in place
  (and the message says so).

- **Jupyter reproduce notebook** — ``urika finalize`` writes
  ``projectbook/reproduce.ipynb`` (``urika.core.notebook_export``;
  ``nbformat`` is now an explicit core dependency): title cell with
  the research question + answer, a setup cell, and one
  markdown-plus-code section per final method embedding the LITERAL
  contents of its standalone script (a missing script degrades to a
  note — the generator never invents code), with key metrics incl.
  CIs and a closing pointer to METRICS.md and the model cards. The
  notebook is validated with ``nbformat.validate`` before writing;
  an execution test on a fresh kernel is gated on ``nbclient``
  availability (in both the unit suite and the e2e smoke).

### Compatibility

v0.9.0 is a strict superset of v0.8.0;
``pip install --upgrade urika`` is sufficient. The new artifacts
(model cards, METRICS.md, reproduce.ipynb, evaluation.json) appear on
the next ``urika finalize`` / ``urika run``;
``RunRecord.metrics_with_uncertainty`` defaults to ``{}`` for legacy
records and the labbook output is byte-identical for runs without
intervals. ``--format`` defaults to ``markdown`` (today's behavior);
the ``export`` extra is only needed for latex/pdf.

### Fixed

- **Project-level presentations now show their figures.** Whole-project
  reveal.js decks (``urika present <project>`` and the final
  presentation from ``urika finalize``) rendered every figure as a
  "Figure missing" placeholder, while experiment-level decks were fine.
  The renderer could only resolve a figure against a single
  experiment's directory; project-level decks span every experiment's
  ``artifacts/``. It now resolves figures across the whole project —
  by bare filename or ``<experiment_id>/artifacts/<file>`` — copying
  each with a collision-safe name (a figure referenced by an
  unresolvable path still shows the visible placeholder). Adds a
  path-traversal guard so a deck can never pull a file from outside
  the project.
- **Dashboard now opens itself in your browser.** The default launch
  generates a per-session auth token; previously it suppressed the
  browser auto-open and printed a long tokenized URL for you to
  copy-paste by hand — and opening the dashboard without that exact
  token (a bookmark, or a terminal click that dropped ``?token=``)
  returned a raw ``{"detail":"Invalid or missing token"}`` JSON error
  page. ``urika dashboard`` now auto-opens the tokenized URL (which
  authenticates and pins the cookie), keeps printing it as an
  SSH/headless fallback, and serves a friendly HTML "access token
  required" page for browser navigations that hit a stale/missing
  token (HTMX/XHR and ``curl`` still get the JSON 401).

## [0.8.0] – 2026-06-10

Research scoping + output polish. The interactive project builder now
elicits genuine research intent (feasibility check, analysis-approach
and interpretability preferences, hypotheses, constraints, co-drafted
success criteria) and persists it on ``ProjectConfig``; the dashboard
gains a full interactive builder wizard with the same loop; and the
generated artifacts (labbook, README, findings.json) gain
plain-language metric interpretations, run-id traceability, and
novice-audience method explainers. Underneath, the v0.7.0 adapters got
a hardening pass: shared error classification, stream timeouts on all
providers, and a fix for the OpenAI $0-usage accounting bug.

### Added

- **Builder research-goal pipeline** — the interactive ``urika new``
  loop (``urika.core.builder_loop.run_builder_loop``) now runs a
  research-question **feasibility check** before the clarifying
  questions (one agent call sanity-checks the question against the
  scanned data; if it flags a concern, the user picks between "Keep my
  question", "Use the refined question", or "Let me rephrase" —
  strictly best-effort, any agent/parse failure skips the step), asks
  fixed **analysis-approach** (statistical / predictive / exploratory /
  mixed) and **interpretability** (interpretable / balanced /
  max_performance) preference questions plus a free-text
  **constraints** question (time/compute budget, regulatory
  requirements), offers an agent-proposed **hypotheses decomposition**
  (1–4 testable hypotheses; accept, skip, or write your own), and
  **co-drafts the initial success criteria** with the user before the
  final refine/accept menu (free-text changes land verbatim as a
  ``user_amendments`` key the evaluator sees as-is). Everything
  gathered is skippable — "done" / "skip" / empty leaves the
  preference unset.

- **Research-intent fields on ``ProjectConfig``** — four new optional
  fields serialised under ``[project]`` in ``urika.toml``:
  ``hypotheses`` (list of strings), ``analysis_approach``,
  ``interpretability_level``, and ``constraints`` (string table).
  Empty means the user skipped; every pre-v0.8.0 project loads
  unchanged with the defaults. The builder seeds the advisor and
  planning agent prompts from these fields so the first experiments
  respect the user's stated approach.

- **Dashboard interactive builder wizard** — the New Project modal's
  "Interactive setup" checkbox now redirects into a full wizard page
  driven by the same ``run_builder_loop`` core as the CLI: SSE-streamed
  agent progress, Q&A turns (``POST /api/projects/{name}/builder/start``,
  ``GET .../builder/stream``, ``POST .../builder/answer``,
  ``POST .../builder/abort``), re-attach on page reload, and
  abort-discards-the-project-to-trash semantics. The modal also gains
  ``web_search`` and ``use_venv`` fields matching the CLI flags.

- **Dashboard planning agent + git pull** — ``POST
  /api/projects/{name}/experiments/{exp_id}/plan`` exposes the
  planning agent from the experiment page (parity with
  CLI/REPL/TUI ``plan``), and ``POST /api/projects/{name}/git/pull``
  plus Init/Pull buttons on the Git tab round out the v0.6.0 surface.

- **REPL/TUI ``/config <provider> --mode``** — ``/config
  anthropic|openai|google [--mode api_key|subscription] [--no-verify]``
  closes the v0.7.0 parity gap (provider auth modes shipped CLI-only).
  The bare form ``/config anthropic`` shows the current mode instead
  of requiring ``--mode`` like the CLI does.

- **Plain-language metric interpretation** — task agents now write one
  sentence per reported metric into the new
  ``RunRecord.metric_interpretation`` dict (keyed by metric name,
  comparing against the success criterion where one is defined), and
  the labbook renders it inline: ``r2=0.74 — Explains 74% of variance
  in the target; the criterion is ≥0.70, so this run meets it.``
  Legacy records load with ``{}`` and render exactly as before.

- **Audience-aware labbook + README** — when the project audience is
  ``novice``, each method heading in experiment notes and the README
  gains a one-line "What this method does" explainer from the new
  ``urika.core.method_glossary`` (covers the 24 built-in tools, with
  fuzzy matching for agent-written variants like
  ``random_forest_tuned`` and library-name aliases).

- **Run-id traceability** — task agents name every figure
  ``<run_id>-<description>.png`` (e.g. ``run-002-confusion-matrix.png``)
  and the labbook attaches figures to runs by run-id prefix first,
  falling back to the old method-name substring heuristic only when no
  run-id-tagged figure exists. ``findings.json`` entries in
  ``final_methods`` must now carry ``run_id`` + ``experiment_id`` for
  every quoted metric, and ``selected_figures`` entries carry the
  producing ``run_id`` — every number in the final report traces back
  to a ``progress.json`` run record.

- **Evaluator ``assumptions_detail``** — the evaluator's
  ``method_validity`` assessment now lists every assumption relevant
  to the methods used (name / test / result / implication), including
  assumptions that were **not** checked, and the report agent is
  instructed to surface assumption checks and violations for every
  statistical claim.

- **Shared adapter error classification + stream timeouts** —
  ``urika.agents.error_classify.classify_error`` (extracted verbatim
  from the Claude adapter) now classifies errors identically across
  Claude, OpenAI, and Google adapters into ``rate_limit`` / ``auth`` /
  ``billing`` / ``transient`` / ``config`` / ``unknown``. OpenAI and
  Google streams gain a silence timeout (``URIKA_AGENT_STREAM_TIMEOUT``
  env var, default 600 s) so a hung SDK stream fails as ``transient``
  instead of blocking forever, and their bash tool wrappers honor the
  project's ``max_method_seconds`` cap via the shared
  ``bash_timeout_seconds`` helper. OpenAI/Google bash subprocesses are
  also spawned with a ``scrub_oauth_env``-cleaned environment.

- **Corrupt-JSON tolerance** — new ``urika.core.json_io``
  (``load_json_or_preserve``) gives the orchestrator session store,
  leaderboard, and knowledge index the same crash-mid-write tolerance
  ``advisor_memory`` has had since v0.4.2: a corrupt file is preserved
  as ``<name>.corrupt-<unix-ts>`` (never clobbering an earlier copy)
  and the caller gets a fresh fallback instead of a crash.

- **Canonical best-run selection** — new
  ``urika.evaluation.ranking.select_best_run`` is the single source of
  truth for "best run". Pre-v0.8.0, four call sites (labbook,
  progress, leaderboard, readme_generator) implemented their own logic
  and could disagree in user-visible artifacts — the README naming one
  best method while the labbook named another. All four now delegate
  to ranking, sharing one ``LOWER_IS_BETTER`` direction table.

### Fixed

- **Run records are now durable even when the task agent's final
  message is cut short.** The task-agent prompt now instructs writing
  each RunRecord to ``labbook/run-<NNN>.json`` as soon as the run
  finishes (the final-message JSON block becomes a summary
  convenience), and the orchestrator's on-disk discovery additionally
  scans ``artifacts/run-*.json`` as a tolerance — previously an agent
  that saved records outside ``labbook/`` produced a "0 runs recorded"
  failure despite real work on disk.
- **Turn-cap exhaustion no longer fails experiments on claude-agent-sdk
  0.2.91+.** The SDK changed its trailing error to ``"Claude Code
  returned an error result: Reached maximum number of turns (N)"``,
  which escaped the adapter's deliberate max-turns-with-content
  tolerance — routine turn-cap exhaustion surfaced as paused
  experiments, failed finalizes, and raw tracebacks. The tolerance now
  matches the new string, errors classify as a friendly ``max_turns``
  category, and ``claude-agent-sdk`` is pinned to ``>=0.2.91,<0.3``.
- **``urika present`` no longer claims success when no deck was
  written.** Project-level presentations sent the agent the prompt
  "Create a presentation for experiment ." (empty id), and the CLI
  printed "Saved to projectbook/presentation/index.html"
  unconditionally even when the agent produced no parseable slide
  JSON. The project-level prompt is now explicit, and the CLI reports
  the real output path on success or a clear error (non-zero exit) on
  failure.
- **OpenAI adapter recorded $0 for every run.** The openai-agents
  SDK's ``RunResult`` has no ``usage`` attribute — usage lives on the
  per-model-response objects in ``RunResult.raw_responses``. The
  adapter read ``getattr(result, "usage", None)`` and silently
  recorded 0 tokens / $0.00 for every successful OpenAI run. Usage is
  now summed across ``raw_responses``, and a real-imports structural
  test pins the SDK surface so this class of drift fails CI.
- **Suffix metrics ranked in the wrong direction.**
  ``metric_direction`` is now suffix-aware: ``val_rmse`` / ``test_loss``
  / ``mean_squared_error`` rank like their base metric (lower is
  better) instead of defaulting to higher-is-better.
- **Orchestrator pauses after 3 consecutive unparseable evaluations.**
  Previously an evaluator that never emitted parseable JSON (prompt
  drift, a model that won't emit JSON) burned silently to
  ``max_turns`` with criteria "not met" every turn; the loop now
  warns per-turn and pauses loudly at 3 so the user can intervene.
- **Failed advisor criteria review now warns.** When the
  pre-completion advisor review errors, the loop completes anyway but
  surfaces a non-blocking warning instead of staying silent.
- **``suggestions/initial.json`` flushed after the interactive
  builder.** On the interactive ``urika new`` path, ``write_project()``
  runs *before* the builder loop, so the advisor suggestions the loop
  produced never reached disk — yet the post-loop "run the first
  planned experiment" offer reads that file.
  ``apply_research_intent()`` now flushes the captured suggestions
  once, after the loop completes.
- **Glob tool denies on unresolvable paths.** When path resolution
  failed, the glob tool fell back to globbing the unresolved root
  instead of honoring the ``_resolve_safe`` deny-on-unresolvable
  contract (the v0.7.0 fix covered the resolution-error branch but not
  the ``resolved is None`` branch).
- **Vault keyring index written atomically with explicit utf-8.** The
  KeyringBackend's name index used a bare ``write_text`` (platform
  default encoding, non-atomic) — a crash mid-write could corrupt the
  index, and non-ASCII secret names broke on Windows ``cp1252``.
- **Dashboard origin guard compares hosts case-insensitively.**
  Hostnames are case-insensitive (RFC 3986 §3.2.2); some clients send
  an upper/mixed-case ``Origin`` host, which the CSRF origin check
  rejected as a mismatch.

### Changed

- **Anthropic auth messaging refreshed for the June 15 2026
  subscription credit-pool policy.** Both auth modes are now
  first-class: ``api_key`` stays the default; ``subscription`` is the
  opt-in path legalised by Anthropic's billing overhaul (Agent SDK
  usage draws from a separate monthly Agent credit pool — $20 Pro /
  $100 Max-5x / $200 Max-20x, no rollover, optional overage at API
  rates). The enforcement layers are reframed accordingly: the
  startup warning is suppressed in subscription mode, the pre-spawn
  ``require_api_key`` refusal applies in ``api_key`` mode only, and
  OAuth-token scrubbing is now **billing hygiene** in ``api_key`` mode
  (a stray parent-shell OAuth token must not silently route charges to
  the subscription credit pool) while subscription mode preserves the
  OAuth-token family as the legitimate auth carrier. Nested-session
  markers are always scrubbed regardless of mode.

### Compatibility

v0.8.0 is a strict superset of v0.7.0;
``pip install --upgrade urika`` is sufficient. The four new
``[project]`` keys in ``urika.toml`` are optional with empty defaults,
``RunRecord.metric_interpretation`` defaults to ``{}`` for legacy
records, and the figure-naming convention only affects newly generated
artifacts — old method-name-matched figures still attach via the
fallback heuristic.

## [0.7.0] – 2026-06-08

Multi-provider model adapters. The same Urika project can now run
experiments against Anthropic, OpenAI, or Google models, with
per-agent provider routing driven by the model string itself —
``claude-*`` routes to the Claude Agent SDK, ``gpt-*`` / ``o3-*`` /
``o4-*`` / ``o5-*`` routes to the OpenAI Agents SDK, ``gemini-*``
routes to Google's Agent Development Kit. No central provider
setting; each agent role can be on a different provider, mixed
freely within a single ``urika.toml``.

### Added

- **OpenAI Agents SDK adapter + ``[openai]`` extra**
  (``pip install urika[openai]``). New ``OpenAIAgentsRunner`` in
  ``src/urika/agents/adapters/openai_agents.py`` translates
  ``AgentConfig`` into the OpenAI Agents SDK's options shape,
  streams messages, accumulates per-call cost via the shared
  pricing table, and surfaces the standard ``AgentResult``
  vocabulary (``tokens_in`` / ``tokens_out`` / ``cost_usd`` /
  ``error_category``) so the orchestrator, leaderboard, and usage
  tracker see identical shapes regardless of which provider ran.

- **Google ADK adapter + ``[google]`` extra**
  (``pip install urika[google]``). ``GoogleADKRunner`` in
  ``src/urika/agents/adapters/google_adk.py`` mirrors the OpenAI
  shape against Google's Agent Development Kit (``google-adk``).
  ``GEMINI_API_KEY`` is registered in the vault's known-secrets
  registry so ``urika config google`` and the dashboard Secrets tab
  both surface it.

- **``urika.agents.tools`` shared layer** — six canonical tools
  (Bash / Read / Write / Grep / Glob / Edit) consumable by any
  adapter, each enforced through the existing ``SecurityPolicy``
  (``writable_dirs`` / ``readable_dirs`` / ``allowed_bash_prefixes`` /
  ``blocked_bash_patterns``). Third-party adapters reuse this layer
  by importing the tool wrappers directly — no re-implementing
  permission logic per provider. The Claude adapter continues to
  use its own SDK-native tool surface; OpenAI and Google adapters
  wire these shared tools into their respective SDK tool registries.

- **``urika.agents.pricing.cost_for()``** — single $-per-1M-token
  table at ``src/urika/agents/pricing.py`` covering all three
  providers (Anthropic Opus 4.7 / Sonnet 4.5, OpenAI GPT-5.4
  family, Google Gemini 3 Pro / Flash). Both new adapters call
  ``cost_for(model, tokens_in, tokens_out)`` so cost reporting is
  uniform across the leaderboard, ``urika usage``, and the
  dashboard Usage page. Gemini rates verified against
  ai.google.dev/pricing on 2026-06-02 (≤200k-token tier).

- **``urika.agents.runner_registry.runner_for()``** — model-prefix
  routing. Callers with a model string in hand (the orchestrator,
  the conversational ``OrchestratorChat``, any per-agent
  configuration consumer) call ``runner_for(model)`` to get the
  correct adapter. Lazy imports inside the function keep
  not-yet-installed extras (``[openai]`` / ``[google]``) from
  failing at collection time — the import error only surfaces if
  the user actually picks a model that needs the missing extra.

- **Anthropic subscription auth path** (opt-in via
  ``urika config anthropic --mode subscription``). Legal after the
  Anthropic Agent SDK announcement's June 15 2026 cutover — users
  with a Pro / Max subscription can now authenticate the Claude
  adapter via ``claude login`` (the Claude Code CLI's OAuth flow)
  instead of an ``ANTHROPIC_API_KEY``. The default stays
  ``api_key`` and the existing ``ANTHROPIC_API_KEY`` path is
  unchanged — subscription mode is fully opt-in.

- **``urika config anthropic|openai|google --mode <api_key|subscription>``**
  — interactive auth setup per provider. ``api_key`` stores the
  provider's key in the vault under the canonical secret name
  (``ANTHROPIC_API_KEY`` / ``OPENAI_API_KEY`` / ``GEMINI_API_KEY``);
  ``subscription`` (Anthropic only) writes the
  ``[anthropic] auth = "subscription"`` toggle into
  ``~/.urika/settings.toml`` after a one-line ``claude login``
  reminder. OpenAI and Google subscription modes are reserved for
  future provider announcements and currently raise a clear
  "not yet supported by <provider>" error rather than silently
  no-oping.

- **``recommended_models_for(provider)``** — per-provider
  reasoning + execution model defaults at
  ``src/urika/core/recommended_models.py``. Returns a
  ``{"reasoning": ..., "execution": ...}`` dict so the dashboard
  Models-tab Provider filter (and the eventual provider-aware
  CLI wizard) can surface the right pair of defaults for each
  provider without hard-coding. The cost-saving "Opus for the
  four reasoning agents, Sonnet 4.5 for the eight execution
  agents" split from v0.4.0 remains the default for Anthropic;
  OpenAI maps to ``gpt-5.4`` + ``gpt-5.4-mini``. Google is the
  asymmetric case: ``gemini-3.5-flash`` for **both** reasoning and
  execution. Reason: ``gemini-3.1-pro-preview`` requires a
  billing-enabled Google AI account (free-tier rate limit = 0), so
  recommending it as the default would block free-tier users at
  first agent call. The Pro row stays in
  ``urika.agents.pricing.PRICES`` and remains selectable from the
  dashboard Models tab, so users with billing can still override
  per-agent and get correct cost reporting.

- **Dashboard Models tab Provider filter** — a three-way toggle
  (Anthropic / OpenAI / Google) on ``/projects/{name}/models`` that
  re-populates the per-agent model dropdowns from
  ``recommended_models_for(provider)`` and that provider's known
  model list. The default on first load remains Anthropic, so
  existing projects render identically.

- **Smoke harness flags** — ``--provider {anthropic|openai|google}``,
  ``--mixed-providers``, and ``--anthropic-auth {api_key|subscription}``
  on ``dev/scripts/smoke-v04-e2e-open.sh``. The operator-driven cut
  criterion now exercises each provider end-to-end (a full project
  build + run + finalize) plus a mixed-providers configuration
  that pins different agents to different providers in one project.

### Backward compatibility

v0.7.0 is a strict superset of v0.6.x.
``pip install --upgrade urika`` is sufficient — existing Claude SDK
users need zero config changes. Specifically:

- ``urika.toml`` schema is unchanged. Existing ``claude-*`` model
  strings continue to route to the same ``ClaudeSDKRunner`` they
  hit today; no migration step is required.
- ``~/.urika/settings.toml`` gains an optional
  ``[anthropic] auth = "api_key" | "subscription"`` key with a
  default of ``"api_key"`` when absent. Pre-v0.7.0 settings files
  are read unchanged.
- The vault gains additive ``OPENAI_API_KEY`` and ``GEMINI_API_KEY``
  entries in ``known_secrets``; pre-v0.7.0 vaults are unaffected
  and continue to work without either key set.
- The dashboard Models tab defaults to the Anthropic provider on
  first load. Existing project pages render identically to v0.6.x;
  the Provider filter is purely additive.

### Known limitations

- **Google ``gemini-3.1-pro-preview`` requires billing.** The Google
  AI free tier has a rate limit of 0 for the Pro preview model, so
  v0.7.0 defaults Google's reasoning + execution recommendations to
  ``gemini-3.5-flash`` for both roles. Users with a billing-enabled
  Google AI account can override per-agent in ``urika.toml``
  (``[runtime.models.<agent>] model = "gemini-3.1-pro-preview"``) or
  via the dashboard Models tab — the Pro row stays in
  ``urika.agents.pricing.PRICES`` so cost reporting works for those
  overrides.
- **20 support-agent call sites still route via ``get_runner()``.**
  ``cli/agents*.py``, ``repl/helpers.py``, and a handful of
  dashboard chat endpoints hard-code the legacy
  ``get_runner()`` factory instead of ``runner_for(model)``. The
  experiment loop is fully migrated — mixed-provider users get
  correct routing on the core planning → task → evaluator →
  advisor cycle — but advisor / finalize / report / memory_curator
  invocations silently fall back to Claude regardless of the
  configured per-agent model. Tracked for a v0.7.1 hotfix.
- **Anthropic subscription auth requires ``claude login`` first.**
  Urika does not run the OAuth flow itself; the Claude Code CLI
  owns that surface. ``urika config anthropic --mode subscription``
  reminds the user to run ``claude login`` before the next agent
  call, and ``urika config anthropic --test`` will detect a missing
  subscription session and print the same hint.

## [0.6.0.1] - 2026-06-01

Windows hotfix. Two pre-existing bugs in the v0.6.0 release were masked
on CI because the v0.6.0 test suite never set ``GIT_AUTHOR_NAME`` /
``GIT_COMMITTER_NAME`` for the runners, so all Windows + Linux jobs
failed at ``git commit`` before reaching the real bugs. After the
ident issue was fixed, two Windows-only failures surfaced — both are
real bugs that would have bitten Windows users in production.

### Fixed

- **``urika.core.atomic_write.os.replace`` retry on Windows
  ``PermissionError``.** Under concurrent contention (many threads
  writing to the same file via ``write_json_atomic`` /
  ``write_text_atomic``), Windows raises ``WinError 5`` because
  another thread holds a microsecond-scale lock on the destination
  during its own replace. POSIX is unaffected. The fix is a
  Windows-only retry loop with exponential backoff (1–80 ms, six
  attempts) wrapping ``os.replace``. The lock window is microseconds
  in practice, so the retries succeed quickly and behavior is
  unchanged on POSIX.
- **Tests now pass ``encoding="utf-8"`` explicitly when seeding
  test fixtures with em-dash content.** Production code already used
  explicit utf-8 everywhere; the tests had three call sites where
  ``.write_text(initial)`` defaulted to ``cp1252`` on Windows, storing
  the em-dash as byte ``0x97``, after which production code's
  ``.read_text(encoding="utf-8")`` crashed with
  ``UnicodeDecodeError``. Affected: ``tests/test_core/test_git.py``
  (4 sites), ``tests/test_core/test_readme_generator.py`` (1 site).
- **``tests/conftest.py`` session-scoped fixture sets
  ``GIT_AUTHOR_*`` / ``GIT_COMMITTER_*`` env vars** so the v0.6.0
  GitHub-test surfaces no longer depend on the developer's
  ``~/.gitconfig``. CI runners on Ubuntu and Windows have no global
  identity by default. macOS happens to come preconfigured, which is
  why this only failed on the other two platforms.

### Tests

Two new regression tests pin the ``_atomic_replace`` retry path on
ALL platforms by monkeypatching ``_IS_WINDOWS`` + ``os.replace``:
``test_atomic_replace_retries_on_windows_permissionerror`` (3-attempt
transient lock succeeds on attempt 3) and
``test_atomic_replace_propagates_after_exhausted_retries`` (all six
attempts fail → ``PermissionError`` propagates).

### Compatibility

This is a pure bugfix release. No CLI, dashboard, or settings changes.
Existing v0.6.0 projects need no migration; ``pip install --upgrade
urika`` is sufficient. Full diff:
[v0.6.0...v0.6.0.1](https://github.com/xkiwilabs/Urika/compare/v0.6.0...v0.6.0.1).

## [0.6.0] - 2026-05-31

GitHub auto-backup. Each Urika project can now be a git repo
automatically backed up to a user-configured remote. **Backup, not
collaboration** — Urika never sees a GitHub credential, never calls
the GitHub API, and stays provider-agnostic (works against any git
remote: GitHub, GitLab, Gitea, Bitbucket, self-hosted). The user's
existing ``git`` auth (HTTPS+PAT, SSH key, ``gh``-stored
credential — anything that already makes ``git push`` work in their
shell) does all the authentication.

This is the thin design. The "Connect GitHub" device-flow OAuth
experience (preserved in ``dev/archive/2026-04-30-github-integration.md``)
is deferred to v1.1+ if real demand surfaces.

### Added

- **``urika github init <project> [--remote URL]``** — initialise the
  project as a git repo, write a researcher-safe ``.gitignore``, set
  ``origin``, and create the initial commit. Idempotent — re-running
  on an existing repo is a no-op for the init step and a
  ``set-url`` for the remote.

- **``urika github init <project> --create [--public]``** — uses the
  ``gh`` CLI (if installed and authed) to create a fresh private
  (default) or public GitHub repo named after the project, set the
  remote, and do the first push in one shot. Wraps ``gh repo create
  <name> --{private|public} --source <dir> --push``. Falls back
  gracefully when ``gh`` is missing or unauthed (prints a one-line
  install hint, exits 2, no partial state).

- **``urika github push / pull / status``** — manual push wraps
  ``git add -A && git commit && git push`` with the **pre-commit
  secret scanner** in front (regex sweep for ``sk-ant-...``,
  ``sk-...`` OpenAI, ``ghp_...``, ``gho_...``, ``ghu_...``,
  ``ghs_...`` GitHub, ``AKIA...`` AWS shapes; aborts with exit code
  3 and ``[urika:secret-detected] <file>:<line>`` if any match).
  ``pull`` does fetch + ff-only merge, refuses on divergence.
  ``status`` shows remote/branch/dirty-count/last-commit/recent.

- **``urika new <name> --github [--public]``** — opt-in at
  project-creation time. After the project wizard's
  ``write_project()`` returns, runs ``urika github init --create``
  with the appropriate visibility. ``--no-github`` skips it even
  when the global preference is set.

- **Global preference: ``[preferences] github_auto_create = true``** —
  in ``~/.urika/settings.toml``. Every ``urika new`` defaults to
  creating a remote; override per invocation with ``--no-github``.
  Companion key ``github_auto_create_visibility = "private"|"public"``
  controls the default visibility.

- **Auto-push hook** — opt-in via ``[github] auto_push = true`` in
  ``urika.toml``. Fires at the end of each command in
  ``[github] auto_push_after = ["run", "finalize", "build-tool"]``
  (the default set). Sequence: stage everything → secret scan →
  commit (with a per-event commit message and the
  ``urika-event: <event>`` trailer) → push. On scan failure, aborts
  without committing. On push failure, prints the verbatim ``git``
  stderr and leaves the local commit intact for the user to retry.
  Wrapped in an outer ``try/except`` so an auto-push failure can
  **never** break the host command. Three CLI commands wired
  (``urika run``, ``urika finalize``, ``urika build-tool``) at four
  call-sites total (``urika run`` has both a meta-experiment and a
  single-experiment success path, both gated on ``run_status ==
  "completed"`` so paused/stopped/failed runs don't trigger).

- **Researcher-safe ``.gitignore`` template** with managed-block
  markers (``# >>> urika: managed block``) so re-running
  ``urika github init`` updates the Urika section in place while
  preserving anything the user added above or below. Defaults
  exclude ``.urika/`` (whole dir — secrets, sessions, meta),
  ``*.lock``, Python build/venv directories, PEM/SSH/dotenv files,
  AND research-data conventions (``data/raw/``, ``*.parquet``,
  ``*.h5``, ``*.pkl``, ``*.joblib``). User can add patterns via
  ``[github] gitignore_extra = [...]`` in urika.toml.

- **Pre-commit secret scanner** (``urika.core.git.scan_for_secrets``)
  scans staged blobs (``git show :<path>``) for known token shapes.
  Binary files skipped via a NUL-byte heuristic. Patterns ordered
  most-specific-first so ``sk-ant-...`` is reported as
  ``anthropic_api_key`` rather than the looser ``openai_api_key``
  pattern. Match preview is masked (first 8 chars + last 4) so the
  user can identify the leak without the full token appearing in
  the error output.

- **Dashboard Git tab** at ``/projects/{name}/git`` — read-only
  status panel (remote URL, branch, dirty count, last commit) plus
  a recent-commits list (with ``urika-event:`` chip per commit) and
  a "Push now" button. When the project isn't yet a git repo, the
  page renders an "Initialise" form (remote URL input) that POSTs
  to ``/api/projects/{name}/git/init``. Sidebar entry between
  Methods and Criteria. Four new API routes:
  ``GET /git/status``, ``POST /git/push``, ``POST /git/init``,
  ``GET /git/log``. ``POST /git/push`` runs the same secret scan
  as the CLI and returns ``409`` with the match details when a
  secret is detected (no commit, working tree unmodified). All
  state-changing routes preserve the v0.4.5.1 CSRF middleware
  (cross-origin requests return 403).

### Architecture

- ``src/urika/core/git.py`` — pure ``git`` (and optional ``gh``)
  ``subprocess`` wrapper. All functions are stateless; errors come
  back as values (``CommitResult``/``PushResult``/``PullResult``/``GhCreateResult``
  dataclasses with ``ok`` + ``error``) rather than exceptions, so
  callers print remediation hints cleanly. ``add_remote`` updates
  the URL when ``origin`` already exists rather than failing.
  ``pull`` fetches the specific branch (not ``FETCH_HEAD``) so a
  fresh remote without upstream tracking still does the right
  thing. ``recent_commits`` parses the ``urika-event:`` trailer
  from commit bodies using a NUL/RS-separated git pretty-format.

- ``src/urika/cli/github.py`` — Click subgroup with four
  subcommands (``init``, ``push``, ``pull``, ``status``) plus the
  ``_maybe_auto_push(project_dir, event)`` helper used by
  ``run``/``finalize``/``build-tool`` tails.

- ``src/urika/dashboard/`` — page route in ``routers/pages.py``,
  four API routes in ``routers/api.py``, template
  ``templates/git.html`` (mirrors the v0.5.0 ``memory.html``
  layout), sidebar entry in ``_sidebar.html``.

### Verified

- 16 implementation tasks, 105 net new tests (3689 total in the
  unit suite, up from 3615), full pytest green.
- Cut criterion #3 verified by an opt-in integration test
  (``tests/test_integration_github_push.py``) that runs ``urika
  new`` + ``urika github init --remote <local-bare>`` + ``urika run
  --max-turns 1`` with a stub agent runner and confirms the bare
  remote received a commit with the expected ``urika-event: run``
  trailer in ~0.3s (vs the 60s cut-criterion budget).
- Secret scanner verified end-to-end: a planted ``sk-ant-...XXX``
  in a staged file aborts ``urika github push`` with exit code 3
  and the file:line of the leak. The dashboard endpoint returns
  409 with the same match details.
- ``gh repo create --push`` integration verified by unit tests that
  mock the ``gh`` invocation; the cut-criterion's "real GitHub
  one-time check" is left to the operator's first invocation
  against their own GitHub account.

### Out of scope (deferred)

- Device-flow OAuth and the dashboard "Connect GitHub" experience —
  preserved in ``dev/archive/2026-04-30-github-integration.md`` for
  a future v1.1+ feature if real demand evidence surfaces.
- GitHub-API-driven repo creation (use ``gh`` CLI instead).
- Audit log viewer in the dashboard.
- Offline commit queue + retry-next-event.
- ``dry_run`` mode that stops before push (the dashboard's
  ``--remote`` form already lets users sanity-check before
  enabling auto_push).
- README auto-management on every event.
- Branch-per-experiment / auto-PR workflows.
- LFS support for large artifacts.
- Multi-remote per project (Urika manages exactly one ``origin``;
  users can add more remotes manually with raw ``git`` if needed).

## [0.5.0.2] - 2026-05-31

Hotfix. After the v0.5.0.1 vault fix unblocked the e2e smoke, the
test ran end-to-end for the first time in two months and surfaced a
second long-standing bug: experiments completed with no leaderboard,
no recorded runs, and no method registry entries despite the task
agent doing real work. Method scripts and run-record JSON files
landed in ``<experiment>/labbook/run-*.json`` as expected, but the
orchestrator never saw them.

Root cause: pre-v0.5.0.2 the orchestrator's run-record harvester only
scanned the task agent's text output for inline ```json blocks. Modern
Claude task agents — especially on Haiku / cheap-config — often skip
inline narration entirely and persist run records exclusively via
``Bash``/``Write`` tool calls. The "no parseable run records" warning
fired every turn while real work was being committed to disk one tool
call away.

### Fixed

- **Orchestrator now reads run records from both channels.** New
  ``urika.orchestrator.parsing.read_labbook_run_records(experiment_dir)``
  enumerates ``<experiment>/labbook/run-*.json`` files and validates
  each with the same field/type checks as ``parse_run_records``
  (shared ``_record_from_block`` helper). The experiment loop
  (``orchestrator/loop.py``) merges text-parsed and disk records by
  ``run_id`` — text wins on duplicate, disk fills in the gaps — so a
  tools-only agent's work lands in the leaderboard, methods registry,
  and progress.json the same way an inline-narrating agent's would.

### Verified

- The open-mode e2e smoke (``dev/scripts/smoke-v04-e2e-open.sh``) was
  re-run end-to-end on the real API after the fix. Run records,
  leaderboard, methods/progress consistency, and the autonomous
  2-experiment pipeline all now pass — the same 8 failures that
  appeared in the v0.5.0.1 e2e flip to green.

## [0.5.0.1] - 2026-05-31

Hotfix. After installing the ``keyring`` extra (e.g. via
``pip install urika[dev]`` or ``urika[all]``), the vault backend
selection at ``urika.core.vault._global_backend`` flipped to the OS
keyring **even when that keyring was empty** — silently stranding any
secrets the user had previously stored via the file backend at
``~/.urika/secrets.env``. ``urika config api-key`` would report the
key was set, ``urika config api-key --test`` would deny it, and every
agent invocation would refuse with ``APIKeyRequiredError: ANTHROPIC_API_KEY
is not set``. The pre-existing bug (since the v0.3.1 vault tiering
shipped 2026-04-29) became reachable once ``pip install -e ".[dev]"``
physically installed the ``keyring`` package alongside an existing
file vault.

### Fixed

- **Vault backend selection now requires a non-empty keyring index.**
  ``_global_backend`` returns the OS keyring only when ``keyring`` is
  reachable AND its sidecar index file (``~/.urika/secrets-index.txt``)
  lists at least one stored key. Otherwise it falls back to the file
  backend at ``~/.urika/secrets.env``. Users who never explicitly
  switched to the keyring backend keep using the file vault even after
  ``keyring`` lands in their Python environment as a transitive
  install. Users who *have* stored keys via the keyring are unaffected
  (their index has entries → keyring stays selected).

## [0.5.0] - 2026-05-31

Memory deepening. v0.4 shipped the project-memory plumbing (auto-
capture + read injection in the planning agent + CLI/REPL/TUI manual
surfaces) but the loop was half-wired: the advisor — the strongest
design-rationale source — never READ what it (or anyone else) wrote
last session, the dashboard had no memory page, and there was no way
to keep the memory directory tidy as projects grew. v0.5.0 closes
that loop. Every agent that benefits now reads memory, every surface
can manage it, and an auto-curator (dry-run by default) keeps the
budget in check.

### Added

- **Advisor and report agents inject project memory** (Decision 1 of
  the v0.5.0 plan). Both roles now compose the same
  ``## Project Memory & Prior Context`` block the planning agent
  uses, delivered via the per-turn user message so the system prompt
  stays byte-stable for the Anthropic prompt cache. The advisor —
  the strongest design-rationale source for capture — now reads what
  it wrote last session; the report agent picks up user preferences
  (tone, audience, prior decisions) and can reference them in
  narrative output. ``format_advisor_context(project_dir)`` and
  ``format_report_context(project_dir)`` are thin delegates to
  ``planning_agent.format_planning_context`` — one shared source of
  truth.

- **Memory curator agent.** A new ``memory_curator`` role
  (``src/urika/agents/roles/memory_curator.py``) proposes four kinds
  of decisions on the memory directory:

  - ``merge`` two entries that make the same load-bearing claim,
  - ``archive`` stale facts (finished experiments, closed PRs),
  - ``flag_stale`` entries whose currency is suspect, and
  - ``flag_contradiction`` between pairs that say opposite things.

  The role is sandbox-locked (no Read / Write / Bash tools, empty
  ``SecurityPolicy``) — it only emits decisions; the apply step
  belongs to a separate code path that the user explicitly invokes.

- **Curator dispatch and auto-trigger (dry-run by default — Decision
  4).** ``urika.core.memory_curator.run_curator(project_dir, runner,
  apply=False)`` invokes the agent, parses decisions, and (when
  ``apply=True``) commits them: merges via concatenation,
  ``archive_entry`` moves to ``memory/archive/<YYYY-MM>/<filename>``,
  flags inject ``flagged_stale: <reason>`` (or ``flagged_contradiction``)
  into the entry's frontmatter idempotently. The orchestrator's
  pre-turn hook (``_maybe_run_curator`` in ``orchestrator/loop.py``)
  runs the curator in dry-run when the session-scoped soft-cap flag
  is set, surfaces proposed decisions through the standard
  ``progress("warning", ...)`` channel (stdout → ``run.log`` →
  dashboard SSE → Slack/Telegram), and clears the flag. Nothing
  mutates without an explicit ``urika memory curate --apply`` (or
  the dashboard "Apply" button).

- **CLI ``urika memory curate [--apply]``** (with same ``--json``
  pattern as the other memory subcommands), **REPL/TUI
  ``/memory curate [--apply]``** (dispatches to the CLI subcommand;
  TUI inherits via ``PROJECT_COMMANDS``), and **dashboard ``POST
  /api/projects/{name}/memory/curate?apply=true``** (with a
  Curate / Apply two-button UI on the memory page that confirms
  before applying and propagates curator errors into the visible
  error field).

- **Dashboard memory page** (the Phase 2 holdover from v0.4 the
  v0.4.5 parity audit flagged as D3). Sidebar entry between
  Knowledge and Methods. List / Add / Delete CRUD via four new API
  endpoints (``GET /api/projects/{name}/memory``,
  ``GET .../memory/{filename}``, ``POST .../memory``,
  ``DELETE .../memory/{filename}``). Filename path-traversal
  rejected (``/``, ``\``, ``..`` → 400). Save returns ``HX-Redirect``
  to the same page so the new entry appears immediately;
  ``hx-on::response-error`` surfaces validation failures so 422s
  no longer silently swallow themselves.

- **Archive viewer + diff view** (Decision 3 — mtime-based). New
  ``project_memory.list_archive(project_dir, month=None)`` enumerates
  archived entries by ``YYYY-MM``; ``project_memory.diff_between(
  project_dir, from_ts, to_ts)`` classifies entries into ``added`` /
  ``archived`` / ``trashed`` buckets from filesystem mtime. Surfaced
  across all three text surfaces:

  - CLI: ``urika memory archive [--month YYYY-MM] [--json]`` and
    ``urika memory diff <from> <to> [--json]`` with a relative-time
    parser accepting ``now`` / ``yesterday`` / ``Nh|Nd|Nw ago`` (or
    the underscore form ``1h_ago``) / ISO 8601.
  - REPL/TUI: ``/memory archive [--month YYYY-MM]`` and
    ``/memory diff <from> <to>``.
  - Dashboard: ``?show_archived=true`` query toggle on the memory
    page, with the archived block rendered below the live list.

- **Per-project ``auto_capture`` toggle.** A checkbox in the
  dashboard memory page header writes ``[memory].auto_capture =
  true|false`` to the project's ``urika.toml`` via a new ``POST
  /api/projects/{name}/memory/auto_capture`` endpoint. Other TOML
  sections (``[project]``, ``[endpoints]``, ``[privacy]``, etc.) are
  preserved on update.

- **Cross-surface parity tests** (``tests/test_cross_interface_parity
  .py``) pin three v0.5.0 contracts: every surface routes curate
  through ``run_curator`` (single source of truth); all surfaces
  write entries to ``<project>/memory/<type>_<slug>.md``; archive
  layout is ``memory/archive/<YYYY-MM>/<filename>`` regardless of
  caller (direct vs curator-apply).

### Changed

- ``load_project_memory(project_dir, session_id=None)`` gained an
  optional session_id parameter. When provided AND the soft cap
  (30 entries OR ~5 000 tokens, Decision 2 byte-heuristic
  ``len(text.encode()) / 3.5``) is exceeded, a flag in
  ``<project>/memory/.curator-flag.json`` is set so the orchestrator
  knows to run the curator in dry-run at next agent invocation. Once
  per session — the flag is cleared after the curator runs (or
  fails) so the same over-budget state doesn't re-fire. Existing
  callers (planning / advisor / report agents — and every test in
  the old test suite) pass no session_id; their behavior is
  unchanged (atomic ``write_json_atomic`` is used for the flag
  to match the post-hardening sweep convention).

- When the **hard cap** (~10 000 tokens) is exceeded,
  ``load_project_memory`` drops the OLDEST entries (by mtime,
  newest preserved) until under cap and replaces the section header
  with ``## Project Memory (over budget — run urika memory curate)``
  so the user sees the situation in the agent's text output. No
  more byte-slicing mid-frontmatter or mid-codeblock.

- The advisor's per-turn context heading changed from
  ``## Research Context (from previous sessions)`` to
  ``## Project Memory & Prior Context`` (the canonical role-symmetric
  heading the planner already uses). Three call sites in
  ``orchestrator/loop.py`` and ``orchestrator/meta.py`` consolidated
  on the shared helper; the old summary-only injection is gone.

### Fixed

- ``/memory curate`` now works from inside the REPL/TUI. The first
  cut of the CLI subcommand called ``asyncio.run(run_curator(...))``
  which raised ``RuntimeError: asyncio.run() cannot be called from a
  running event loop`` when dispatched from the REPL or TUI (both
  run slash commands inline on a live loop). The subcommand now
  detects a running loop via ``asyncio.get_running_loop()`` and
  runs the curator on a fresh loop in a worker thread when one
  exists; the bare CLI path still uses ``asyncio.run`` for
  no-overhead startup.

- The dashboard "Apply" button no longer silently swallows curator
  errors. ``CuratorResult(error=...)`` returned from a soft failure
  is now propagated to the visible error span, and the page only
  reloads on ``d.applied && !d.error``.

### Out of scope (revisit post-1.0 if usage demands)

- Read-memory **tool call** (agents currently get memory as a
  system-prompt prefix; no on-demand ``read_memory(topic)`` tool).
- Memory-aware **turn summarisation** that uses memory to dedupe
  captures at write time (the curator dedupes post-hoc instead).
- Cross-project memory — memory stays project-scoped by design.

## [0.4.5.1] - 2026-05-26

Pre-v0.5 hardening release. A deep review surfaced one silent
data-loss bug, an unauthenticated dashboard surface, a confirmed
per-surface drift regression, and a handful of smaller robustness
gaps. This release closes them all before the v0.5.0 memory-
deepening work begins. No new features — all fixes.

### Security

- **Dashboard ships default-secure.** ``urika dashboard`` with no
  ``--auth-token`` now auto-generates a random token
  (``secrets.token_urlsafe(24)``) and prints the tokenized URL the
  user should open. ``_make_auth_dependency`` accepts the token via
  ``Authorization: Bearer`` header, a ``urika_token`` cookie
  (``httponly``, ``samesite=strict``), or a ``?token=`` query param —
  all compared with ``secrets.compare_digest``. The cookie is set
  automatically on the first valid ``?token=`` request so HTMX/Alpine
  XHRs stay authenticated. ``--no-auth`` (with a red warning) opts
  back into the old open mode for users who deliberately want it.
  ``create_app(auth_token=None)`` is unchanged so the test suite still
  exercises both modes.
- **CSRF / cross-origin guard.** A new middleware in
  ``dashboard/app.py`` rejects state-changing requests (anything not
  ``GET``/``HEAD``/``OPTIONS``) whose ``Origin`` header doesn't match
  the request's ``Host`` — closing the cross-origin form-POST vector
  that was reachable from any web page the user visited while the
  dashboard ran on localhost. Applies in both auth and no-auth modes.
- **SSRF blocklist on the endpoint probe.** The dashboard's
  ``/settings/test-endpoint`` route (and any future caller that opts
  in) now resolves the URL host via a new ``urika.core.netguard``
  module and refuses to open it if any resolved A/AAAA record is
  private, loopback, link-local, reserved, multicast, or unspecified
  — defeating the cloud-metadata (``169.254.169.254``) / RFC1918 /
  internal-admin oracle a logged-in dashboard user could otherwise
  build. Redirects are also disabled on the probe opener so a public
  URL can't ``302`` into a private address. The CLI ``urika config``
  endpoint test stays opt-out (a user typing their own Tailscale /
  LAN endpoint isn't an SSRF vector), and the privacy preflight to a
  user-declared private LLM endpoint is deliberately exempt and
  documented as such.
- **Slack inbound fails closed without an allowlist.** Previously
  ``SlackChannel._is_authorized`` returned ``True`` when both
  ``allowed_channels`` and ``allowed_users`` were unset — meaning any
  workspace member could trigger ``pause``/``stop``/``ask``. It now
  returns ``False``, logs a one-time ``DISABLED`` warning telling the
  user to configure an allowlist, and matches Telegram's already-
  strict ``chat_id`` posture. Telegram's high-priority metric values
  are also HTML-escaped now (the key was escaped but the value
  wasn't, under ``parse_mode="HTML"``).
- **Vault secret-removal write is atomic.** ``vault._remove_env_key``
  used ``path.write_text(...)`` then ``path.chmod(0o600)``, leaving a
  brief window where the rewritten secrets file had default umask
  perms. It now routes through the same ``write_text_atomic(..., mode
  =0o600)`` helper the create / upsert paths use, so the 0600 bits
  are baked in at ``O_CREAT|O_EXCL``.

### Fixed

- **Output parser no longer drops run records that embed a code
  fence in a string value.** ``_extract_json_blocks`` used a
  non-greedy ``re.compile(r"```(?:json)\s*(.*?)```")`` that stopped
  at the **first** ``` it saw — so a task-agent record whose
  ``observation`` or ``hypothesis`` quoted a ```python snippet got
  truncated mid-JSON, ``json.loads`` raised, and the block was
  silently skipped. The downstream effect was severe: an experiment
  whose only run records all embedded fences recorded zero runs and
  was marked ``failed`` despite real work; the same truncation also
  defeated ``parse_evaluation`` so ``criteria_met`` could go
  unrecognised and the loop ran to ``max_turns`` wondering why
  criteria never matched. The parser now does brace-balanced
  extraction from each ``json`` opening fence (honouring string
  literals and escapes), falling back to the legacy slice only when
  balancing fails. The scan cursor also advances past balanced
  regions so a quoted ``json`` opener inside an already-parsed string
  value no longer fires a spurious "Skipping malformed JSON block"
  warning.
- **Advisor no longer loses ALL method context when one methods.json
  row is malformed.** ``_determine_next`` did ``m['name']`` (direct
  key access) inside a ``for m in methods[-20:]`` loop wrapped by an
  outer ``except Exception: pass``. One row missing ``name`` raised
  ``KeyError``, the except swallowed it, and the entire method-
  context block — every well-formed row — dropped out of the advisor
  prompt with no signal, degrading next-experiment suggestions. The
  loop is now defensive at the row level (``m.get("name",
  "<unnamed>")``, guarded non-dict ``metrics``), and the broad
  ``except`` logs at ``debug`` instead of silent ``pass`` so future
  failures are observable.
- **Stopped runs no longer get finalized.** ``run_project``
  computed its finalize-skip predicate from ``is_pause_requested()``
  only, so a run that broke out via ``is_stop_requested()`` (the
  dashboard's stop button) fell through to ``finalize_project`` —
  finalizing a project the user had explicitly stopped. The gate now
  matches the loop's own exit semantics (``is_pause_requested() or
  is_stop_requested()``).
- **TUI live output panel no longer leaks ``ESC 7`` / ``ESC 8`` /
  OSC bytes.** The hardened ANSI-stripping regex added in v0.4.4.3
  (covering CSI + OSC + Fe + Fp incl. DECSC/DECRC) lived only in
  ``orchestrator/run_log.py``; ``tui/capture.py`` still had the old
  CSI-only regex its own comment admitted didn't cover OSC or 8-bit
  CSI. The TUI panel could therefore re-leak the same bytes
  ``run_log`` was specifically fixed to strip. Both call sites now
  import ``strip_ansi`` from a new ``urika.core.ansi`` module — one
  shared source of truth for ANSI stripping across all surfaces.
- **Session lock creation is atomic.** ``acquire_lock``'s final
  step was ``path.write_text(str(os.getpid()))`` — truncate-then-
  write, non-atomic. A concurrent ``acquire_lock`` racing past the
  stale-lock unlink could read the half-written empty file, deem it
  stale, unlink the live lock, and both processes proceed. The
  create now goes through ``os.open(..., O_CREAT|O_EXCL|O_WRONLY,
  0o644)`` so creation itself is the exclusivity primitive — the
  empty-lock TOCTOU window is gone.
- **``_DAEMON_THREADS`` no longer grows unbounded in the dashboard
  process.** The list of spawned reaper / drainer threads in
  ``dashboard/runs.py`` was append-only; in a long-lived dashboard
  every run / finalize / advisor / etc. spawn slowly leaked a
  ``Thread`` object plus its closure. Registration now prunes
  finished (``not is_alive()``) entries on each append.
- **``_toml_value`` no longer emits invalid TOML for unknown
  types.** Values that weren't str / bool / int / float / list / dict
  (``Path``, ``datetime``, tuples) fell through to ``return
  repr(val)``, producing output (``PosixPath('/x/y.csv')``) that
  ``tomllib.load`` couldn't parse — same failure family as the
  v0.4.4 control-char bug. Unknown types are now encoded as a TOML
  basic string via the same helper the dict-key branch uses.
- **REPL ``/run --resume`` works from local typed input.** Only the
  remote Slack / Telegram path threaded ``--resume`` (via
  ``_parse_remote_run_args``); the local handler hard-coded
  ``resume=False`` in its ``ctx.invoke(cli_run, ...)`` call, so
  typing ``/run --resume`` in the REPL or TUI silently dropped the
  flag. ``--resume`` is now parsed from local typed args too.

### Changed

- **Experiment commands have consistent ``experiment-<verb>``
  aliases.** CLI uses space-subcommands (``experiment create`` /
  ``experiment delete`` / ``experiment list``); the REPL had a mix
  of ``/experiment-create``, ``/delete-experiment``, and
  ``/experiments``. The REPL registry now exposes
  ``/experiment-delete`` and ``/experiment-list`` aliases pointing at
  the same handlers; the old names keep working for back-compat. The
  TUI inherits both via the shared ``PROJECT_COMMANDS`` registry, so
  this lands on all three surfaces without a TUI-side change.



Surface parity track. The CLI / TUI / REPL / dashboard had drifted —
one feature on one surface, a different flavour on another, and one
real blocker (the dashboard's new-project flow skipped the
interactive Q&A loop that ``urika new`` runs). v0.4.5 closes that
blocker, fills in the missing TUI / REPL / dashboard commands, and
adds a cross-surface parity test class that pins the four major
shared paths so future refactors can't accidentally re-fork them.

### Added

- **Dashboard interactive new-project wizard.** A new
  ``/projects/{name}/builder`` page drives the same agent Q&A loop
  that ``urika new`` runs in a TTY — clarifying questions, advisor
  suggestions, planning agent, refinement choice. Built on three new
  endpoints (``POST /builder/start``, ``GET /builder/stream`` SSE,
  ``POST /builder/answer``) plus an ``abort`` endpoint that
  cancels the background task and trashes the partial project. The
  builder loop body lives in a new ``urika.core.builder_loop`` core
  module with injectable ``ask_user`` / ``emit`` callbacks; CLI and
  dashboard both route through it.

- **REPL ``/unlock`` command.** Stale-lock recovery without
  dropping to a shell. Mirrors ``urika unlock`` semantics
  (``--force`` to override the live-PID safety check) and uses
  the same ``urika.core.unlock.try_unlock`` helper as the CLI and
  the new dashboard endpoint, so all three surfaces stay in lockstep.

- **Dashboard per-experiment Unlock button.** Shown on the
  experiments page whenever a ``.lock`` is on disk but the
  experiment isn't actively running. Tries the safe path first; on
  a live-PID refusal, surfaces a confirm dialog with a
  context-appropriate message (urika-looking vs. recycled-PID) and
  retries with ``force=true``. Calls a new
  ``POST /api/projects/{name}/experiments/{exp_id}/unlock`` endpoint.

- **REPL ``/secret`` command** (also reachable from the TUI via the
  shared REPL command registry). ``/secret list`` enumerates the
  global vault (names only, never values). ``/secret set NAME``
  prompts for a masked value on a real TTY; refuses on non-TTY
  stdin (TUI worker dispatch, CI scripts) and redirects to the CLI
  / dashboard so a secret value never lands in TUI scrollback.
  ``/secret delete NAME`` confirms and removes.

- **``urika.core.unlock``** — new module exposing ``try_unlock`` +
  ``list_locked_experiments`` + ``UnlockStatus`` enum + frozen
  ``UnlockResult`` dataclass. Single source of truth for stale-lock
  recovery semantics; the CLI / REPL / dashboard surfaces all route
  through it.

- **``urika.core.builder_loop``** — new module exposing
  ``run_builder_loop`` (async, injectable callbacks) +
  ``BuilderEvent`` / ``BuilderQuestion`` / ``BuilderAborted``.

### Changed

- **``urika unlock`` (CLI) refactored** to route through
  ``urika.core.unlock.try_unlock`` instead of inline PID-safety
  logic. User-visible output strings unchanged; existing 7
  CLI-unlock tests still pass.

- **``_run_builder_agent_loop`` (CLI) reduced to a 100-line wrapper**
  that injects prompt_toolkit-based ``ask_user`` and ThinkingPanel /
  print_* ``emit`` callbacks. The loop body — ~290 lines — moved to
  ``urika.core.builder_loop.run_builder_loop`` so the dashboard can
  drive the same logic. CLI behaviour unchanged.

### Tests

47 new tests across the three tracks:

- **Track 1 — 4 builder-loop parity tests** in
  ``test_cross_interface_parity.py::TestBuilderLoopInvocationParity``.
- **Track 2 — 26 tests** across new files
  ``test_repl/test_cmd_unlock.py``, ``test_repl/test_cmd_secret.py``,
  ``test_dashboard/test_api_unlock.py``, plus
  ``test_cross_interface_parity.py::TestUnlockHelperParity``.
- **Track 3 — 17 cross-surface parity tests** in 4 new classes:
  ``TestNotificationAutoSeedParity``, ``TestPauseFlagPathParity``,
  ``TestCriteriaMetEarlyExitParity``, ``TestSettingsCascadeParity``.

Full suite: 3442 passed / 2 skipped under ``URIKA_HOME=/tmp/empty/``.

### Notes

The parity audit that drove this release surfaced several
**false-negative gaps** — features the first audit pass thought
were missing on the dashboard but actually worked (advisor chat
composer + streaming, pause button, new-experiment modal,
summarize button, resume endpoint). Those didn't need any new
code; only the D1 blocker (interactive builder Q&A loop) was real.

Similarly the TUI: it inherits the REPL's ``PROJECT_COMMANDS``
registry, so REPL ``/inspect``, ``/update``, etc. already worked
from the TUI all along. The audit's T1 / T2 / T3 gaps collapsed
to just "add ``/unlock`` and ``/secret`` to the REPL — TUI
inherits them for free".

## [0.4.4.4] - 2026-05-16

Tiny follow-up release. One production-code fix; the other changes are
test infrastructure that doesn't ship to the public repo. Surfaced by
the first post-billing CI run after v0.4.4.3.

### Fixed

- **REPL `/run` now self-heals dead-PID lockfiles on Windows.** The
  `cmd_run` lock-detection branch used POSIX-only
  `os.kill(int(pid_str), 0)` + a `ProcessLookupError` catch to probe
  PID liveness — the same bug `session.py:acquire_lock` already
  fixed in v0.4.2.1 (commit 74cde602). On Windows `os.kill(dead_pid,
  0)` raises `OSError(WinError 87)`, not `ProcessLookupError`, so
  the catch never fired and dead-PID locks stayed forever. The v0.4.2
  REPL split (ccbb5df7) re-introduced the buggy pattern in the
  freshly-extracted `cmd_run`; the Actions billing block from
  2026-05-13 to 2026-05-15 hid the resulting CI failure across four
  intermediate dev pushes. `cmd_run` now routes through
  `session._pid_is_alive` (psutil-backed, cross-platform) and also
  aligns the empty-lock case with `session.py`'s "treat as stale"
  semantic — pre-fix the REPL prompted the user for an empty lock
  while `acquire_lock` silently cleaned it on the next call, an
  internal inconsistency.

## [0.4.4.3] - 2026-05-15

Hotfix release. Closes four bugs reported by a Windows user whose
~26-hour autonomous run got stuck mid-stream, plus the capped-mode
safety net surfaced by the v0.4.4.2 e2e smoke.

### Fixed

- **Orchestrator no longer hangs forever on a stalled API call.** The
  Claude Agent SDK adapter's `async for msg in query(...)` loop had
  no wall-clock cap, so a stream that went silent mid-experiment left
  the process alive — animating the TUI spinner, doing nothing else
  — with no error and no recovery path. The reporter's run sat in
  this state for hours before the process eventually died, leaving a
  stale lock the dashboard couldn't clear. Each `__anext__` is now
  wrapped in `asyncio.wait_for` with a configurable cap (default
  600s, override via `URIKA_AGENT_STREAM_TIMEOUT`). A silent stream
  surfaces as a `transient` failure — the experiment pauses, the
  lock is released, and `urika run --resume` (or `/resume` in the
  TUI) picks it back up. The SDK's claude-cli subprocess is reaped
  via `aclose()` on the timeout path so nothing leaks.
- **`urika status` no longer says "pending" while an experiment is
  actually running.** The status field in `progress.json` was only
  written on terminal states (completed / failed / stopped), and
  `urika status` reads `progress.json` — so it lied about state for
  the entire duration of every run. `start_session` / `pause_session`
  / `resume_session` now mirror their session status into
  `progress.json` so the CLI and dashboard listings reflect reality
  during the run, not just after it ends.
- **`run.log` no longer fills with TUI spinner ANSI escapes.** The
  ThinkingPanel writes raw cursor save/restore + scroll-region +
  colour escape sequences via `sys.stdout.write` at ~8 frames/second.
  The reporter's 26-hour run accumulated ~344 MB of escape codes in
  `run.log`. Worse, the constantly-ticking mtime made monitoring
  tools (and the user) think the run was still doing real work when
  the agent had hung mid-stream — compounding the hang above. The
  orchestrator's stdout tee now strips CSI / OSC / Fe / Fp escape
  sequences before writing to disk. Terminal output is unchanged.
- **`urika results` now explains the discrepancy with `urika status`'s
  run count.** `status` counts every run in `progress.json`; `results`
  (without `--experiment`) counts leaderboard entries, which are
  best-per-method. A run that doesn't improve any method's best is
  silently dropped from the ranking — so the reporter saw `status`
  say "8 runs" and `results` show 7 rankings with no explanation.
  `results` now emits a footer "Showing M of N runs (leaderboard
  keeps best-per-method; …)" when M < N, and the `--json` output
  adds `total_runs` + `ranked_runs` fields.
- **`--max-experiments N --auto` now actually runs N experiments
  even when the advisor bails after one.** Surfaced by the v0.4.4.2
  e2e smoke: the existing fresh-project safety net only fires when
  no experiments exist yet, so a request for 2 experiments with the
  advisor saying "done" after #1 collapsed to 1 experiment with no
  user-visible explanation. Adds a mode-gated safety net that fires
  only in `capped` mode (the user explicitly asked for N) —
  `checkpoint` and `unlimited` modes are unchanged. The net tries
  one explicit re-prompt first, then seeds a deterministic
  robustness-check experiment so the slot does real work.

### Notes

- Issue 2 from the same Windows report (stale `.lock` blocking the
  dashboard's "running" indicator) was **already fixed** in v0.4.2.1's
  PID-aware `acquire_lock` self-heal and the dashboard's pages
  helper that uses `_is_active_run_lock`. The user's symptom — having
  to manually delete the lock — was the downstream effect of the
  API-hang above: when the orchestrator can't exit, the normal
  pause / fail / complete paths that call `release_lock` never run.
  With the timeout in place a hung stream becomes a `transient`
  failure that pauses the experiment cleanly.

## [0.4.4.2] - 2026-05-13

Tiny follow-up release. One production-code fix; the rest of the work
since v0.4.4.1 is test infrastructure that doesn't ship to the public
repo.

### Fixed

- **`urika run` on a brand-new project no longer silently bails when
  the advisor produces nothing usable.** The non-`--auto`
  single-experiment path (`cli/run_planning._determine_next_experiment`)
  had the same flaw the v0.4.4 fix closed for `--auto`/`--max-experiments`
  in `orchestrator/meta.run_project`: if the advisor's call failed or
  its reply had no parseable `suggestions` block, the function returned
  `None` and the run exited "nothing to do" — leaving the user with a
  freshly-created project that never ran. It now seeds a deterministic
  `baseline` experiment in that case (only on a fresh project — no
  change when there are completed experiments and "no suggestion"
  legitimately means "done").

## [0.4.4.1] - 2026-05-13

Hotfix release. Closes four beta-user-reported bugs that v0.4.4 didn't
touch — three of them in code paths the test suite had never exercised.

### Fixed

- **`urika new` crashed the interactive builder** with "Agent loop
  unavailable (sequence item 1: expected str instance, list found).
  Continuing with manual setup." — `cli_display.format_agent_output`
  did `" — ".join([strategy, metrics])` where `metrics` is a **list**
  (which is exactly the schema the planning agent's own prompt example
  shows: `"metrics": ["metric_name"]`). The renderer now flattens
  lists / any non-str value where prose is expected;
  `data/profiler.profile_dataset` also coerces column *names* to `str`
  at the source (pandas hands back tuples for a `MultiIndex`, ints for
  integer headers — and several consumers do `", ".join(columns)`).
- **A hybrid / private-mode experiment was thrown away after several
  turns** when a transient blip hit the data agent — the SDK transport
  surfaced a ResultMessage flagged is_error with a bogus message as
  `Exception("Claude Code returned an error in error result: success")`
  (seen against local endpoints), and the loop treated *every*
  data-agent failure as a permanent hard fail, discarding the work done
  on earlier turns. A recoverable data-agent failure now **pauses** the
  session (`urika run --resume` re-runs the turn) — only an `auth`
  failure hard-fails. `_classify_error` now tags
  `"returned an error in error result …"` and
  `"fatal error in message reader"` as `transient`.
- **`urika usage` didn't count the `urika new` builder loop** — the
  project_builder / advisor / planning agent calls there were invisible.
  The builder loop now accumulates token / cost usage across all its
  agent calls and records one session.
- **A research question / description containing a `\r` (Windows line
  ending), a tab, or any control character produced invalid
  `urika.toml`** — the encoder only escaped `\`, `"`, `\n`, so
  `tomllib.load` then failed everywhere downstream. (Plausible cause of
  "the dashboard create button doesn't work when I type a real
  question; entering 'x' in every field works".) Replaced with a proper
  TOML basic-string encoder: named escapes for `\b \t \n \f \r`,
  `\uXXXX` for the remaining control chars.

### Added

- Tests for all of the above — including `format_agent_output` (which
  had no test coverage at all), `_classify_error` on the SDK relay
  quirk, builder-loop usage recording, the data-agent pause-vs-fail
  policy, and `urika.toml` round-tripping with quotes / backslashes /
  CR-LF / tabs / control chars / unicode.

## [0.4.4] - 2026-05-13

Robustness release. Closes a family of "the experiment exited looking
fine but did nothing" failure modes, makes every failure visible
instead of silent, and — most importantly — gives the end-to-end smoke
real teeth so a green e2e run actually implies the agents, files, and
process steps all completed and produced real results. The unit suite
also never makes a real API call, so a companion set of tests guards
the prompt↔parser contract and the loop's "messy LLM output" paths,
which the mocked tests could never exercise.

### Fixed

- **A flaky agent error no longer kills the experiment.** A failed
  agent turn now *pauses* the session (resumable via `urika run
  --resume`) instead of hard-failing it — except for genuinely
  unrecoverable `auth` errors. Pre-fix, any error the SDK adapter
  couldn't categorise ("unknown" — a momentary connect blip, an
  SDK-internal decode hiccup, a bare "Command failed with exit code N")
  hard-failed the experiment, frequently on turn 1 since the planning
  agent is the first SDK call every turn. A bare CLI exit-N with no
  diagnostic is now classified as `transient` (→ pause-and-resume).
- **`urika run --max-experiments N` no longer exits with 0
  experiments** when the advisor's first reply has no parseable
  `suggestions` block. On a brand-new project it now retries once with
  an explicit nudge and, failing that, seeds a deterministic baseline
  experiment so the orchestrator still does real work. A mid-project
  advisor *call failure* is now distinguished from "the advisor chose
  not to suggest anything" and surfaced as such.
- **An experiment that ran every turn but recorded zero runs is now
  `failed`** (with a clear message and a resume hint), not silently
  `completed` with an empty `progress.json` and no `methods.json`.
  Each turn that produces no parseable run record now emits a `warning`
  progress event; so do an evaluator response with no `criteria_met`
  block and a planning agent that produces no parseable method plan.
  These previously failed completely silently.
- **Stale lock self-heal: a recycled PID no longer wedges resume.** A
  `.lock` left behind by a crashed run whose PID the OS has recycled to
  an unrelated (non-python/urika) process is now treated as stale and
  cleared, so `urika run --resume` works without a manual `urika
  unlock`.
- **Dashboard: the New Project modal's `private_endpoint_name` is
  honoured** — the chosen endpoint is pinned under the new project's
  `[privacy.endpoints.private]` (422 on an unknown name). Previously
  the field was posted but silently ignored.
- **Dashboard: a run that failed to launch no longer shows "completed".**
  The run-log SSE stream reports `failed` when `run.log` carries a
  `URIKA-LAUNCH-FAILED:` marker.
- **Dashboard: `POST /run` self-heals a pre-v0.4.3.1 bare project** by
  running the idempotent `enrich_workspace` (scan → profile → criteria
  → README) when `criteria.json` is missing, so older dashboard-created
  projects become usable on their next run.
- **Sandbox tool denials and malformed-JSON-block drops now log at
  WARNING** (were INFO/DEBUG), so a run drowning in `permission_check
  denied` or an agent emitting unparseable JSON is diagnosable from
  `run.log` / the dashboard SSE feed.
- **Dashboard: invalid `pattern` regex on the project-name input.**
  `pattern="[a-z0-9][a-z0-9-]*"` is rejected by modern Chromium's
  `/v`-mode pattern parsing (`Uncaught SyntaxError`), so client-side
  name validation silently didn't run. Hyphen escaped:
  `[a-z0-9][a-z0-9\-]*`.

### Added

- **`task_agent` prompt: a "Bash sandbox restrictions" section** — no
  shell pipes / redirection / `&&` / `;` / heredocs; write a script
  file and run it, capture output from inside Python. (The agent was
  burning turns fighting the sandbox.)
- **The end-to-end smoke (`dev/scripts/smoke-v04-e2e-*.sh`) now asserts
  the agents did real work, not just that commands exited 0**: `>=1`
  run with a non-empty metrics dict; `methods.json` ↔ `progress.json`
  ↔ `leaderboard.json` mutually consistent; `>=1` diagnostic figure;
  every experiment dir recorded `>=1` run; `findings.json` carries an
  `answer` and `>=1` final method; `requirements.txt` lists real
  packages; `reproduce.sh` has a shebang, references `requirements.txt`,
  and runs a `methods/final_*.py`; `>=1` syntactically-valid standalone
  `final_*.py`; and (under `URIKA_SMOKE_REAL=1`) `requirements.txt`
  actually installs in a clean venv. Plus `verify_no_early_exit_markers`
  now also flags a turn-1 pause.
- **A nightly CI workflow (`.github/workflows/e2e-smoke.yml`)** that
  runs the cheap-config open-mode e2e smoke (sonnet + haiku, ~$0.50,
  ~10–15 min) on a schedule and on demand. Skipped on the public
  mirror.
- **Test coverage for the failure modes above**: a prompt↔parser
  contract test (extracts the `json` example from each role prompt and
  asserts the matching parser accepts it); messy-LLM-output loop tests
  (no fence / truncated / empty / error string → `warning` + `failed`,
  not silent `completed`); finalize-sequence content tests
  (`final-report.md` written iff substantial, presentation rendered,
  README embeds the findings answer); `methods.json` self-heal tests
  (malformed records don't crash `register_method`); `urika run`
  outcome-surfacing tests (a `failed` / `paused` run is visibly
  reported — which the TUI/REPL inherit); and a real-browser dashboard
  test driving the "+ New project" modal and asserting the created
  project is enriched, not a bare skeleton.

## [0.4.3.1] - 2026-05-11

Hotfix release. Closes a SecurityPolicy enforcement hole, hardens the
project method registry against malformed records, fixes the
dashboard's New Project flow so it actually runs the project builder,
and lands a community-contributed TUI keybinding.

### Security

- **Sub-agent sandbox escape blocked.** A `task_agent` could spawn an
  `Agent` / `Task` sub-agent that runs with its own un-sandboxed tool
  config and never returns through `can_use_tool` — a hole in the
  SecurityPolicy enforcement added in v0.4.1. `permission.py` now
  denies `Task` / `Agent` / `ToolSearch` outright (new
  `_SANDBOX_ESCAPING_TOOLS`), and `claude_sdk.py` appends them to
  `disallowed_tools` so the model never sees them. On a real
  autonomous run a spawned sub-agent overwrote project-root
  `methods.json` with a record missing `name`, which crashed the next
  turn's `register_method` with `KeyError: 'name'`.

### Fixed

- **Method registry hardened.** `register_method` /
  `update_method_status` use `m.get("name")` instead of `m["name"]`;
  `load_methods` validates the file shape (top-level dict, `methods`
  list, each entry a dict with a str `name`) and drops malformed
  entries, self-healing the file on the next write. The
  `KeyError: 'name'` crash can't recur even if something writes a bad
  record. `task_agent_system.md` also gained an explicit "Files you
  must NEVER write to" section (`methods.json`, `criteria.json`,
  `leaderboard.json`, `advisor-history.json`, `.urika/`, `urika.toml`)
  — the v0.4.3 cache-reuse prompt reorder had softened the original
  "only write inside `{experiment_dir}/`" instruction.
- **Dashboard New Project now runs the builder.** `POST /api/projects`
  previously only laid down a bare workspace skeleton and stashed the
  form's `instructions` field for a never-shipped future phase.
  Dashboard-created projects ended up missing the `[data]` block, drift
  hashes, runtime defaults, seeded criteria, README narrative, and
  knowledge ingestion that `urika new` provides automatically. New
  `project_builder.enrich_workspace()` runs the non-interactive subset
  of the builder (scan → profile sample → `[data]` block + data
  hashes → runtime defaults → docs/papers ingestion → seed criteria →
  regenerate README) right after workspace creation. Best-effort
  throughout — non-existent paths are skipped silently, so the
  existing bare-skeleton contract for callers POSTing fake paths still
  holds. The interactive scoping agent loop stays out of the HTTP
  handler; the stashed instructions are reserved for a future async
  background-builder pass.

### Added

- **Ctrl+Y copies the last response (community contribution).** New
  Ctrl+Y keybinding in the TUI copies the most recent
  orchestrator/free-text response to the system clipboard via
  `pyperclip`, with a toast confirming the copy and showing a 60-char
  preview. Covers both the primary free-text path and the remote-drain
  branch (incoming Slack/Telegram). Falls through gracefully — empty
  response → warning toast, `pyperclip` failure (no `xclip`/`xsel` on
  headless Linux) → error toast, never a crash. Thanks to Chris Lam.

## [0.4.3] - 2026-05-10

Prompt cache-reuse + cross-platform CI release. Three structural
changes to how agent prompts are assembled cut Anthropic input-token
costs by roughly 10× on autonomous-mode runs (validated end-to-end
against the real API at 90.9% cache-hit ratio). Plus a full GitHub
Actions matrix across Linux + macOS + Windows × Python 3.11 + 3.12,
27 new tests across the prompt-cache and E2E coverage tracks, and a
real-API validation harness anyone can re-run to verify the fix on
their own setup.

### Added

- **Cross-platform CI matrix.** GitHub Actions now runs the full
  test suite on `ubuntu-latest`, `macos-latest`, and `windows-latest`
  × Python 3.11 and 3.12 (6 jobs per push). Lint runs once on the
  Ubuntu+3.12 canonical job. Catches platform-specific regressions
  the previous Linux-only matrix missed (the v0.4.2.1 Windows lock
  bug is the canonical case study).
- **Real-API cache validation harness.** `dev/scripts/validate-cache-reuse.sh`
  + `parse-cache-trace.py` run a minimal autonomous experiment with
  `URIKA_PROMPT_TRACE_FILE` set, then report per-agent cache hit
  ratios. ~$0.20, ~10 min wall-clock. Re-runnable on any setup with
  `ANTHROPIC_API_KEY` configured.
- **End-to-end test coverage gaps closed (Track 2).** 25 new
  integration tests across 4 files:
  - REPL via `pexpect` (4 state-based tests).
  - TUI via Textual `Pilot` + stub agents (3 tests).
  - Dashboard via headless `playwright` (9 tests against a real
    uvicorn-served app).
  - Backwards-compatibility fixtures: 3 legacy project shapes
    (empty-lockfile, corrupt-progress, no-runtime-block) + 9
    execution tests pinning the v0.4.2 self-heal behaviour.
  - Cheap-config smoke variant (`URIKA_SMOKE_REAL=0` env-var) that
    runs the full e2e harness against sonnet+haiku at reduced
    max-turns instead of opus, dropping per-iteration cost ~10×.

### Changed

- **Tier-1 prompt cache reorder (7 role prompts).** `task_agent`,
  `evaluator`, `advisor_agent`, `planning_agent`, `report_agent`,
  `presentation_agent`, and `orchestrator` all moved
  `{experiment_id}` and `{experiment_dir}` from the prompt header
  into a trailing **Experiment Context** appendix. Mid-body
  references reworded from `{experiment_dir}/methods/` to
  descriptive language ("the `methods/` subdirectory of the
  experiment workspace"). Net: 95-98% of each role's system
  prompt is byte-stable across consecutive experiments in the
  same project; the cached prefix carries through the 5-min TTL
  window. Autonomous-mode runs (`urika run --max-experiments N`)
  benefit most.
- **Planning agent memory moved to per-turn user message.**
  `planning_agent.build_config` previously prepended project
  memory + advisor context summary to the system prompt — any
  change to either invalidated the entire 5.9KB base prompt's
  cache. New `format_planning_context(project_dir)` helper
  carries the same content via the per-turn user message instead;
  the system prompt is now byte-stable across sessions even when
  memory entries are added.
- **Audience block moved to per-turn user message.** The 3
  narrative agents (report, presentation, finalizer) previously
  substituted `{audience_instructions}` directly into their
  system prompt body — three audience modes
  (novice/standard/expert) produced three different system
  prompts per role. New `format_audience_context(audience)` helper
  keeps the system prompt byte-stable across audiences; switching
  modes within the cache TTL now hits cache.

### Fixed

- **Cross-platform PID-alive check in `project_delete.py`.**
  Pre-fix this module had its own `os.kill(pid, 0)` probe that, on
  Windows, calls `TerminateProcess(pid, 0)` rather than the benign
  existence check it returns on POSIX. The dashboard's
  delete-project flow self-terminated whenever the locked PID
  matched the test process. Routed through the cross-platform
  `core/session.py::_pid_is_alive` helper that already uses
  `psutil.pid_exists`. (The same hazard had already been fixed in
  `session.py` for v0.4.2.1; the duplicate site here was missed.)
- **Lazy scipy imports in 4 statistical tools** (`mann_whitney_u`,
  `one_way_anova`, `paired_t_test`, `descriptive_stats`). scipy
  1.17.1 ships a Windows packaging bug where any
  `from scipy.stats import …` triggers a broken
  `scipy.signal._signal_api` import and raises `NameError` at
  module load. Affected every `urika tools` listing call on
  Windows. Imports moved inside the tools' `run()` methods so
  metadata listing doesn't load scipy at all.
- **API-key warning suppressed in `--json` mode.** The startup
  warning when `ANTHROPIC_API_KEY` is unset previously leaked into
  every `--json`-mode CLI test on machines without the key set
  (CliRunner mixes stderr into stdout by default), failing every
  JSON-parsing test in CI. Extracted to a testable helper that
  gates on `is_interactive_stderr()`; the warning still prints in
  real interactive shells.

### Internal

- **27 new prompt cache regression tests.** `tests/test_agents/test_prompt_cache_stability.py`:
  - 7 per-role tests asserting >=90% common-prefix between
    different `experiment_id` values (catches Tier-1 regressions
    where a per-experiment placeholder leaks back into the body).
  - 1 byte-identity-within-experiment test (catches
    non-determinism — timestamps, PIDs — sneaking into the
    builder).
  - 1 planning_agent-stable-across-memory-changes test (catches
    rec #2 regressions).
  - 3 audience-stable-across-modes tests (catches rec #3
    regressions).
  - 2 helper-content tests proving the moved blocks still surface
    via the user-message context (proves the refactor moved
    content rather than dropping it).
- **Tests marked `@pytest.mark.integration`** for real-LLM and
  external-tool tests so the per-PR CI gate's `-m "not integration"`
  filter excludes them. Affected: `TestReportCommand` (3 tests),
  `TestRunCommand::test_run_no_experiments`, the smoke harnesses.
- **Cross-platform test fixes** (incidental work surfaced by the
  new Windows CI):
  - `test_output_json_handles_non_serializable` no longer hardcodes
    `'/tmp/test'` as the expected path string.
  - `test_agent_run_start_ms_is_monotonic` polls until the clock
    increments instead of relying on a fixed 10ms sleep (Windows
    monotonic clock has 15.6ms resolution).
  - 4 CliRunner+uvicorn tests skipped on Windows (CliRunner+Click
    signal-handler interaction; real `urika dashboard` /
    `urika advisor` work fine on Windows in interactive use).
- **`pexpect` and `playwright` added to the `[dev]` extras** for
  the new smoke harnesses.
- **`pytest-timeout` added to the CI install line** with
  `--timeout=300` per-test ceiling. Catches hung tests cleanly
  instead of stalling the whole run via runner-level kill.

## [0.4.2.1] - 2026-05-09

Hotfix release for two beta-user-blocking bugs reported on Windows
+ hybrid mode. Both issues caused projects to become unusable
after the first failed run; this release restores self-healing
behaviour for all platforms.

### Fixed

- **Privacy preflight inherits global endpoints (all platforms).**
  Hybrid/private projects whose URL matched a globally-configured
  `[privacy.endpoints.private]` were left without a project-level
  endpoint block in `urika.toml` (the project_builder's
  "skip duplicate write" optimisation). The runtime loader at
  `agents/config.py:340-349` already inherited from globals, but
  the per-turn privacy preflight in `core/privacy.py` did not —
  so every hybrid run failed turn 1 with "No private endpoint
  configured for hybrid mode" even when the global endpoint was
  reachable. `check_private_endpoint` now mirrors the inheritance
  pattern; project-level values still win on collision. Self-heals
  existing affected projects without requiring a re-save.
- **Cross-platform stale-lock self-heal (fixes Windows blocker).**
  Pre-fix `acquire_lock` used `os.kill(pid, 0)` and only treated
  `ProcessLookupError` (Linux ESRCH) as a dead PID. Windows
  `os.kill(dead_pid, 0)` raises `OSError(WinError 87, "The
  parameter is incorrect")`, which the catch-all
  `except OSError: return False` misclassified as "process is
  alive". Result: after any experiment failure on Windows, the
  `.lock` file never self-healed and every subsequent run hit
  "Experiment is already running (PID X is alive)" until the user
  manually ran `urika unlock`. Linux self-healed; Windows did not.
  Routed PID-alive checks through `psutil.pid_exists` (now an
  explicit dependency, was already a transitive dep on most
  installs), with an `os.kill` fallback for the rare case where
  psutil itself fails to import. Also fixes `urika unlock`'s
  process-name surfacing — pre-fix it read `/proc/<pid>/comm`
  directly which was Linux-only, leaving Windows + macOS users
  with a less-informative safety prompt.

### Internal

- 12 new regression tests (4 privacy, 8 session) including a
  Windows-simulated dead-PID test that monkeypatches `os.kill` to
  raise `WinError 87` — verifies the fix without needing Windows
  in CI. The pre-existing `test_hybrid_no_endpoint_fails` was made
  hermetic via `URIKA_HOME` monkeypatch (was implicitly relying on
  the developer's `~/.urika/settings.toml` being empty).

## [0.4.2] - 2026-05-07

Hardening release driven by a comprehensive 6-surface code audit
(CLI, TUI, Dashboard, Core, Code health, Tests) plus two beta-user
bug reports (advisor→/run silent failure, agent simulating data on
first experiments). Eleven internal "packages" of fixes, 2844 tests
passing (+161 new), zero regressions.

### Security

- **OAuth scrub completeness** — `core/compliance.py::_OAUTH_TOKEN_VARS`
  was defined but never used; only two of nine OAuth/identity tokens
  were blanked when spawning the bundled `claude` CLI subprocess.
  Critically, `CLAUDE_CODE_OAUTH_REFRESH_TOKEN` was left live, so
  the access-token blank could be re-minted by the subprocess. Now
  the constant is iterated and includes all 9 OAuth tokens (refresh,
  identity, websocket-auth, file-descriptor variants) + 9 nested-
  session markers (CLAUDE_CODE_SESSION_ID/KIND/NAME/LOG, REMOTE,
  TMUX, AGENT, ACTION, RESUME).
- **Privacy fail-closed on corrupt config** — `core/privacy.py` and
  `agents/config.py` no longer silently default to "open mode" when
  `urika.toml` fails to parse. `FileNotFoundError` → open
  (legitimate), `TOMLDecodeError` → fail-closed with a clear error.
- **Endpoint hostname check** — `agents/config.py:194` URL match
  changed from substring (`"anthropic.com" in url`) to
  `urlparse().hostname` + suffix match. Closes
  `http://anthropic.com.evil.com` getting cloud's larger context-
  window allocation.
- **Vault file race closed** — `vault.py` `FileBackend` now creates
  files via `os.open(O_CREAT|O_EXCL, 0o600)` instead of write-then-
  chmod. No window between file creation and mode set during which
  another local user could read.
- **`urika new --json` requires `--overwrite`** — pre-fix the
  flag-less `--json` path silently `shutil.rmtree`'d any existing
  project of the same name (data loss for scripted-create users).

### Added

- **Atomic JSON state writes** — new `core/atomic_write.py`
  (`write_text_atomic`, `write_json_atomic`) using temp-file +
  `os.replace` + parent-dir fsync. Migrated 9 sites: `registry.py`,
  `orchestrator_sessions.py`, `session.py`, `advisor_memory.py`,
  `progress.py`, `criteria.py`, `method_registry.py`, `usage.py`,
  three sites in `vault.py`. SIGTERM mid-write no longer corrupts
  state files. Advisor history corrupt-file is preserved as
  `.corrupt-<ts>.json` instead of silently zeroed.
- **Real-data-only enforcement** — `task_agent_system.md` and
  `data_agent_system.md` now have explicit "Critical: Real Data
  Only" sections forbidding data simulation, fabrication, or
  substitution. Lists canonical forbidden patterns
  (`np.random.normal` for inputs, `sklearn.datasets.make_*`,
  hardcoded `pd.DataFrame({...})` literals, `simulate_*` /
  `fake_*` / `dummy_*` helpers, "simulating because too long"
  comments) with explicit allowed-uses-of-randomness carve-out for
  legitimate train/test shuffling, bootstrap resampling FROM real
  data, model init, CV seeds. STOP-and-report instead of substitute
  when data genuinely cannot be loaded.
- **Runtime data-integrity scanner** — new `core/data_integrity.py`
  scans each turn's method scripts for real-data signals
  (`pd.read_*`, `np.load`, project `data_paths` basenames, urika
  tool imports) and synthetic-data signals (`make_*`, `simulate_`
  helpers, "synthetic data" comments). Emits a SUSPECT warning to
  the live log + dashboard SSE when a turn produces synthetic-only
  runs, so the suspicion lands in `run.log` rather than being
  silently recorded as a real result.
- **`urika unlock <project> [exp_id]`** — new CLI command for
  clearing stale lockfiles. Safe by default: refuses to unlock if
  the lock's PID is alive AND its process name (via
  `/proc/<pid>/comm`) looks like Urika. `--force` overrides for
  PID-recycle false positives. Closes the user-reported "stops
  with lockfile message on a project from an older release" flow.
- **`/setup` slash registered in TUI/REPL** — pre-fix `"setup"`
  was listed in `tui/app.py::_WORKER_COMMANDS` but had no handler;
  typing `/setup` printed "Unknown command".
- **Five missing slash commands wired** — `/summarize`,
  `/sessions [list|export]`, `/memory [list|show|delete]`,
  `/venv [create|status]`, `/experiment-create` now reachable from
  the TUI/REPL with the same effect as the equivalent shell
  commands.
- **getpass bridge for the TUI** —
  `tui/agent_worker._install_getpass_bridge` patches
  `click.termui.hidden_prompt_func` once at import. Pre-fix
  `click.prompt(hide_input=True)` (4 sites in `cli/config.py` for
  API-key entry plus `cli/config_notifications.py` for SMTP
  password) called `getpass.getpass`, which on POSIX opens
  `/dev/tty` directly, bypassing both `sys.stdin` and the TUI's
  stdin bridge — the prompt blocked indefinitely.
- **Vendored htmx, alpine, chart.js** under
  `dashboard/static/vendor/`. Dashboard now works offline / air-
  gapped. Pre-fix these loaded from unpkg.com / cdn.jsdelivr.net.
- **Sidebar links for Compare + Criteria** — both pages rendered
  correctly but were reachable only via deeplink.
- **SSE disconnect detection** — all 5 SSE endpoints
  (`/runs/<id>/stream`, `/finalize/stream`, `/summarize/stream`,
  `/tools/build/stream`, `/advisor/stream`) now poll
  `request.is_disconnected()`. Pre-fix a closed browser tab left
  the generator polling disk every 0.5s until the lockfile
  disappeared, leaking coroutine slots under load.
- **Per-project `context_window` + `max_output_tokens`** form
  fields on the dashboard's project Settings → Privacy tab. The
  v0.4.1 fields were on global Settings only; the per-project API
  parser silently dropped them when typed in the per-project form.
- **`pytest` markers `slow` and `integration`** registered in
  `pyproject.toml`. Long-running SSE tests + the pytest-wrapped
  smoke harness (`tests/test_smoke/test_smoke_open.py`) marked
  appropriately. Default `pytest` is now ~1 minute (down from ~7).
- **`urika logs` actually tails `run.log`** — pre-fix the
  docstring claimed "Show experiment run log" but the body only
  printed `progress.json` runs/metrics; `run.log` was never
  opened. `--summary` preserves the legacy progress-summary view;
  `--tail N` controls trailing line count.

### Changed

- **Empty legacy lockfiles treated as stale unconditionally** —
  pre-v0.3 (commit 2fdae4b4) `acquire_lock` used `path.touch()`
  which created EMPTY lock files. Current release ALWAYS writes
  the PID. Pre-fix the acquire-lock code refused for 6 hours
  after an empty lock's mtime — catching brand-new releases
  bouncing off ancient locks left over from pre-v0.3 crashes.
  Now: any empty lock = pre-v0.3 leftover = stale, clean it up
  immediately. Better error message in `start_session` points the
  user at the new `urika unlock` recovery command.
- **`/advisor` invokes the actual `advisor_agent` role** — pre-fix
  `cmd_advisor` delegated to `_handle_free_text` which runs
  `OrchestratorChat` (a different agent with a different system
  prompt and no access to `advisor_memory`). The shell `urika
  advisor` always invoked the real role; the slash now matches.
  Persists exchanges via `advisor_memory.append_exchange`,
  parses suggestions on the response.
- **TUI free-text injection blocked while busy** — pre-fix the
  TUI queued the text and replayed it after the worker exited,
  with stale-context, drain-race, and silent-bury problems plus
  inconsistency with the REPL's blocking-prompt model. Now: a
  one-line panel hint pointing the user at /stop, /pause, or
  "open another terminal for a parallel chat." Slash dispatcher
  also rejects free-text during non-/run agents (where queued
  text was previously dead-stored). Reader-feed and queue-during-
  /run paths preserved (legitimate uses for click.prompt
  injection inside the orchestrator loop).
- **/pause cooperative flag only written during /run or /resume**
  — pre-fix typing `/pause` during `/finalize` or `/report` wrote
  a `pause_requested` flag that the next /run picked up and
  immediately paused on. Now `cmd_pause` checks
  `active_command in ("run", "resume")`.
- **/resume preserves `advisor_first` + `review_criteria`** — pre-
  fix /resume silently dropped both flags to False even when the
  original /run had them on. Now read from `[preferences]` in
  `urika.toml` and forwarded through `ctx.invoke(cli_run, ...)`.
- **Remote `/run` accepts `--no-advisor-first` / `--advisor-first`**
  — pre-fix the worker hardcoded `advisor_first=True` for remote
  callers, leaving Slack/Telegram users unable to opt out.
- **Remote command map driven by the live registry** — pre-fix
  `_REMOTE_COMMAND_MAP` was a hardcoded list of 9 names that
  drifted away from the registry; new v0.4.2 slashes were silently
  unreachable from Slack/Telegram. Now built from `GLOBAL_COMMANDS
  ∪ PROJECT_COMMANDS` minus an explicit `_REMOTE_BLOCKED_COMMANDS`
  block-list (interactive editors, destructive admin actions).
- **REPL `/summarize` runs as an agent command** — pre-fix it ran
  on the main thread and blocked the prompt for the duration of a
  multi-minute agent call.
- **REPL parses advisor suggestions on free-text reply** — pre-fix
  `_handle_free_text` defined `_offer_to_run_suggestions` a few
  lines below but never called it; the REPL had the same advisor→
  /run silent-fail-to-pending bug as the TUI. Now both UIs are
  parity-locked on the suggestion path.
- **Update banner suppressed under `--json`** — pre-fix a user
  running `urika list --json` from an interactive TTY got a banner
  prepended to the JSON document, breaking parsers.
- **`cli/run_planning.py::_best_metric_val` honors
  `_LOWER_IS_BETTER`** — pre-fix `max(nums)` ranked RMSE=12.3
  above RMSE=0.42 (worst-as-best for error metrics). Now prefers
  a higher-is-better metric when present and inverts when only
  lower-is-better metrics are available.
- **`packaging.version.Version` for update comparison** — pre-fix
  `_parse_version` truncated at first non-int (`0.4.0rc1` → `(0,4)`
  → equal to `0.4.0` → wrong pre-release ordering).
- **Token accounting separates fresh / cache-create / cache-read**
  — `AgentResult` gained `input_tokens_only`, `cache_creation_in`,
  `cache_read_in` fields. `core/usage.py::estimate_cost` applies
  Anthropic's 1.25× cache-creation premium and 0.10× cache-read
  discount when the breakdown is supplied. Pre-fix everything was
  billed at fresh-input rates, overstating cost for cache-heavy
  workloads.
- **TUI `/pause` reachable while busy** — pre-fix
  `_ALWAYS_ALLOWED_COMMANDS = {"quit", "stop"}` rejected `/pause`,
  making the documented "pause mid-experiment" feature
  structurally unreachable from the TUI.
- **TUI remote chat parses suggestions** — Slack/Telegram users
  hit the same advisor→/run silent fail bug that Package H fixed
  for the local InputBar path; the parallel `_run_remote_chat`
  worker is now updated too.
- **`set_agent_active` initialises the processing clock** — pre-
  fix only `set_agent_running` set `_processing_start`, so REPL
  paths (which only call `set_agent_active`) accumulated zero
  processing time. Every REPL session logged `processing_ms=0` to
  `usage.json`.
- **`clear_project` mirrors `load_project`** — pre-fix it only
  nulled three fields, leaking notification-bus thread, pending
  suggestions, and usage counters across project deletions.
- **REPL `cmd_advisor` correctly handles `_run_single_agent`'s
  `str` return type** — caught the I-7 regression where the
  `result.get(...)` call swallowed an AttributeError and silently
  no-opped both `append_exchange` and `parse_suggestions`.

### Fixed

- **Orchestrator leaderboard inside the per-run loop** — pre-fix
  the leaderboard update sat OUTSIDE the inner `for run in runs:`
  loop, referencing the loop variable after iteration ended. On
  any turn that produced multiple runs (multi-method exploration,
  ensemble experiments) only the LAST run's metrics ever reached
  the leaderboard.
- **JSON-fence regex accepts single-line code blocks** — pre-fix
  the regex required a literal newline between the language tag
  and body, silently dropping ` ```json {...} ``` `.
- **`parse_run_records` validates metrics is a dict** — pre-fix
  an agent emitting `"metrics": "great"` (string) created a
  RunRecord whose downstream consumers crashed on `.values()`.
- **Email channel health check** — pre-fix returned `(True, "")`
  for any relay that accepted NOOP without auth even when
  `MAIL FROM` would be rejected at send time. Now probes
  `MAIL FROM` when no password env is configured.
- **`UserCancelled` detected by `isinstance` not string compare**
  — pre-fix `type(exc).__name__ == "UserCancelled"` would match
  any class anywhere named UserCancelled.
- **`cli_display._is_tty()` re-evaluates per call** — pre-fix
  `_IS_TTY` was frozen at import; Textual swaps `sys.stdout` after
  import, turning spinners into permanent no-ops in the TUI.
- **Orchestrator session ID collision at second resolution** —
  pre-fix `_timestamp_id` returned `%S` precision; two sessions
  in the same wall-clock second collided. Now appends a 4-hex
  random suffix.
- **Empty-string secrets distinguishable from unset** — vault
  `get` uses `is not None` checks at all 3 tiers.
- **Bare `except:` in `core/session.py:165`** narrowed to
  `except Exception:` so `KeyboardInterrupt` propagates cleanly.

### Removed

- **TypeScript TUI launcher (`urika tui` CLI command)** — the TS
  TUI was archived to `dev/archive/typescript-tui/` and gitignored
  from main, but the launcher in `src/urika/cli/tui.py` shipped on
  main as a discoverable command pointing at vaporware. The
  Python Textual TUI (`urika` no-args, the documented default) is
  unchanged.

### Internal

- 161 new tests across 12 new test files plus updates to existing
  tests for the new contracts. Suite now 2844 total (1 skipped),
  runs in ~65 seconds (down from ~7 minutes after the slow-marker
  hardening + sleep removals).
- 5 of 45 audit findings refuted by direct code reading rather
  than agent reports — caught two false-positive "fixes for fixes"
  before they shipped.

## [0.4.1] - 2026-05-03

Hardening release. No new feature surface — closes the v0.4.x bug
backlog discovered after v0.4.0 shipped, plus instrumentation for
the prompt-bloat investigation that ultimately deprioritised the
work originally planned. Hybrid-mode E2E smoke run end-to-end
against the marketing dataset (vLLM + Anthropic split, 50 agent
calls, 87.5% cache hit, no `ContextWindowExceededError`).

### Added

- **Per-endpoint `context_window` + `max_output_tokens`** on
  `[privacy.endpoints.<name>]`. Closes the v0.4 E2E private-mode
  smoke regression where local vLLM endpoints (32K window)
  returned HTTP 400 `ContextWindowExceededError` because the
  bundled `claude` CLI defaulted to a 32K output request that
  alone filled the window. Auto-default by URL: `anthropic.com` →
  200000 / 32000 (no behaviour change for cloud), anything else →
  32768 / 8000 (conservative; leaves 24K for input). Forwarded to
  the CLI via `CLAUDE_CODE_MAX_CONTEXT_TOKENS` and
  `CLAUDE_CODE_MAX_OUTPUT_TOKENS` env vars. Configurable via the
  dashboard's Settings → Privacy tab and via `urika.toml` /
  `~/.urika/settings.toml` directly.
- **Per-Bash-tool-call timeout cap** via
  `[preferences].max_method_seconds` (default 1800 s = 30 min).
  Pre-fix a deadlocked training script (infinite loop, stuck GPU
  op, hung network call) could wedge an experiment for hours. The
  `can_use_tool` permission callback now clamps every Bash tool
  call to the configured ceiling via
  `PermissionResultAllow.updated_input`. Smaller-than-cap requests
  pass through unchanged so quick health checks stay fast. 0 /
  negative falls back to the default — no "no-cap" mode by design.
- **CLI launcher: "Run autonomously (no prompts)" option.** The
  bare `urika run <project>` settings dialog gained an `Autonomous`
  status line in the header and a new menu option that flips
  `auto=True` for a single-experiment run. Pre-fix users who
  expected the loop to flow advisor → planner → run without
  confirmation had to know about the `--auto` flag.
- **`URIKA_PROMPT_TRACE_FILE` instrumentation.** When set,
  `ClaudeSDKRunner.run` appends one JSONL record per agent call
  with system / prompt bytes, tokens broken down by
  input / cache_creation / cache_read, output tokens, and
  duration. Companion script `dev/scripts/analyze_prompt_trace.py`
  summarises the per-agent table. Off by default — zero overhead
  beyond an env-var lookup.
- **Cookbook docs page**
  `21-cookbook-long-running-training.md` covering the
  multi-minute-per-method project shape: `max_turns` sizing,
  budget calibration, stop / resume semantics, the prompt-trace
  loop, and a defensive metric-write template.

### Fixed

- **SIGTERM after criteria met no longer downgrades completed
  status.** Pre-fix the dashboard's Stop button (or any SIGTERM)
  arriving while `_generate_reports` was producing the
  per-experiment narrative overwrote the on-disk `completed`
  status with `stopped` and exited 1. A successful run with a
  user-abandoned cosmetic narrative pass showed up as a failure.
  `stop_session` now refuses to downgrade a terminal status; the
  CLI's signal handler exits 0 when it detects the
  already-completed case and prints a clarifying message.
- **Documentation page on pip-installed Urika** now works.
  Pre-fix the dashboard's `/docs` page rendered `Documentation
  not available` and linked to a placeholder
  `github.com/yourorg/urika` URL because `docs/` only shipped
  with editable installs. The wheel now bundles the `docs/` tree
  at `urika/_docs/` via `hatch.build.targets.wheel.force-include`
  and the resolver checks the bundled location. Empty-state copy
  + GitHub link fixed to point at the real repo.
- **Sessions tab empty-state copy** re-written to disambiguate
  what creates sessions (Advisor tab, `urika advisor` CLI, TUI
  free-text) from what doesn't (`urika run`, `urika finalize`).
  Pre-fix users who ran `urika run` and saw an empty Sessions tab
  assumed the feature was broken.

### Investigated, not changed

- **Prompt-bloat global trim (originally v0.4.1 #2):** dropped.
  Live-trace data from a real run showed 88.6% prompt-cache hit
  ratio and a 200:1 output:fresh-input token ratio. Trimming
  user-prompt blobs would save tens of fresh input tokens per
  turn against an output stream of ~21K tokens — not a meaningful
  lever. Plan rewritten in
  `dev/plans/2026-05-02-prompt-bloat-and-context-budget.md` —
  the per-endpoint declarations above (Layer 2 in the original
  plan) were kept because they solve a different problem
  (local-model context exceeded); the global audit (Layer 1) is
  cancelled.

## [0.4.0] - 2026-05-02

First feature-complete v0.4 release. Bundles every v0.4 track
(SecurityPolicy enforcement, multi-provider runtime abstraction,
project memory Phase 1, experiment comparison view, dataset hash +
drift detection, cost-aware budget, shell completion, sessions list/
export) plus Windows hardening, sensible defaults, and per-agent
model curation discovered during pre-release testing.

### Added (post-rc2)

- **Reasoning vs execution model split** — when the user picks Opus
  as the open-mode or hybrid-mode default in `urika config`, the
  wizard now auto-pins **reasoning agents** (`planning_agent`,
  `advisor_agent`, `finalizer`, `project_builder`) to that Opus
  tier and **execution agents** (`task_agent`, `evaluator`,
  `report_agent`, `presentation_agent`, `tool_builder`,
  `literature_agent`, `data_agent`, `project_summarizer`) to
  `claude-sonnet-4-5`. Sonnet performs indistinguishably from Opus
  on "execute this plan" / "format these numbers" / "apply rule to
  metric" tasks and saves ~5× per call. Net ~50–65% cost reduction
  per experiment with zero quality impact. Sonnet/Haiku defaults
  skip the split entirely (already at the cheaper tier). Single
  source of truth in new `urika.core.recommended_models`.
- **`urika config [PROJECT] --reset-models`** — re-applies the
  reasoning/execution split to an existing project's `urika.toml`
  or, without `PROJECT`, to every configured mode in
  `~/.urika/settings.toml`. Idempotent. Hybrid projects keep their
  data-agent + tool-builder private-endpoint pin across the
  rebuild. Designed for upgrading from pre-v0.4.0 settings files
  or after manual drift.
- **Dashboard "Reset to recommended defaults" button** on the
  Models tab in both `/settings` (global) and `/projects/<n>/settings`
  (project-scoped). New endpoints: `POST /api/settings/models/reset`
  and `POST /api/projects/<n>/settings/models/reset`. Same shared
  helper as the CLI flag; confirmation dialog + Alpine-driven
  progress + inline success/failure message.

### Changed (post-rc2)

- **Per-experiment finalize no longer auto-writes the project-level
  narrative.** The post-criteria-met sequence in
  `orchestrator/loop_finalize._generate_reports` was running TWO
  agent-written narratives back-to-back: the experiment-level
  one (`experiments/<id>/labbook/narrative.md`, fast and
  per-experiment) and a project-level one
  (`projectbook/narrative.md`, summarising "all experiments and
  the research progression"). The project-level pass added
  10–25 minutes of cloud-LLM tail to every successful
  experiment and is fundamentally redundant — `urika report`
  produces the same narrative on demand with a leaner prompt,
  and `urika finalize` produces the canonical
  `projectbook/final-report.md` from the structured
  `findings.json` at end-of-project. Removed the inline pass;
  per-experiment narrative + per-experiment presentation are
  unchanged. **Agent feedback loop is unaffected** — the planner
  and advisor never read `projectbook/narrative.md`; their
  cross-experiment memory is `methods.json` + `criteria.json`
  + `advisor-history.json` + `advisor-context.md` (rolling
  summary refreshed per advisor call) + project memory.
- **`max_turns_per_experiment` default unified at 5** across every
  surface (was 10). Five sites flipped (factory `settings.py`, CLI
  fallback, TUI defaults helper, dashboard New-Experiment modal,
  dashboard global Settings page). Cap on a stuck-loop experiment's
  worst-case spend drops from ~$1+ to ~$0.50; well-set criteria
  still converge in 2–3 turns. Override per experiment via
  `urika run --max-turns N` or per project via `[preferences]
  max_turns_per_experiment`.
- **Dashboard New-Experiment modal max-turns input** now reads from
  the project's `[preferences].max_turns_per_experiment` (with
  global-default fallback) rather than hardcoding the value.
  Editing the project-level preference now flows through to the
  modal — single source of truth.

### Fixed (post-rc2)

- **Bearer-token auth for non-Anthropic private endpoints.** The
  bundled Claude Agent SDK CLI sends the auth header based on
  which env var it sees: `ANTHROPIC_API_KEY` → `x-api-key`,
  `ANTHROPIC_AUTH_TOKEN` → `Authorization: Bearer`.
  api.anthropic.com expects the former; vLLM, LiteLLM, OpenRouter,
  and most OpenAI-compatible private endpoints expect the latter
  and 401 with "Ensure Key has 'Bearer ' prefix" otherwise. Pre-fix
  urika set `ANTHROPIC_API_KEY` for all configured endpoints, so
  every private-mode agent call 401-ed. Two-part fix: (a)
  `urika.agents.config.build_agent_env_for_endpoint` now sets
  `ANTHROPIC_AUTH_TOKEN` (and clears `ANTHROPIC_API_KEY`) for
  non-Anthropic base URLs; (b)
  `urika.core.compliance.scrub_oauth_env` no longer
  unconditionally blanks `ANTHROPIC_AUTH_TOKEN` — it preserves
  deliberately-set values (the parent-leakage protection still
  blanks the var when absent). `CLAUDE_CODE_OAUTH_TOKEN` is still
  unconditionally blanked (no legitimate use in a Urika subprocess).
- **System claude CLI v2.1.124+ trailing exit-1 in streaming mode.**
  The system-installed `claude` CLI (which urika prefers for newer
  request schemas, e.g. `claude-opus-4-7`) exits 1 in streaming
  bidirectional mode *after* successfully streaming the final
  `ResultMessage`. Pre-fix, every multi-agent step in urika
  (advisor, build-tool, plan, run, evaluate, report, present,
  finalize) treated this as a hard failure even though the work
  completed cleanly. The adapter now detects "we already saw a
  clean ResultMessage" (`num_turns > 0` AND `not is_error`) and
  returns `success=True` with the captured state. Counter-cases —
  exit before any ResultMessage (credit-low, auth) and exit after
  `is_error=True` — still propagate as failures with the
  classified category. Also installs a `logging.Filter` on
  `claude_agent_sdk._internal.query` that drops the SDK's noisy
  `Fatal error in message reader: ...` log line when our adapter
  has already tolerated the error. Captures the bundled CLI's
  stderr for the first time so future post-stream errors actually
  reach urika logs (the SDK transport hardcoded a useless
  placeholder before).
- **`urika new` no longer spawns live agent under non-TTY stdin.**
  Two paths in `urika new` invoked the project-builder LLM agent
  loop with no stdin guard: the clarifying-questions loop and the
  post-creation "offer to run an experiment" prompt (whose
  default-on-EOF auto-fired `urika run`). Every CliRunner-based
  unit test of `urika new` was silently making real API calls
  until something killed it, and any CI script running
  `urika new --data foo.csv` without `--description` was paying
  for an unwanted agent loop. Both paths now skip when
  `sys.stdin.isatty()` is False or `URIKA_NO_BUILDER_AGENT=1` is
  set. `--json` mode was already safe via its own fast path.
- **Windows: SSE log streamers crashed on cp1252 bytes** (e.g.
  `0x97` em-dash) emitted by the bundled claude CLI's tool-use
  markers. All ten SSE endpoints (`run` / `evaluate` / `report` /
  `present` / `finalize` / `summarize` / `build-tool` / `advisor`
  / `_log` paths in `dashboard/routers/api.py`) now open log files
  with `errors="replace"` so a stray byte renders as `?` instead
  of tearing down the dashboard's live log view with
  `UnicodeDecodeError`.
- **Windows: stdout/stderr UnicodeEncodeError on box-drawing chars.**
  Python on Windows defaults `sys.stdout` to the active console
  code page (typically `cp1252`), which can't encode urika's
  `╭─╮` banner / spinner / TUI glyphs. `cli/_base._ensure_utf8_streams`
  now reconfigures both streams to UTF-8 with `errors="replace"`
  at import time (before Click parses anything), no-op on
  already-UTF-8 streams. Survives streams that lack
  `reconfigure()` (older Python, exotic test wrappers).
- **CLI smoke harness greps too aggressively.** The bare
  `Fatal error in message reader` string is no longer a FAIL
  trigger — the adapter already tolerates it cleanly. The harness
  now only flags the actionable `can_use_tool callback requires`
  streaming-mode regression marker or a Python traceback that
  references the adapter module.

### Docs (post-rc2)

- **20 → 32 user-facing docs** — split six over-long pages into
  focused sub-pages so reference material stays search-friendly
  and reading material stays linear. `12-built-in-tools.md` →
  `12a/12b`, `13-models-and-privacy.md` → `13a/13b`,
  `14-configuration.md` → `14a/14b`, `16-cli-reference.md` →
  `16a/16b/16c/16d/16e`, `18-dashboard.md` →
  `18a/18b/18c/18d`, `19-notifications.md` → `19a/19b`. Every
  cross-reference inside `docs/` and the top-level `README.md`
  was rewritten to point at the right sub-page; orphaned
  `contributing-an-adapter.md` was added to the index.
- **Audit pass** corrected the dashboard's actual default port
  (random free port, override with `--port`; `--auth-token`
  documented), the `task_agent`'s actual allowed bash list
  (`python` + `pip` + `pytest`), the dashboard settings tab counts
  (project: 6 with Secrets, global: 5 with Secrets), the project
  tree (added `memory/`, `.urika/sessions/`, etc.), and stripped
  every internal "(Phase 11/13)" annotation from
  `18a-dashboard-pages.md` that had been leaking into the public
  docs.
- **Windows install troubleshooting** — `01-getting-started.md`
  now covers the `WinError 32` urika.exe file-lock and the
  cp1252 console-encoding self-fix.

### Plans

- **`dev/plans/2026-05-02-prompt-bloat-and-context-budget.md`** —
  three-layer plan for v0.4.1 covering prompt-assembly trim,
  per-endpoint `context_window` declaration + output-token clamp,
  and summarisation fallback. Tracks the issue surfaced by the
  v0.4 E2E private-mode smoke (32K-context vLLM endpoint hit a
  94K-char advisor prompt + 32K-token output-cap request).

- **System claude CLI v2.1.124+ trailing exit-1 in streaming mode.**
  The system-installed `claude` CLI (which urika prefers for newer
  request schemas, e.g. `claude-opus-4-7`) exits 1 in streaming
  bidirectional mode *after* successfully streaming the final
  `ResultMessage`. Pre-fix, every multi-agent step in urika
  (advisor, build-tool, plan, run, evaluate, report, present,
  finalize) treated this as a hard failure even though the work
  completed cleanly. The adapter now detects "we already saw a
  clean ResultMessage" (`num_turns > 0` AND `not is_error`) and
  returns `success=True` with the captured state. Counter-cases —
  exit before any ResultMessage (credit-low, auth) and exit after
  `is_error=True` — still propagate as failures with the
  classified category. Also installs a `logging.Filter` on
  `claude_agent_sdk._internal.query` that drops the SDK's noisy
  `Fatal error in message reader: ...` log line when our adapter
  has already tolerated the error. Captures the bundled CLI's
  stderr for the first time so future post-stream errors actually
  reach urika logs (the SDK transport hardcoded a useless
  placeholder before).
- **Windows: SSE log streamers crashed on cp1252 bytes** (e.g.
  `0x97` em-dash) emitted by the bundled claude CLI's tool-use
  markers. All ten SSE endpoints (`run` / `evaluate` / `report` /
  `present` / `finalize` / `summarize` / `build-tool` / `advisor`
  / `_log` paths in `dashboard/routers/api.py`) now open log files
  with `errors="replace"` so a stray byte renders as `?` instead
  of tearing down the dashboard's live log view with
  `UnicodeDecodeError`.
- **Windows: stdout/stderr UnicodeEncodeError on box-drawing chars.**
  Python on Windows defaults `sys.stdout` to the active console
  code page (typically `cp1252`), which can't encode urika's
  `╭─╮` banner / spinner / TUI glyphs. `cli/_base._ensure_utf8_streams`
  now reconfigures both streams to UTF-8 with `errors="replace"`
  at import time (before Click parses anything), no-op on
  already-UTF-8 streams. Survives streams that lack
  `reconfigure()` (older Python, exotic test wrappers).
- **CLI smoke harness greps too aggressively.** The bare
  `Fatal error in message reader` string is no longer a FAIL
  trigger — the adapter already tolerates it cleanly. The harness
  now only flags the actionable `can_use_tool callback requires`
  streaming-mode regression marker or a Python traceback that
  references the adapter module.

## [0.4.0rc2] - 2026-04-30

Second v0.4 release candidate. Closes the remaining v0.4 tracks
(2, 5, and the rest of 4) on top of rc1.

### Added

- **Project memory Phase 1** (Track 2). New
  `<project>/memory/MEMORY.md`-indexed directory of structured
  markdown entries (user / feedback / instruction / decision /
  reference). `urika.core.project_memory` provides
  `load_project_memory(project_dir)` for system-prompt injection,
  `save_entry(...)` / `delete_entry(...)` for writes, and
  `parse_and_persist_memory_markers(project_dir, agent_text)` —
  strips `<memory type="...">...</memory>` markers from agent
  output and persists each as an entry. Per-project disable via
  `[memory] auto_capture = false` in `urika.toml`. Soft cap 5 KB
  (warns), hard cap 20 KB (truncates with marker). Phase 2-4
  (advisor/planner-emit prompts, curator agent, dashboard page,
  TUI slash command) defer to v0.5.
- **`urika memory list / show / add / delete`** CLI group as the
  manual surface over Phase 1.
- **Planner reads context summary + project memory** at
  `build_config` time. Pre-v0.4 only the advisor saw the rolling
  context summary; the planner had to rediscover prior decisions
  from `advisor-history.json` on its own.
- **`urika sessions list / export`** (Track 2 cheap win). Export
  an `OrchestratorSession` to Markdown (default — sharing) or JSON
  (full fidelity). Both stdout and `-o file`.
- **Experiment comparison view** (Track 4). New
  `GET /projects/<n>/compare?experiments=exp-001,exp-002` route
  renders a side-by-side metric table. Pre-v0.4 users had to open
  separate experiment-detail tabs and compare in their head —
  table-stakes for the experiment-tracking competitive set.
- **Cost-aware budget** (Track 4). `urika run --budget USD` flag
  pauses the experiment at the next turn boundary when accumulated
  cost crosses the budget; resumable. `urika run --dry-run` adds
  a cost estimate row using the project's prior session costs
  (last 7 non-zero, range + median × planned experiments).

### Fixed

- **TUI `_TuiWriter._post_line` prefers public `asyncio` API**
  over Textual's private `app._loop` / `app._thread_id` for the
  same-thread check. Fallback to private-attribute path is
  preserved for older Textual versions. Pre-v0.4 a Textual upgrade
  that renamed the private attrs would silently break thread-safe
  routing.
- **TUI `SystemExit` handler in `agent_worker.py` only exits the
  app for the explicit `/quit` command.** Pre-v0.4 every
  `SystemExit` (e.g. `urika config secret` wizards calling
  `raise SystemExit(0)` on user-cancel) silently quit the TUI
  behind the user's back.

## [0.4.0rc1] - 2026-04-30

First v0.4 release candidate. v0.4.0 is positioned as the **first
feature-complete Urika system, stable enough for extensive user
testing**. Strip GitHub integration out (deferred to v0.5) and Urika
is still a complete research-analysis platform.

This RC1 closes Tracks 1 (carry-overs from v0.3.2 deferrals),
3 (multi-provider thin abstraction), and most of 4 (user-facing
features: shell completion, dataset hash + drift detection).
Tracks 2 (project memory Phase 1), 5 (TUI polish), and the rest of
4 (experiment comparison view, cost-aware budget) follow in
subsequent RCs.

### Added

- **SecurityPolicy enforcement via SDK `can_use_tool` callback.**
  Pre-v0.4 the `writable_dirs` / `readable_dirs` /
  `allowed_bash_prefixes` / `blocked_bash_patterns` fields on
  every agent role were advisory only. v0.4 wires them into a real
  `can_use_tool` coroutine the SDK invokes before each tool
  dispatch. Bash commands shlex-parsed; shell metacharacters
  (`;`, `&&`, `||`, `|`, backticks, `$(`, `>`, `>>`, `<`, `&`,
  newline) rejected outright. Path operations canonicalised
  (collapse `..`, follow symlinks). Closes the orchestrator
  Bash bypass (`urika ; rm -rf /` was matching the prefix string).
- **Stop endpoints for non-run operations.** New `POST` routes:
  `/projects/<n>/advisor/stop`, `/finalize/stop`,
  `/summarize/stop`, `/build-tool/stop`, and
  `/runs/<exp>/present/stop`. All use the same SIGTERM-to-process-
  group pattern as `/runs/<exp>/stop`. Pre-v0.4 long-running
  advisor / finalize / build-tool / present invocations had no
  kill switch from the dashboard.
- **Multi-provider thin abstraction.** `AgentRunner` ABC gains
  `required_env` and `supported_tools` classmethods. New
  `urika.runners` entry-point group lets external packages
  register adapters (`OpenAIRunner`, `GoogleADKRunner`, etc.)
  without modifying core. New `list_backends()` enumerates every
  resolvable name. New `docs/contributing-an-adapter.md` walks
  contributors through the seam. End-to-end second adapter is
  deferred to v0.5.
- **Dataset hash + drift detection.** `urika new` records SHA-256
  of every data file under `[project.data_hashes]` in
  `urika.toml`. `urika status` re-hashes registered files and
  surfaces drift with a yellow warning. `--json` mode includes
  `data_drift`. Closes a long-standing reproducibility gap:
  pre-v0.4 there was no record at all, so editing a data file
  silently between experiments was undetectable.
- **`urika completion install / script / uninstall`.** Native
  bash / zsh / fish completion via Click 8's built-in generator.
  Auto-detects shell from `$SHELL`. Writes scripts to
  `~/.urika/completions/urika.<shell>`.
- **`OrchestratorSession` is now a real source of truth** in
  documented form (was already shipping in v0.3.2 but undocumented
  in CHANGELOG until this entry).

### Fixed

- **Cross-interface default consistency** — `audience` (`"standard"`
  everywhere — was 4 sites disagreeing on novice/standard/expert),
  `max_turns_per_experiment` (10 everywhere — was CLI=5, REPL=5,
  dashboard=10).
- **`KNOWN_AGENTS` (dashboard pages.py + api.py) adds
  `project_summarizer`** so the per-agent model-override grid
  renders all 12 agents instead of 11.
- **Email password input in CLI notifications wizard now masks**
  via `click.prompt(hide_input=True)`. Pre-v0.4 echoed plaintext
  while the dashboard's matching field always masked.
- **`VALID_SESSION_STATUSES` includes `pending` and `starting`.**
  Pre-v0.4 the set omitted these even though `experiment.json`
  and `progress.json` both used `pending` as the seed status.
- **Surface swallowed exceptions across orchestrator + cli +
  vault** — `loop_criteria.py` `pause_session` / `fail_session`,
  `loop.py` `resume_session` / `start_session`, `parsing.py`
  malformed JSON blocks (was a silent `continue` — most common
  reason `criteria_met` was missed), `cli/_base.py` `UrikaError`
  `__cause__` chain, `core/vault.py` `_read_env_file` and
  `_read_meta` failures.
- **`default_max_turns` upper bound** (200) in dashboard form
  validation. Pre-v0.4 the field accepted any positive int, so
  a paste of 999999 let every experiment run effectively forever.
- **`_toml_value` quotes inline-table keys** that aren't valid TOML
  bare keys (file paths contain `/` and `.`). Required for
  `[project.data_hashes]` to round-trip.

### Changed

- **`SecurityPolicy` docstring** updated to drop the "ADVISORY ONLY"
  warning (now actually enforced at runtime).
- **`task_agent.allowed_bash_prefixes`** gains `"pytest"` (was on
  `tool_builder` only). Required so ad-hoc pytest invocations from
  task_agent don't get denied under the new enforcement.
- **`OrchestratorChat._build_config` allowlist** updated from
  `["urika ", "CLAUDECODE= urika "]` to `["urika"]` — the
  pre-v0.4 string-prefix form was broken under shlex tokenisation
  AND was the bypass that made `urika ; rm -rf /` match.
- **`get_runner()` factory** now opens via entry points; raises
  with an actionable message + link to
  `docs/contributing-an-adapter.md` for unknown backends.

## [0.3.2] - 2026-04-30

Hardening release. v0.3.0/0.3.1 shipped four families of bugs that share one
root cause: contracts that hold in one path silently break in another (CLI
default ≠ dashboard default; advisor prompt assumes TTY but dashboard spawns
with `stdin=DEVNULL`; bundled `claude` CLI rejects newer model schema; Stop
button sends SIGTERM but CLI only handles SIGINT). v0.3.2 closes those four
families and pins them with regression tests.

### Fixed

- **Dashboard advisor chat no longer auto-fires multi-hour experiment runs from chat messages.** The CLI's "Run these experiments? [Yes]" prompt fell through to the default option on EOF when `dashboard.spawn_advisor` invoked `urika advisor` with `stdin=DEVNULL`, silently launching a 100+ minute experiment from what the user typed as a question. `_offer_to_run_advisor_suggestions` now skips the prompt entirely on non-TTY callers and prints a hint pointing at the dashboard's "New experiment" button. The Textual TUI's stdin bridge stays interactive so TUI users still see the prompt.
- **Stop button on a running experiment now actually stops the run AND flips the card to "stopped".** The dashboard sent SIGTERM but the CLI only handled SIGINT, so `stop_session` never wrote the terminal status — the card stayed on the seed `"pending"` value forever. Four-part fix: CLI's `_cleanup_on_interrupt` now handles SIGTERM symmetrically; `api_run_stop` writes `"stop"` to `<project>/.urika/pause_requested` first (graceful, lets the loop call `stop_session` at the next turn boundary) before escalating to `os.killpg(getpgid(pid), SIGTERM)` — process-group, not just the leader, so SDK-spawned `claude` and nested `urika` agents also exit; `runs._start_reaper` writes `progress.json["status"]="stopped"` (or `"failed"`) before unlinking the lock for non-zero exits as defense in depth; the SSE log stream now reads the actual terminal state from `progress.json` instead of always emitting `"completed"` regardless of how the run ended.
- **Sessions tab now captures dashboard advisor chats.** Pre-v0.3.2 only the TUI / REPL paths wrote orchestrator-session records; the dashboard's advisor chat (which spawns `urika advisor` via `runs.spawn_advisor`) silently never produced one — users reported running multiple advisor turns and seeing nothing in Sessions. CLI `urika advisor` now writes an `OrchestratorSession` record to `<project>/.urika/sessions/` after a successful exchange.
- **Stale `claude-opus-4-7` settings get migrated automatically on first launch.** v0.3.0/0.3.1 dashboard forms defaulted every agent in open mode to 4-7, but the bundled `claude` CLI inside `claude-agent-sdk 0.1.45` (v2.1.63) sends the deprecated `thinking.type.enabled` request shape that 4-7 rejects with HTTP 400, surfacing as "Fatal error in message reader: exit code 1". One-shot migration `migrate_settings()` (called from CLI startup and dashboard startup, idempotent via marker file at `~/.urika/.migrated_0.3.2`) detects 4-7 in any per-mode default or per-agent override slot, backs up `~/.urika/settings.toml` to `settings.toml.pre-0.3.2.bak`, and rewrites the broken positions to `claude-opus-4-6`. Users with the public `claude` CLI installed can re-pin 4-7 from the dashboard afterward — the runtime adapter prefers system `claude` on PATH (v2.1.100+ knows the current `thinking.type.adaptive` schema).
- **`urika new` now honors the global default model set in the dashboard.** `core/project_builder.py` was reading legacy flat `[runtime].model` while the dashboard form wrote `[runtime.modes.<mode>].model` — fresh projects from `urika new` silently ignored every default the user configured. `get_default_runtime(mode)` now prefers the per-mode key, falling back to flat for pre-0.3 layouts.
- **SDK adapter prefers system `claude` on PATH over the bundled binary.** `claude-agent-sdk 0.1.45` ships claude CLI v2.1.63 — too old to speak the request schema for newer models. The adapter now resolves `shutil.which("claude")` unconditionally and uses it when present; falls back to bundled when no system CLI is installed. Prevents the "Fatal error in message reader" symptom for users with a current `claude` CLI even if their `claude-opus-4-7` pin survived migration.
- **`compliance.scrub_oauth_env` extended to zero `CLAUDE_CODE_*` session markers.** Without this, agents launched from a Claude-Code-owned shell inherited `CLAUDECODE` etc. via the SDK's `{**os.environ, **options.env}` merge and the bundled CLI refused to launch nested. The orchestrator chat's inline scrub block (which previously only zeroed three of the four markers and missed both OAuth tokens) now delegates to the same helper; `dashboard/runs.py:_build_env` applies it as defense in depth so dashboard-spawned `urika run` children stay clean too.
- **Real subprocess stderr now surfaces from the SDK adapter.** Pre-v0.3.2 the adapter blindly forwarded `ProcessError.stderr` even when it was the SDK's hardcoded `"Check stderr output for details"` placeholder, masking the real cause (e.g. the API rejecting `thinking.type.enabled` with HTTP 400). Detect and discard the sentinel; preserve `type(exc).__name__`, exit code, and traceback via `logger.exception`.
- **Per-turn orchestrator crashes now leave a full traceback in `run.log`.** A `KeyError` parsing an evaluator block became "Experiment failed: 'criteria_met'" with no traceback anywhere; the broad per-turn catch now `logger.exception`s before returning so the SSE tailer carries the diagnostic.
- **Dashboard subprocess launch failures now appear in the run log.** `dashboard/runs.py:_spawn_detached` writes a `URIKA-LAUNCH-FAILED:` marker line into the log file the SSE tailer is watching when `Popen` itself raises (ENOEXEC, missing python, env too big), then re-raises so the route returns 500. Pre-v0.3.2 the FD was closed empty in `finally` and the route returned 200 + a phantom PID.
- **Reaper-thread crashes no longer leave orphan locks.** `_start_reaper`'s `proc.wait()` is now wrapped in try/except so a daemon-thread exception can't leave the lock forever (the "ghost run" failure mode you'd previously have to clear by hand).
- **Vault write failures during dashboard settings save now surface to the user.** Pre-v0.3.2 the privacy-endpoint and notifications form save handlers wrapped `vault.set_global` in `except Exception: pass` — the form returned a green "Saved" while secrets silently didn't write, so the next agent run mysteriously failed auth. Failures are now logged at error level AND collected into a per-request list shown in the response (HTML or JSON) so users see "Saved (with N secret-store warnings)".
- **Transient network errors and config errors now pause the experiment instead of failing it.** `_classify_error` adds `"transient"` (5xx / connection_reset / connection_refused / timeout / bad gateway) and `"config"` (MissingPrivateEndpointError / APIKeyRequiredError) categories, both added to `_PAUSABLE_ERRORS`. A network blip mid-loop or a misconfigured project pauses (resumable from the dashboard's Resume button) instead of killing a multi-hour autonomous run.
- **SDK adapter accumulates cost/tokens across multi-`ResultMessage` streams.** Pre-v0.3.2 these were set (not summed), so a subagent's usage was clobbered by the final ResultMessage's usage. Cache-token fields (`cache_creation_input_tokens`, `cache_read_input_tokens`) now also count.
- **Dashboard's `VALID_PRIVACY_MODES` list fixed.** Contained the defunct `"university"` mode and was missing `"hybrid"`; canonical set is now exactly `{open, private, hybrid}` and `pages.py` agrees with `api.py`.
- **Non-TTY guards extended to remaining destructive prompts.** `cli/run_planning.py:_determine_next_experiment` (twin of the advisor auto-fire bug), `cli/run.py` settings dialog and resume selector, `cli/agents_present.py`, `cli/agents_report.py`, `cli/agents.py` advisor and build-tool no-arg paths — all now skip the prompt or fall through to a safe default on non-TTY callers.

### Added

- **Cross-interface invariant tests** (`tests/test_cross_interface_defaults.py`). Pin five contracts that pre-v0.3.2 drift broke: CLI wizard's `_CLOUD_MODELS` and dashboard's `KNOWN_CLOUD_MODELS` agree; dashboard template's hardcoded fallback model is in `KNOWN_CLOUD_MODELS`; `VALID_PRIVACY_MODES` agrees with `_VALID_PRIVACY_MODES`; `get_default_runtime(mode)` round-trips what the dashboard form PUT writes; `python -m urika` is a valid module entry point. Future drift fails fast at CI time rather than mid-experiment.
- **Regression tests for stop / migration / classifier**: SIGTERM-exit terminal status writeback (3 tests), `_classify_error` coverage of all six categories (8 tests), `migrate_settings` rewrite + idempotence + no-op paths (4 tests), `get_default_runtime` per-mode preference (3 tests), upgraded stop endpoint signals process group + writes flag file (1 test).

### Changed

- **Dashboard model picker default lowered to `claude-opus-4-6`** in all six hardcoded sites (`pages.py:KNOWN_CLOUD_MODELS`, two `cloud_models` lists, `runtime_model_placeholder`, four `global_settings.html` fallback expressions). 4-7 stays selectable for users with the public `claude` CLI installed.
- **CLI `_CLOUD_MODELS` constant hoisted to module scope** in `cli/config.py` so the cross-interface invariant test can import it. 4-7 added as a selectable option with a "requires public claude CLI on PATH" description so it's offered alongside 4-6 / sonnet-4-5 / haiku-4-5.
- **Install docs reordered for beginners** (`docs/01-getting-started.md` and README): `Step 1 Prerequisites → Step 2 Install Urika → Step 3 API key → Step 4 Verify → Troubleshooting`. Python is now an explicit Step 1 with per-OS install commands; Claude CLI is documented as **recommended, not required** (the SDK ships its own bundled binary that handles 4-6/sonnet/haiku; users only need to install Node + `claude` if they want 4-7 or future Anthropic models). PEP 668 `externally-managed-environment` callout lives in Step 2 (the install step itself), not buried elsewhere. Troubleshooting table covers PEP 668, the "Fatal error in message reader" symptom, missing PATH, npm EACCES, missing API key, missing `urika` binary.

### Known limitations (deferred to 0.4)

- **`SecurityPolicy` is advisory only.** The `writable_dirs` / `readable_dirs` / `allowed_bash_prefixes` / `blocked_bash_patterns` fields on every agent role are documented as enforced sandboxing but currently aren't consumed at runtime — the only real sandbox is `allowed_tools` + `cwd`. The orchestrator chat's "block raw data reads via `cat */data/`" rules are paper. Real fix requires wiring these into the SDK's `PreToolUse` hook; landing in 0.4 alongside the multi-provider adapter scaffolding.
- **Orchestrator's Bash allow-list is bypassable.** `allowed_bash_prefixes=["urika ", ...]` is a string-prefix check that `urika ; rm -rf /` matches. Same fix path as above (SDK hook integration).

## [0.3.1] - 2026-04-29

Hotfix release driven by first-time Windows install feedback. Three issues that blocked fresh `pip install urika` users — primarily on Windows, but the fixes are platform-agnostic and improve the experience everywhere.

### Fixed

- **Dashboard `TypeError: unhashable type: 'dict'` on first page load.** Newer Starlette versions (≥0.40) removed the deprecated `TemplateResponse(name, context)` positional signature; the dict was being treated as Jinja `globals` and passed as a hash key, which fails. Migrated all 29 dashboard `TemplateResponse` call sites in `routers/pages.py` (26) and `routers/docs.py` (3) to the modern `TemplateResponse(request, name, context)` signature. Resolves the 269 v0.3-era deprecation warnings as a side benefit.
- **Vault backend selection respects test monkeypatching.** `urika.core.secrets._vault()` now only forces a `FileBackend` when `_SECRETS_PATH` has been monkeypatched away from the home-directory default (so existing test redirection still works). Otherwise it lets `SecretsVault` pick the best available global backend — OS keyring when `urika[keyring]` is installed and probes successfully, file fallback otherwise. Matches what `urika config secret` writes to.
- **Dashboard refreshes credentials on page render.** `/settings` (the global settings page) and `/api/settings/test-endpoint` now call `load_secrets()` before reading `ANTHROPIC_API_KEY` / private-endpoint env vars. Means a key added via `urika config api-key` or `urika config secret` (in another shell since the dashboard process started) becomes visible without restarting the dashboard.
- **Privacy preflight sends bearer token to auth-protected private endpoints.** `urika.core.privacy.check_private_endpoint` was building the GET `/v1/models` request with no `Authorization` header. An auth-protected vLLM / LiteLLM / OpenAI-compatible local endpoint behind an API key returned 401/403, `urlopen` raised `URLError`, and the gate reported "Local model unreachable" — even though the endpoint was running and the agent runtime had the right key. Fix: when `api_key_env` names a set env var, the preflight sends `Authorization: Bearer <token>` (loaded via the same `load_secrets()` refresh as above). Unauthenticated endpoints (default Ollama) unaffected — no header sent when `api_key_env` is blank or the var is unset.

### Added

- **`urika config secret`** — interactive CLI command for storing arbitrary named credentials in the global vault (private vLLM keys, HuggingFace tokens, third-party API credentials). Mirrors `urika config api-key` but works for any name. Includes a foot-gun guard that catches users pasting a value (e.g. `sk-...`) into the name prompt and asks them to confirm. Same vault backs the credential indirection (`bot_token_env`, `api_key_env`, `password_env`) used elsewhere — the dashboard's Privacy and Notifications tabs continue to store names; this command stores values.
- **Update banner now suppressed when stdout isn't a TTY** — was corrupting JSON output for `urika ... --json` consumers and adding noise to CI / piped sessions. Display also no longer prints `vv0.3.1` when GitHub tags use a `v` prefix.

### Tests

- 2418 → 2421 (+3 regression tests for the privacy preflight bearer-token paths).


## [0.3.0] - 2026-04-29

The "three interfaces, one platform" release. Urika now treats CLI, TUI, and dashboard as equal first-class interfaces, ships a hardened notifications subsystem with end-to-end test-send, finishes orchestrator session memory with a dashboard surface, and (most importantly) aligns with Anthropic's Consumer Terms §3.7 by requiring `ANTHROPIC_API_KEY` for all usage and actively blocking the subscription OAuth path the April 2026 enforcement targeted.

### Compliance (must-read)

- **Urika now requires an `ANTHROPIC_API_KEY`** for any command that spawns an agent. Per Anthropic's [Consumer Terms §3.7](https://www.anthropic.com/legal/consumer-terms) and the April 2026 Agent SDK clarification, a Claude Pro / Max subscription cannot be used to authenticate the Claude Agent SDK that Urika depends on. The full rationale is in [`docs/20-security.md`](docs/20-security.md#provider-compliance).
- **Three-layer safety net** prevents accidental subscription use:
  1. CLI startup prints a yellow warning when `ANTHROPIC_API_KEY` is unset (silence with `URIKA_ACK_API_KEY_REQUIRED=1`).
  2. The Anthropic SDK adapter raises `APIKeyRequiredError` before spawning when no key is found and the agent is bound for `api.anthropic.com`. Private endpoints (`ANTHROPIC_BASE_URL`) and non-Claude models are exempt.
  3. The subprocess environment scrubs `CLAUDE_CODE_OAUTH_TOKEN` and `ANTHROPIC_AUTH_TOKEN` so the spawned `claude` cannot fall back to OAuth even if the user has those vars set. Source: `src/urika/core/compliance.py`.
- New `urika config api-key` interactive command saves the key into `~/.urika/secrets.env` (chmod 0600). `urika config api-key --test` fires a real round-trip request to Anthropic to verify the key works (≈ $0.0001 per test).
- Dashboard Settings page surfaces a banner when no key is set and a positive "API key configured" indicator with a Test button when set.

### Added

**Three interfaces, one platform**

- New `docs/02-interfaces-overview.md` chapter introduces CLI / TUI / dashboard as equal-first-class interfaces with a task-by-task cheat-sheet table covering create-project, run, pause/stop, resume, results, advisor, sessions, finalize, knowledge, notifications, etc.
- Documentation reorder for v0.3 — Dashboard chapter jumps from #19 to #18 (sandwiched with TUI and CLI Reference instead of buried at the end). Knowledge Pipeline pulled forward to #10. Five user-facing how-to docs gain "From the dashboard" subsections to close three-mode coverage gaps.
- README replaces "Two ways to use Urika" framing with three-interface positioning + a short comparison table.

**Notifications: dashboard parity**

- New `POST /api/settings/notifications/test-send` endpoint with a **Send test notification** button on the dashboard's Notifications tab. Tests un-saved form data so users can validate credentials before clicking Save. Per-channel results render inline with the SDK's actual error string (e.g. Slack `invalid_auth`, Gmail `530 Authentication Required`).
- Slack settings tab now exposes previously-missing inbound config fields (App token env var, Allowed channels, Allowed users) so Socket Mode commands can be enabled without hand-editing TOML.

**Orchestrator session memory: dashboard surface**

- New `/projects/<n>/sessions` page with the Sessions sidebar tab (between Advisor and Knowledge). Lists up to 20 most-recent orchestrator chat sessions per project with preview text, turn count, last-updated timestamp, **Resume** button, and **Delete** button (HTMX swap).
- New `DELETE /api/projects/<n>/sessions/<id>` endpoint trashes a session.
- `GET /projects/<n>/advisor?session_id=<id>` pre-loads a prior orchestrator session's messages above the advisor transcript as read-only context.
- Auto-prune at save: `save_session` now caps each project at the most recent 20 sessions.
- REPL project-switch hint now shows session preview + relative time ("Previous session from 2 hours ago: \"Why are tree counts so skewed…\"").

**CLI commands now documented + new ones**

- `urika config api-key` (new — interactive setup) and `urika config api-key --test` (new — verify the key works end-to-end).
- `urika notifications`, `urika summarize`, `urika tui`, `urika experiment delete`, `urika dashboard --auth-token`, `urika run --dry-run`, `urika run --review-criteria` — all shipped earlier but were missing from the CLI reference; now documented in `docs/16-cli-reference.md`.

**TUI slash commands now documented**

- `/pause`, `/stop`, `/copy [N]`, `/notifications`, `/delete-experiment` — shipped earlier but were missing from the slash-command tables in `docs/17-interactive-tui.md`.

**Documentation**

- `docs/14-configuration.md` now covers `~/.urika/settings.toml` (annotated schema) and `~/.urika/secrets.env` (format + the env-var-name indirection pattern that channels use).
- `docs/17-notifications.md` adds Troubleshooting and Caveats sections — per-channel error tables (Email / Slack / Telegram) with symptom → cause → fix, plus caveats covering email batching, health-check filtering, inline-keyboard scope, and the "channel-message-not-Slack-slash-command" Slack convention.
- `docs/19-notifications.md` (was 17) clarifies that Slack inbound commands work via channel messages, NOT via Slack-side Slash Commands API registration.
- `docs/03-core-concepts.md` and `docs/12-built-in-tools.md` reframe the 24 built-in tools as a "seed library" — not a fixed catalogue. Documents the **tool builder** agent's role in creating project-specific tools on demand, both automatically (via planner `needs_tool: true` flag) and explicitly (via `urika build-tool`, `/build-tool`, dashboard Build tool modal).

### Changed

**Notifications: vocabulary unification (foundation for everything else above)**

- Canonical event-type vocabulary in `notifications/events.py` (`EVENT_METADATA` keyed by frozen `EventMetadata` dataclass with emoji, priority, label). All channels read from this single source of truth instead of maintaining their own per-event maps.
- Previously-dropped events (`experiment_paused`, `experiment_stopped`, `meta_paused`, `meta_completed` on Slack) now render with their proper emoji and route through the right priority builder. The default ℹ fallback is no longer hit for any canonical event.
- Bus mapper (`_map_progress_event`) now translates orchestrator phase strings for `experiment_completed/failed/paused/stopped`. The orchestrator emits canonical phase events at every termination point so non-CLI surfaces (TUI direct-orchestrator-call, future programmatic callers) get notifications without going through the CLI direct-`notify()` path.
- Per-channel `health_check()` probes auth/config (Slack `auth_test`, Telegram `Bot.get_me`, Email SMTP `NOOP`). Failing channels are excluded from dispatch at `bus.start()` with a clear WARNING log instead of dying silently mid-run.
- Shared formatter helpers in `notifications/formatting.py` (`format_event_emoji`, `format_event_label`, `format_event_summary_line`) eliminate duplication across channels.

**Dashboard usage page is now provider-aware**

- Cost figures throughout are explicitly labelled as estimates ("Est. cost", "Tokens (est.)") with a top-of-page disclaimer pointing users to their model provider's console for authoritative billing. The disclaimer is provider-agnostic — Anthropic, OpenAI, Google, and private endpoints all map cleanly when the multi-provider runtime lands.

### Fixed

**Dashboard notification settings: 4 silent persistence bugs**

The dashboard SAVE handler and template GETs were using non-canonical key names that the channel constructors don't read. A user-saved notification config silently didn't activate at runtime. The dashboard's test-send code path masked the bugs by mapping correctly when constructing test-send channels. Fixed:
- Email password env: `smtp_password_env` → `password_env` (channel reads `password_env`).
- Email SMTP user: `smtp_user` → `username` (channel reads `username`).
- Email SMTP host: `smtp_host` → `smtp_server` (channel reads `smtp_server`). Templates have a legacy fallback so existing TOML files keep populating the form.
- Slack bot token env: `token_env` → `bot_token_env` (channel reads `bot_token_env`).
- Project email override: writes `to` (loader merges into channel's `to`) instead of `extra_to` (silently ignored).
- Project telegram override: writes `chat_id` instead of `override_chat_id` (silently ignored).

A new round-trip test (`PUT /api/settings → build channel from TOML → assert credential is reachable`) guards against regression.

**Notifications: silent failures and event-loop bugs**

- `EmailChannel._send_email` no longer swallows SMTP exceptions — failures now propagate so test-send and the bus dispatcher can surface them. Previously a misconfigured Gmail relay reported "✓ sent" with no email actually delivered.
- `TelegramChannel.health_check` and `send` now run their asyncio work in a fresh OS thread so calling them from inside a running event loop (FastAPI handler) no longer raises "Cannot run the event loop while another loop is running".
- Telegram routing now reads canonical metadata priority for routing decisions, not just emoji — fixes asymmetric formatting between Slack and Telegram for the same canonical event.

**Compliance, secrets, and dashboard auth surfacing**

- Dashboard `test-send` endpoint refreshes `~/.urika/secrets.env` before constructing channels, so credentials added by `urika notifications` (in another shell) are visible without restarting the long-lived dashboard process.
- Sessions list empty-state copy fixed — sessions are saved by terminal orchestrator chat, not by the advisor.
- `docs/19-dashboard.md` advisor file path corrected (`advisor-history.json`, not `advisor.json`); broken `07-advisor.md` link fixed; two contradictory sidebar-order claims reconciled to match `_sidebar.html`.
- `docs/16-interactive-tui.md` Session Memory section: removed false `urika --resume` claim (no such flag — use `/resume-session` inside the TUI). `/new-session` flipped from "(planned)" to documented.
- `docs/20-security.md` task-agent code path corrected (`experiments/<id>/methods/`, not `code/`).

**Misc**

- Dashboard sessions list page: Resume button now uses `btn--primary` (blue), Delete uses `btn--danger` (red); rows vertically centred with breathing room. Was crammped at the right edge with no colour.
- TUI `/resume-session` no longer suggests a project name on tab completion — it takes a session number, not a project.
- Email channel: SMTP user field gains placeholder + help text ("usually the same as From address") so first-time setup is less ambiguous; save handler drops empty values so the channel's own fallback (`username = config.get(..., self._from)`) kicks in.
- Email password env field gains inline note pointing to https://myaccount.google.com/apppasswords for Gmail App Password setup.

### Documentation: stale claims fixed

- Tool count: 18 → 24 across `README.md`, `docs/README.md`, `docs/03-core-concepts.md`, `docs/12-built-in-tools.md`. Six new tool entries added with full property tables (`cluster_analysis`, `linear_mixed_model`, `pca`, `polynomial_regression`, `regularized_regression`, `time_series_decomposition`). Tool categories grew from 5 to 7 (added Dimensionality Reduction + Time Series).
- Agent count: 11 → 12 across `docs/03-core-concepts.md`, `docs/11-agent-system.md`, `README.md`, `CLAUDE.md`. The previously-undocumented **Project Summarizer** agent is now in `docs/11-agent-system.md` with its full property table.
- Audience defaults: docs now correctly describe three modes (`novice`, `standard`, `expert`) with `standard` as the default. Was claiming two modes with `expert` as default in `docs/14-configuration.md` and `docs/16-cli-reference.md`.

### Tests

- 2288 → 2395 tests (+107). New coverage for canonical event metadata, channel emoji/priority routing, bus mapper run-status branches, send-test helper, dashboard test-send endpoint + Send-test button, Slack inbound-field round-trip, per-channel health checks, bus startup filtering, dashboard sessions list page, session delete endpoint, advisor `?session_id=` pre-load, auto-prune on save, project-switch hint with relative time, API-key compliance helpers (CLI warning, hard refusal, OAuth scrub), `urika config api-key` interactive flow, `urika config api-key --test` end-to-end check, dashboard notification round-trip regression, and dashboard compliance banner.


## [0.2.0] - 2026-04-25

A polish-and-foundations release. User-visible improvements to presentations and the TUI; a substantial internal refactor that splits six 1,100+ line files into focused modules; release-readiness work including security documentation and CI.

### Added

**Presentations**
- New `standard` audience mode (now the default) — verbose speaker notes, restrained on-slide bullets. Sits between `expert` (terse) and `novice` (full plain-English walkthrough).
- Speaker notes are now required on every slide and render into reveal.js's speaker-view (`<aside class="notes">`, press `S` in a deck). The slide is the headline; the notes carry the explanation.
- New `explainer` slide type — lead sentence + short paragraph body — for method-introduction slides.
- Visible "Figure missing: <path>" placeholder when an agent references a figure that doesn't exist (was previously a silent broken `<img>`).

**CLI**
- `urika run --dry-run` — preview the planned pipeline (agents, tools, writable directories, where task-agent code will be written) without invoking any agent.
- `urika config provider/model` subcommands and `--audience standard` choice everywhere `--audience` is accepted.

**TUI**
- `/copy [N]` slash command — copy the last N output-panel lines to the clipboard via `pyperclip`. Terminal-agnostic fallback for sessions where Shift+drag doesn't forward.
- Opt-in per-command timeout in the worker — `_COMMAND_TIMEOUTS` dict maps command name → seconds, prevents forever-hangs on handlers that block on non-stdin resources.

**Notifications**
- Slack channel now supports `allowed_channels` and `allowed_users` allowlists; unauthorized interactions are dropped with a WARNING log. Startup warns if neither list is set (the bot is unrestricted).

**Errors**
- New typed-error hierarchy in `urika.core.errors` — `UrikaError` base + `ConfigError`, `AgentError`, `ValidationError` subclasses with optional actionable hints. CLI top-level handler renders them as `Error: <msg>` + `hint: <hint>` and exits 2 without a traceback.

**Documentation**
- New `docs/18-security.md` — explains agent-generated code execution, permission boundaries, secrets, dashboard/notifications security posture.

**CI**
- GitHub Actions workflow tests Python 3.11 + 3.12 with ruff + pytest on every push/PR to `main` and `dev`.

### Changed

**Refactoring (behavior-preserving)** — six files over 1,100 lines split along natural seams; every public entry-point preserved via re-exports. No external API changes.
- `orchestrator/loop.py` 1,114 → 647 lines + `loop_criteria.py`, `loop_display.py`, `loop_finalize.py`
- `cli/agents.py` 1,186 → 564 lines + `agents_report.py`, `agents_finalize.py`, `agents_present.py`
- `cli/project.py` 1,198 → 112 lines + `project_new.py`, `project_inspect.py`
- `cli/run.py` 1,269 → 933 lines + `run_planning.py`, `run_advisor.py`
- `repl/commands.py` 1,274 → 826 lines + `commands_registry.py`, `commands_run.py`, `commands_session.py`
- `cli/config.py` 1,341 → 369 lines + `config_setup.py`, `config_notifications.py`
- `cli_display.py` 967 → 546 lines + `cli_display_panels.py`

**Defaults**
- Default audience for `report` / `present` / `finalize` agents is now `standard` (was `expert`).

**Dependencies**
- `textual` pinned to `>=8.0,<9.0` to protect against major-version breakage in `tui/capture.py`'s private-attribute use
- `claude-agent-sdk` pinned to `>=0.1,<1.0`
- New: `pyperclip>=1.8` (for `/copy`)

### Fixed

- 18 pre-existing lint errors across the tree (mostly unused imports from older refactors); CI now starts green.

### Removed

- The archived TypeScript TUI experiment at `dev/archive/typescript-tui/` (9,772 tracked lines). Preserved in git history at commit `e07e747c` if ever needed.

### Tests

- 1,389 → 1,472 tests (+83). New coverage for: audience modes, presentation speaker notes + explainer slide + missing-figure placeholder, `/copy` command, worker-command timeout, Slack allowlist, typed-error rendering, `_agent_run_start` helper, plus 16 tests filling gaps in `orchestrator/meta.py`, `core/labbook.py`, and `dashboard/renderer.py`.


## [0.1.0] - 2026-03-30

Initial pre-release.

### Added

- Multi-agent orchestration system with 11 specialized agent roles
- Experiment lifecycle: planning, task execution, evaluation, advisory loop
- Meta-orchestrator for autonomous multi-experiment campaigns
- Finalization sequence: standalone methods, findings, reports, presentations
- 18 built-in statistical and ML tools
- Knowledge pipeline with PDF, text, and URL extractors
- Interactive REPL with 25+ slash commands
- CLI with 20+ commands
- Notification system (Email, Slack, Telegram) with remote control
- Pause/stop/resume for experiments and multi-experiment runs
- Reveal.js presentation generation
- Project builder with data profiling and multi-format support
- Versioned criteria system with advisor-driven evolution
- Method registry tracking all approaches across experiments
- Auto-generated labbooks, reports, and README files
- Privacy-aware hybrid endpoint model (public/private)
- 1072 tests

