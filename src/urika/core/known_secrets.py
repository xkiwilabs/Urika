"""Registry of well-known secret names and their descriptions.

The dashboard's add-form autocompletes from :data:`KNOWN_SECRETS` so
users adding a new credential see a useful suggestion list. The Secrets
tab uses :data:`LLM_PROVIDERS` to render the "LLM Providers" section
and mark unsupported providers as locked (coming-soon affordance).

Adding an entry to ``KNOWN_SECRETS`` does NOT make the secret required
or pre-render a row — those rules live in the dashboard's
``GET /api/secrets`` handler. Tools that genuinely require a secret
should declare it in their docstring (Phase D).
"""

from __future__ import annotations

from dataclasses import dataclass


KNOWN_SECRETS: dict[str, str] = {
    "ANTHROPIC_API_KEY": "Claude API (Anthropic adapter — required by Urika v0.3+).",
    "OPENAI_API_KEY": "OpenAI API (planned multi-provider adapter).",
    "GOOGLE_API_KEY": "Google AI / Gemini API (planned multi-provider adapter).",
    "HUGGINGFACE_HUB_TOKEN": "HuggingFace gated models / datasets / embeddings.",
    "WANDB_API_KEY": "Weights & Biases experiment tracking.",
    "KAGGLE_USERNAME": "Kaggle dataset access (paired with KAGGLE_KEY).",
    "KAGGLE_KEY": "Kaggle dataset access (paired with KAGGLE_USERNAME).",
    "GITHUB_TOKEN": "GitHub access for private repos (literature agent / knowledge ingestion).",
    "URIKA_EMAIL_PASSWORD": "Email notification SMTP password.",
    "SLACK_BOT_TOKEN": "Slack outbound notification bot token.",
    "SLACK_APP_TOKEN": "Slack inbound (Socket Mode) app token.",
    "TELEGRAM_BOT_TOKEN": "Telegram notification bot token.",
}


@dataclass(frozen=True)
class ProviderInfo:
    """Metadata for an LLM provider Urika knows about.

    Attributes
    ----------
    name:
        Environment variable name the runtime reads at agent-startup.
    display:
        Human-readable label for the dashboard (e.g. "Claude
        (Anthropic)").
    description:
        Short blurb shown beneath the row.
    available:
        ``True`` if Urika supports authenticating against this provider
        in the current version. ``False`` rows render with a "coming
        soon" badge and the dashboard refuses to save values for them.
    """

    name: str
    display: str
    description: str
    available: bool


LLM_PROVIDERS: list[ProviderInfo] = [
    ProviderInfo(
        name="ANTHROPIC_API_KEY",
        display="Claude (Anthropic)",
        description="Required by Urika v0.3+. Used by all default agent roles.",
        available=True,
    ),
    ProviderInfo(
        name="OPENAI_API_KEY",
        display="OpenAI (GPT)",
        description=(
            "Multi-provider support — settable once that adapter ships in v0.5."
        ),
        available=False,
    ),
    ProviderInfo(
        name="GOOGLE_API_KEY",
        display="Google AI (Gemini)",
        description=(
            "Multi-provider support — settable once that adapter ships in v0.5."
        ),
        available=False,
    ),
]
