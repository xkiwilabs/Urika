"""Registry of well-known secret names and their descriptions.

The vault's :func:`list_with_origins` uses this to surface secrets that
are commonly useful but not yet configured. Agents and the dashboard
also use it to suggest names + descriptions when adding a new secret.

Adding an entry here does NOT make the secret required; it's purely a
discoverability hint. Tools that genuinely require a secret should
declare it in their docstring (Phase D).
"""

from __future__ import annotations


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
