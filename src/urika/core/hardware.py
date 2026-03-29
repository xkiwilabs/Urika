"""Hardware detection for agent context."""

from __future__ import annotations

import os
import platform
import shutil


def detect_hardware() -> dict[str, object]:
    """Detect available hardware: GPU, RAM, CPU cores.

    Returns a dict with keys: gpu, gpu_name, gpu_vram, ram_gb, cpu_count, os_name.
    """
    info: dict[str, object] = {
        "gpu": False,
        "gpu_name": "",
        "gpu_vram": "",
        "ram_gb": 0,
        "cpu_count": os.cpu_count() or 1,
        "os_name": platform.system(),
    }

    # Detect GPU via nvidia-smi
    if shutil.which("nvidia-smi"):
        try:
            import subprocess

            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=name,memory.total",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                parts = result.stdout.strip().split(",")
                info["gpu"] = True
                info["gpu_name"] = parts[0].strip()
                if len(parts) > 1:
                    info["gpu_vram"] = f"{int(parts[1].strip())} MB"
        except Exception:
            pass

    # Detect Apple Silicon GPU (MPS)
    if not info["gpu"] and platform.system() == "Darwin":
        try:
            import subprocess

            result = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and "Apple" in result.stdout:
                info["gpu"] = True
                info["gpu_name"] = "Apple Silicon (MPS)"
        except Exception:
            pass

    # Detect RAM
    try:
        import subprocess

        if platform.system() == "Linux":
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        parts = line.split()
                        if len(parts) >= 2:
                            kb = int(parts[1])
                            info["ram_gb"] = round(kb / (1024 * 1024), 1)
                        break
        elif platform.system() == "Darwin":
            result = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                info["ram_gb"] = round(int(result.stdout.strip()) / (1024**3), 1)
    except Exception:
        pass

    return info


def hardware_summary() -> str:
    """Return a one-line hardware summary for agent prompts."""
    info = detect_hardware()
    parts = []

    cpu = info["cpu_count"]
    parts.append(f"{cpu} CPU cores")

    ram = info["ram_gb"]
    if ram:
        parts.append(f"{ram} GB RAM")

    if info["gpu"]:
        gpu_str = str(info["gpu_name"])
        if info["gpu_vram"]:
            gpu_str += f" ({info['gpu_vram']})"
        parts.append(gpu_str)
    else:
        parts.append("no GPU")

    parts.append(str(info["os_name"]))

    return "System: " + ", ".join(parts)


def pip_install_hint(package: str) -> str:
    """Return a pip install command with GPU-aware hints for known packages."""
    info = detect_hardware()
    has_gpu = info["gpu"]
    gpu_name = str(info.get("gpu_name", ""))
    is_apple = "Apple" in gpu_name or "MPS" in gpu_name

    if package in ("torch", "pytorch", "torchvision", "torchaudio"):
        if has_gpu and not is_apple:
            return f"pip install {package} --index-url https://download.pytorch.org/whl/cu121"
        elif is_apple:
            return f"pip install {package}  # MPS backend available on Apple Silicon"
        else:
            return f"pip install {package} --index-url https://download.pytorch.org/whl/cpu"

    if package in ("tensorflow", "tensorflow-gpu"):
        if has_gpu and not is_apple:
            return "pip install tensorflow[and-cuda]"
        else:
            return "pip install tensorflow"

    return f"pip install {package}"
