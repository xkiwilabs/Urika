"""`urika setup` command — installation/health check.

Split out of cli/config.py as part of Phase 8 refactoring. Importing
this module registers the @cli.command decorator for ``setup``.
"""

from __future__ import annotations

import os

import click

from urika.cli._base import cli


@cli.command("setup")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def setup_command(json_output: bool) -> None:
    """Check installation and install optional packages."""
    from urika.cli_display import (
        print_error,
        print_step,
        print_success,
        print_warning,
    )

    if json_output:
        # Collect package status and hardware info as JSON
        _all_packages = {
            "numpy": "numpy",
            "pandas": "pandas",
            "scipy": "scipy",
            "scikit-learn": "sklearn",
            "statsmodels": "statsmodels",
            "pingouin": "pingouin",
            "click": "click",
            "claude-agent-sdk": "claude_agent_sdk",
            "matplotlib": "matplotlib",
            "seaborn": "seaborn",
            "xgboost": "xgboost",
            "lightgbm": "lightgbm",
            "optuna": "optuna",
            "shap": "shap",
            "imbalanced-learn": "imblearn",
            "pypdf": "pypdf",
            "torch": "torch",
            "transformers": "transformers",
            "torchvision": "torchvision",
            "torchaudio": "torchaudio",
        }
        pkg_status = {}
        for name, imp in _all_packages.items():
            try:
                __import__(imp)
                pkg_status[name] = True
            except Exception:
                pkg_status[name] = False

        hw_data: dict = {}
        try:
            from urika.core.hardware import detect_hardware as _dh

            hw_data = dict(_dh())
        except Exception:
            pass

        from urika.cli_helpers import output_json

        output_json(
            {
                "packages": pkg_status,
                "hardware": hw_data,
                "anthropic_api_key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
            }
        )
        return

    click.echo()
    click.echo("  Urika Setup")
    click.echo("  " + "─" * 40)
    click.echo()

    # Check core packages
    core_packages = {
        "numpy": "numpy",
        "pandas": "pandas",
        "scipy": "scipy",
        "scikit-learn": "sklearn",
        "statsmodels": "statsmodels",
        "pingouin": "pingouin",
        "click": "click",
        "claude-agent-sdk": "claude_agent_sdk",
    }
    print_step("Core packages:")
    all_core = True
    for name, imp in core_packages.items():
        try:
            __import__(imp)
            print_success(f"  {name}")
        except ImportError:
            print_error(f"  {name} — NOT INSTALLED")
            all_core = False
    if not all_core:
        print_warning("Some core packages missing. Run: pip install -e .")
        click.echo()

    # Check viz
    print_step("Visualization:")
    for name, imp in [
        ("matplotlib", "matplotlib"),
        ("seaborn", "seaborn"),
    ]:
        try:
            __import__(imp)
            print_success(f"  {name}")
        except ImportError:
            print_error(f"  {name} — NOT INSTALLED")

    # Check ML
    print_step("Machine Learning:")
    for name, imp in [
        ("xgboost", "xgboost"),
        ("lightgbm", "lightgbm"),
        ("optuna", "optuna"),
        ("shap", "shap"),
        ("imbalanced-learn", "imblearn"),
    ]:
        try:
            __import__(imp)
            print_success(f"  {name}")
        except ImportError:
            print_error(f"  {name} — NOT INSTALLED")

    # Check knowledge
    print_step("Knowledge pipeline:")
    try:
        __import__("pypdf")
        print_success("  pypdf")
    except ImportError:
        print_error("  pypdf — NOT INSTALLED")

    # Check DL
    print_step("Deep Learning:")
    dl_installed = True
    for name, imp in [
        ("torch", "torch"),
        ("transformers", "transformers"),
        ("torchvision", "torchvision"),
        ("torchaudio", "torchaudio"),
    ]:
        try:
            __import__(imp)
            print_success(f"  {name}")
        except ImportError:
            print_error(f"  {name} — not installed")
            dl_installed = False
        except Exception as exc:
            # RuntimeError from CUDA version mismatches, etc.
            short = str(exc).split(".")[0]
            print_error(f"  {name} — {short}")
            dl_installed = False

    # Check hardware
    click.echo()
    print_step("Hardware:")
    try:
        from urika.core.hardware import detect_hardware

        hw = detect_hardware()
        cpu = hw["cpu_count"]
        ram = hw["ram_gb"]
        print_success(f"  CPU: {cpu} cores")
        if ram:
            print_success(f"  RAM: {ram} GB")
        if hw["gpu"]:
            gpu = hw["gpu_name"]
            vram = hw.get("gpu_vram", "")
            label = f"  GPU: {gpu}"
            if vram:
                label += f" ({vram})"
            print_success(label)
        else:
            print_step("  GPU: none detected")
    except Exception:
        print_step("  Could not detect hardware")

    # Offer DL install
    if not dl_installed:
        click.echo()
        click.echo("  " + "─" * 40)
        click.echo()
        print_step("Deep learning packages are not installed.")
        print_step(
            "These are large (~2 GB) and only needed for neural network experiments."
        )
        click.echo()
        choice = click.prompt(
            "  Install deep learning packages?",
            type=click.Choice(
                ["yes", "no", "gpu", "cpu"],
                case_sensitive=False,
            ),
            default="no",
        )
        if choice == "no":
            click.echo("  Skipped.")
        else:
            import subprocess
            import sys

            def _torch_install_args(*, want_gpu: bool = True) -> tuple[list[str], str]:
                """Build pip install args for PyTorch based on platform.

                Returns (args_list, description_string).

                - macOS: default PyPI (includes MPS for Apple Silicon)
                - ARM (any OS without NVIDIA): default PyPI
                - x86 + NVIDIA: detect CUDA version, use matching wheel
                - No GPU / want_gpu=False: CPU-only wheels (x86) or default (ARM)
                """
                import platform

                # Use --force-reinstall if torchaudio has a CUDA mismatch
                force = False
                try:
                    r = subprocess.run(
                        [sys.executable, "-c", "import torchaudio"],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if r.returncode != 0 and "CUDA version" in r.stderr:
                        force = True
                except Exception:
                    pass

                base = [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    *(["--force-reinstall"] if force else []),
                    "torch",
                    "torchvision",
                    "torchaudio",
                ]
                arch = platform.machine().lower()
                is_arm = arch in ("arm64", "aarch64", "armv8l")

                # macOS — default PyPI includes MPS for Apple Silicon
                if sys.platform == "darwin":
                    desc = "MPS" if is_arm else "CPU"
                    return base, desc

                # ARM Linux/Windows — no CUDA index, default PyPI
                if is_arm:
                    cuda_tag = _detect_cuda_tag() if want_gpu else None
                    if cuda_tag:
                        # ARM + NVIDIA (Jetson) — use default pip, torch auto-detects
                        return base, f"ARM + CUDA ({cuda_tag})"
                    return base, "ARM CPU"

                # x86 Linux/Windows
                if want_gpu:
                    cuda_tag = _detect_cuda_tag()
                    if cuda_tag:
                        return (
                            base
                            + [
                                "--index-url",
                                f"https://download.pytorch.org/whl/{cuda_tag}",
                            ],
                            f"CUDA {cuda_tag}",
                        )
                return (
                    base + ["--index-url", "https://download.pytorch.org/whl/cpu"],
                    "CPU",
                )

            def _detect_cuda_tag() -> str | None:
                """Detect CUDA version, return wheel tag (e.g. 'cu124') or None."""
                # 1. Check existing torch installation
                try:
                    import torch

                    cv = torch.version.cuda
                    if cv:
                        parts = cv.split(".")
                        return f"cu{parts[0]}{parts[1]}"
                except Exception:
                    pass
                # 2. Check nvcc
                try:
                    import re

                    r = subprocess.run(
                        ["nvcc", "--version"],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    if r.returncode == 0:
                        m = re.search(r"release (\d+)\.(\d+)", r.stdout)
                        if m:
                            return f"cu{m.group(1)}{m.group(2)}"
                except Exception:
                    pass
                # 3. Check nvidia-smi exists (GPU present but no toolkit)
                try:
                    r = subprocess.run(
                        ["nvidia-smi"],
                        capture_output=True,
                        timeout=5,
                    )
                    if r.returncode == 0:
                        return "cu124"  # Default to latest stable
                except Exception:
                    pass
                return None

            if choice == "gpu":
                args, desc = _torch_install_args(want_gpu=True)
                print_step(f"Installing PyTorch ({desc})…")
                subprocess.run(args, check=False)
                # Then the rest
                print_step("Installing transformers…")
                subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "pip",
                        "install",
                        "transformers>=4.30",
                        "sentence-transformers>=2.2",
                        "timm>=0.9",
                    ],
                    check=False,
                )
            elif choice == "cpu":
                args, desc = _torch_install_args(want_gpu=False)
                print_step(f"Installing PyTorch ({desc})…")
                subprocess.run(args, check=False)
                print_step("Installing transformers…")
                subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "pip",
                        "install",
                        "transformers>=4.30",
                        "sentence-transformers>=2.2",
                        "timm>=0.9",
                    ],
                    check=False,
                )
            else:
                # "yes" — auto-detect
                try:
                    from urika.core.hardware import (
                        detect_hardware,
                    )

                    hw_info = detect_hardware()
                    has_gpu = hw_info.get("gpu", False)
                except Exception:
                    has_gpu = False

                args, desc = _torch_install_args(want_gpu=has_gpu)
                print_step(f"Installing PyTorch ({desc})…")
                subprocess.run(args, check=False)
                print_step("Installing transformers…")
                subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "pip",
                        "install",
                        "transformers>=4.30",
                        "sentence-transformers>=2.2",
                        "timm>=0.9",
                    ],
                    check=False,
                )
            print_success("Deep learning packages installed.")
    else:
        # Check GPU availability with torch
        click.echo()
        try:
            import torch

            if torch.cuda.is_available():
                dev = torch.cuda.get_device_name(0)
                print_success(f"  PyTorch CUDA: {dev}")
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                print_success("  PyTorch MPS: available")
            else:
                print_step("  PyTorch: CPU only")
        except Exception:
            pass

    click.echo()
    print_step("Claude access:")
    if os.environ.get("ANTHROPIC_API_KEY"):
        print_success("  ANTHROPIC_API_KEY is set")
    else:
        print_warning(
            "  ANTHROPIC_API_KEY not set — needed unless using Claude Max/Pro"
        )

    click.echo()
    # Check for updates
    print_step("Updates:")
    try:
        from urika.core.updates import (
            check_for_updates,
            format_update_message,
        )

        update_info = check_for_updates(force=True)
        if update_info:
            msg = format_update_message(update_info)
            print_warning(f"  {msg}")
        else:
            print_success("  You are on the latest version")
    except Exception:
        print_step("  Could not check for updates")

    click.echo()
    print_success("Setup check complete.")
    click.echo()

