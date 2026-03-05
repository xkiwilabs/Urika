"""Urika CLI."""

import click


@click.group()
@click.version_option(package_name="urika")
def cli() -> None:
    """Urika: Agentic scientific analysis platform."""
