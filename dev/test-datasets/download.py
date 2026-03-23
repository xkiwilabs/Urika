#!/usr/bin/env python3
"""Download (or generate) test datasets for Urika integration testing.

Usage:
    python dev/test-datasets/download.py                # all datasets
    python dev/test-datasets/download.py --dataset stroop
    python dev/test-datasets/download.py --output-dir /tmp/test-data
"""

from __future__ import annotations

import argparse
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

import numpy as np
import pandas as pd


DATASETS = ["stroop", "depression", "marketing", "housing", "text-sentiment", "images", "eeg", "gene-expression", "climate", "energy-forecast"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _progress_hook(block_num: int, block_size: int, total_size: int) -> None:
    """Simple download progress indicator."""
    downloaded = block_num * block_size
    if total_size > 0:
        pct = min(100, downloaded * 100 // total_size)
        bar = "#" * (pct // 2) + "-" * (50 - pct // 2)
        print(f"\r  [{bar}] {pct}%", end="", flush=True)
    else:
        print(f"\r  {downloaded // 1024} KB downloaded", end="", flush=True)


def _download_file(url: str, dest: Path) -> None:
    """Download a file with progress display."""
    print(f"  Downloading {url}")
    try:
        urllib.request.urlretrieve(url, str(dest), reporthook=_progress_hook)
        print()  # newline after progress bar
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Download failed: {exc}") from exc


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Dataset generators / downloaders
# ---------------------------------------------------------------------------

def download_stroop(data_dir: Path) -> None:
    """Download the Lakens Stroop dataset from GitHub."""
    dest = data_dir / "stroop.csv"
    if dest.exists():
        print("  Already exists, skipping.")
        return
    _ensure_dir(data_dir)
    url = "https://raw.githubusercontent.com/Lakens/Stroop/master/stroop.csv"
    _download_file(url, dest)
    print(f"  Saved to {dest}")


def download_depression(data_dir: Path) -> None:
    """Generate a synthetic depression/mental-health survey dataset."""
    dest = data_dir / "depression_survey.csv"
    if dest.exists():
        print("  Already exists, skipping.")
        return
    _ensure_dir(data_dir)

    rng = np.random.default_rng(42)
    n = 500

    age = rng.integers(18, 75, size=n)
    gender = rng.choice(["male", "female", "non-binary"], size=n, p=[0.45, 0.48, 0.07])
    sleep_hours = np.clip(rng.normal(6.5, 1.8, n), 2, 12).round(1)
    exercise_weekly = rng.integers(0, 8, size=n)
    social_support = np.clip(rng.normal(5.5, 2.0, n), 1, 10).round(1)
    stress_level = np.clip(rng.normal(5.0, 2.5, n), 1, 10).round(1)
    income_bracket = rng.choice(
        ["<20k", "20k-40k", "40k-60k", "60k-80k", "80k-100k", ">100k"],
        size=n,
        p=[0.10, 0.20, 0.25, 0.20, 0.15, 0.10],
    )

    # BDI score influenced by sleep, exercise, social support, stress
    bdi_base = (
        30
        - sleep_hours * 1.5
        - exercise_weekly * 1.2
        - social_support * 0.8
        + stress_level * 2.0
        + rng.normal(0, 4, n)
    )
    bdi_score = np.clip(bdi_base, 0, 63).astype(int)

    # Depression severity categories based on BDI
    severity = pd.cut(
        bdi_score,
        bins=[-1, 9, 18, 28, 63],
        labels=["minimal", "mild", "moderate", "severe"],
    )

    df = pd.DataFrame({
        "participant_id": [f"P{i:04d}" for i in range(1, n + 1)],
        "age": age,
        "gender": gender,
        "bdi_score": bdi_score,
        "sleep_hours": sleep_hours,
        "exercise_weekly": exercise_weekly,
        "social_support_score": social_support,
        "stress_level": stress_level,
        "income_bracket": income_bracket,
        "depression_severity": severity,
    })

    df.to_csv(dest, index=False)
    print(f"  Generated {n} rows -> {dest}")


def download_marketing(data_dir: Path) -> None:
    """Generate a synthetic customer segmentation dataset."""
    dest = data_dir / "customer_segmentation.csv"
    if dest.exists():
        print("  Already exists, skipping.")
        return
    _ensure_dir(data_dir)

    rng = np.random.default_rng(123)
    n = 400

    age = rng.integers(18, 70, size=n)
    gender = rng.choice(["male", "female", "other"], size=n, p=[0.48, 0.49, 0.03])
    annual_income = np.clip(rng.lognormal(10.8, 0.6, n), 15000, 200000).astype(int)
    spending_score = np.clip(rng.normal(50, 25, n), 1, 100).astype(int)
    education = rng.choice(
        ["high_school", "bachelors", "masters", "phd", "other"],
        size=n,
        p=[0.25, 0.35, 0.22, 0.08, 0.10],
    )
    marital_status = rng.choice(
        ["single", "married", "divorced", "widowed"],
        size=n,
        p=[0.35, 0.40, 0.18, 0.07],
    )
    purchase_frequency = np.clip(rng.poisson(8, n), 0, 50)

    df = pd.DataFrame({
        "customer_id": [f"C{i:04d}" for i in range(1, n + 1)],
        "age": age,
        "gender": gender,
        "annual_income": annual_income,
        "spending_score": spending_score,
        "education": education,
        "marital_status": marital_status,
        "purchase_frequency": purchase_frequency,
    })

    df.to_csv(dest, index=False)
    print(f"  Generated {n} rows -> {dest}")


def download_housing(data_dir: Path) -> None:
    """Export the California Housing dataset from scikit-learn."""
    dest = data_dir / "california_housing.csv"
    if dest.exists():
        print("  Already exists, skipping.")
        return
    _ensure_dir(data_dir)

    try:
        from sklearn.datasets import fetch_california_housing
    except ImportError:
        raise RuntimeError(
            "scikit-learn is required for the housing dataset. "
            "Install it with: pip install scikit-learn"
        )

    data = fetch_california_housing(as_frame=True)
    data.frame.to_csv(dest, index=False)
    print(f"  Exported {len(data.frame)} rows -> {dest}")


def download_text_sentiment(data_dir: Path) -> None:
    """Generate a synthetic sentiment analysis dataset with realistic reviews."""
    dest = data_dir / "sentiment_reviews.csv"
    if dest.exists():
        print("  Already exists, skipping.")
        return
    _ensure_dir(data_dir)

    rng = np.random.default_rng(999)

    positive_templates = [
        "Absolutely loved this product! {adj} quality and {adj2} customer service.",
        "Best purchase I've made in years. The {noun} works {adv} well.",
        "Five stars! {adj} design, {adj2} functionality, and fast shipping.",
        "Exceeded my expectations. The {noun} is {adj} and {adj2}.",
        "Highly recommend! {adj} value for money, {adv} impressed.",
        "Perfect for what I needed. {adj} build quality and {adj2} performance.",
        "Outstanding {noun}! {adj} and reliable, couldn't be happier.",
        "Love it! {adj} experience from start to finish. Will buy again.",
        "Great {noun} at a fair price. {adj} and {adj2} in every way.",
        "Top-notch product. The {noun} is {adv} {adj} and well-made.",
        "This {noun} changed my routine. {adj} results after just a week.",
        "Pleasantly surprised by how {adj} this is. {adj2} packaging too.",
        "Solid purchase, {adv} {adj}. The {noun} does exactly what it promises.",
        "Wonderful quality. The {noun} feels {adj} and works {adv} well.",
        "Can't say enough good things. {adj} product, {adj2} delivery.",
    ]

    negative_templates = [
        "Very disappointed. The {noun} broke after {time}. {adj} quality.",
        "Would not recommend. {adj} customer service and {adj2} product.",
        "Terrible experience. The {noun} is {adv} {adj} and overpriced.",
        "Waste of money. The {noun} stopped working after {time}.",
        "One star. {adj} build quality, {adj2} design, total letdown.",
        "Returned immediately. The {noun} was {adj} and {adj2} out of the box.",
        "Awful. The {noun} is {adv} {adj} compared to competitors.",
        "Do not buy this. {adj} quality and {adj2} instructions.",
        "Regret this purchase. The {noun} feels {adj} and {adv} cheap.",
        "Horrible {noun}. {adj} experience, will never buy from this brand again.",
        "Broken on arrival. The {noun} was {adj} and {adj2} packaged.",
        "Save your money. {adj} performance and {adj2} durability.",
        "Not as described. The {noun} is {adv} {adj} and misleading.",
        "Frustrating experience. {adj} support and the {noun} is {adj2}.",
        "Complete junk. The {noun} lasted {time} before failing. {adj}.",
    ]

    pos_adj = ["excellent", "fantastic", "superb", "wonderful", "amazing", "great", "impressive", "stellar"]
    pos_adj2 = ["reliable", "sleek", "intuitive", "responsive", "sturdy", "elegant", "efficient", "delightful"]
    pos_adv = ["incredibly", "remarkably", "truly", "genuinely", "exceptionally"]

    neg_adj = ["poor", "terrible", "awful", "dreadful", "horrible", "flimsy", "disappointing", "mediocre"]
    neg_adj2 = ["unreliable", "clunky", "confusing", "fragile", "cheap", "defective", "shoddy", "useless"]
    neg_adv = ["incredibly", "absurdly", "shockingly", "unbelievably", "ridiculously"]

    nouns = ["product", "item", "device", "unit", "gadget", "tool", "appliance", "accessory"]
    times = ["one day", "two days", "a week", "two weeks", "a month", "three uses"]

    rows = []
    for i in range(200):
        if i < 100:
            template = rng.choice(positive_templates)
            text = template.format(
                adj=rng.choice(pos_adj),
                adj2=rng.choice(pos_adj2),
                adv=rng.choice(pos_adv),
                noun=rng.choice(nouns),
                time=rng.choice(times),
            )
            sentiment = "positive"
        else:
            template = rng.choice(negative_templates)
            text = template.format(
                adj=rng.choice(neg_adj),
                adj2=rng.choice(neg_adj2),
                adv=rng.choice(neg_adv),
                noun=rng.choice(nouns),
                time=rng.choice(times),
            )
            sentiment = "negative"
        rows.append({"text": text, "sentiment": sentiment})

    df = pd.DataFrame(rows)
    # Shuffle so positive/negative are interleaved
    df = df.sample(frac=1, random_state=42).reset_index(drop=True)
    df.to_csv(dest, index=False)
    print(f"  Generated {len(df)} rows -> {dest}")


def download_images(data_dir: Path) -> None:
    """Generate a tiny synthetic image classification dataset."""
    if (data_dir / "cats").exists() and (data_dir / "dogs").exists() and (data_dir / "birds").exists():
        print("  Already exists, skipping.")
        return
    _ensure_dir(data_dir)

    try:
        from PIL import Image
    except ImportError:
        raise RuntimeError(
            "Pillow is required for the images dataset. "
            "Install it with: pip install Pillow"
        )

    rng = np.random.default_rng(7)

    # Color tints per class (R, G, B multipliers)
    class_tints = {
        "cats": (1.0, 0.7, 0.3),   # warm orange tint
        "dogs": (0.5, 0.3, 1.0),   # blue-purple tint
        "birds": (0.3, 1.0, 0.4),  # green tint
    }

    counts = {"cats": 17, "dogs": 17, "birds": 16}  # total 50

    for class_name, n_images in counts.items():
        class_dir = data_dir / class_name
        class_dir.mkdir(parents=True, exist_ok=True)
        tint = class_tints[class_name]

        for i in range(n_images):
            # Create random base pattern
            base = rng.integers(50, 200, size=(64, 64, 3), dtype=np.uint8)

            # Apply class-specific color tint
            tinted = np.zeros_like(base, dtype=np.float64)
            tinted[:, :, 0] = base[:, :, 0] * tint[0]
            tinted[:, :, 1] = base[:, :, 1] * tint[1]
            tinted[:, :, 2] = base[:, :, 2] * tint[2]

            # Add some geometric shapes for texture variety
            cx, cy = rng.integers(10, 54, size=2)
            radius = rng.integers(5, 20)
            y_grid, x_grid = np.ogrid[:64, :64]
            mask = (x_grid - cx) ** 2 + (y_grid - cy) ** 2 < radius ** 2
            tinted[mask] = np.clip(tinted[mask] * 1.5, 0, 255)

            img_array = np.clip(tinted, 0, 255).astype(np.uint8)
            img = Image.fromarray(img_array, mode="RGB")
            img.save(class_dir / f"{class_name}_{i:03d}.png")

        print(f"  Generated {n_images} images in {class_dir}")

    print(f"  Total: 50 images (64x64) in 3 classes -> {data_dir}")


def download_eeg(data_dir: Path) -> None:
    """Generate a synthetic EEG motor imagery dataset."""
    dest = data_dir / "eeg_motor_imagery.csv"
    if dest.exists():
        print("  Already exists, skipping.")
        return
    _ensure_dir(data_dir)

    rng = np.random.default_rng(314)

    participants = [f"P{i:02d}" for i in range(1, 11)]
    channels = ["Fz", "Cz", "Pz", "C3", "C4", "O1", "O2"]
    conditions = ["left_hand", "right_hand", "rest"]
    n_trials = 20
    epoch_steps = list(range(0, 1000, 4))  # 250 Hz -> 250 samples per epoch

    rows = []
    for pid in participants:
        participant_offset = rng.normal(0, 5)  # inter-participant variability
        for trial in range(1, n_trials + 1):
            condition = rng.choice(conditions)
            for ch in channels:
                for t in epoch_steps:
                    # Base EEG: mix of alpha (~10 Hz) and noise
                    time_s = t / 1000.0
                    alpha = 8.0 * np.sin(2 * np.pi * 10 * time_s)
                    beta = 3.0 * np.sin(2 * np.pi * 20 * time_s)
                    noise = rng.normal(0, 12)

                    amp = alpha + beta + noise + participant_offset

                    # Embed lateralised mu-rhythm desynchronisation
                    if condition == "left_hand" and ch == "C4":
                        # Left hand imagery -> right motor cortex (C4) desync
                        amp -= 4.0 * np.sin(2 * np.pi * 11 * time_s)
                        amp += rng.normal(0, 1.5)
                    elif condition == "left_hand" and ch == "C3":
                        # Ipsilateral side: slight increase
                        amp += 1.5 * np.sin(2 * np.pi * 11 * time_s)
                    elif condition == "right_hand" and ch == "C3":
                        # Right hand imagery -> left motor cortex (C3) desync
                        amp -= 4.0 * np.sin(2 * np.pi * 11 * time_s)
                        amp += rng.normal(0, 1.5)
                    elif condition == "right_hand" and ch == "C4":
                        amp += 1.5 * np.sin(2 * np.pi * 11 * time_s)

                    rows.append({
                        "participant_id": pid,
                        "trial": trial,
                        "channel": ch,
                        "condition": condition,
                        "epoch_ms": t,
                        "amplitude_uv": round(amp, 2),
                    })

    df = pd.DataFrame(rows)
    df.to_csv(dest, index=False)
    print(f"  Generated {len(df)} rows -> {dest}")


def download_gene_expression(data_dir: Path) -> None:
    """Generate a synthetic gene expression dataset (high-dimensional)."""
    dest = data_dir / "gene_expression.csv"
    if dest.exists():
        print("  Already exists, skipping.")
        return
    _ensure_dir(data_dir)

    rng = np.random.default_rng(271)
    n_samples = 80
    n_genes = 200
    n_de_genes = 25  # differentially expressed genes

    conditions = ["cancer"] * 40 + ["normal"] * 40
    sample_ids = [f"S{i:03d}" for i in range(1, n_samples + 1)]

    # Generate expression matrix
    expression = rng.normal(loc=8.0, scale=1.5, size=(n_samples, n_genes))

    # Add differential expression for the first n_de_genes genes in cancer samples
    for g in range(n_de_genes):
        # Effect sizes vary — some genes strongly differentially expressed, some subtle
        effect = rng.uniform(1.0, 3.0)
        if g % 3 == 0:
            # Some genes upregulated in cancer
            expression[:40, g] += effect
        else:
            # Some genes downregulated in cancer
            expression[:40, g] -= effect * 0.7

    # Add correlated gene groups (simulate co-regulated pathways)
    for start in [30, 60, 100, 150]:
        shared_signal = rng.normal(0, 0.8, size=(n_samples, 1))
        block_size = min(10, n_genes - start)
        expression[:, start:start + block_size] += shared_signal * 0.5

    # Round to 3 decimal places
    expression = np.round(expression, 3)

    # Build dataframe
    gene_cols = [f"gene_{i:03d}" for i in range(1, n_genes + 1)]
    df = pd.DataFrame(expression, columns=gene_cols)
    df.insert(0, "condition", conditions)
    df.insert(0, "sample_id", sample_ids)

    df.to_csv(dest, index=False)
    print(f"  Generated {n_samples} samples x {n_genes} genes -> {dest}")


def download_climate(data_dir: Path) -> None:
    """Download the Our World in Data CO2 emissions dataset."""
    dest = data_dir / "owid-co2-data.csv"
    if dest.exists():
        print("  Already exists, skipping.")
        return
    _ensure_dir(data_dir)
    url = "https://raw.githubusercontent.com/owid/co2-data/master/owid-co2-data.csv"
    _download_file(url, dest)
    print(f"  Saved to {dest}")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def download_energy_forecast(output_dir: Path) -> None:
    """Generate synthetic energy demand dataset for deep learning forecasting."""
    csv_path = output_dir / "energy_demand.csv"
    data_dir = output_dir
    if csv_path.exists():
        print(f"  Already exists: {csv_path}")
        return

    data_dir.mkdir(parents=True, exist_ok=True)

    # 2 years of hourly data = 17,520 rows
    np.random.seed(42)
    hours = 365 * 2 * 24
    timestamps = pd.date_range("2023-01-01", periods=hours, freq="h")

    # Build realistic energy demand with multiple patterns
    t = np.arange(hours)

    # Daily cycle (peak at 18:00, trough at 04:00)
    daily = 15 * np.sin(2 * np.pi * (t - 6) / 24)

    # Weekly cycle (lower on weekends)
    weekly = 5 * np.sin(2 * np.pi * t / (24 * 7))

    # Annual cycle (higher in winter/summer for heating/cooling)
    annual = 20 * np.sin(2 * np.pi * (t - 24 * 30) / (24 * 365))

    # Trend (slight upward)
    trend = 0.001 * t

    # Non-linear interactions (what makes DL outperform ARIMA)
    hour_of_day = t % 24
    day_of_week = (t // 24) % 7
    month = ((t // (24 * 30)) % 12).astype(float)

    # Temperature (correlated with annual cycle + noise)
    temperature = 15 + 12 * np.sin(2 * np.pi * (t - 24 * 30) / (24 * 365)) + np.random.normal(0, 3, hours)

    # Non-linear temperature effect (U-shaped: high demand at extremes)
    temp_effect = 0.3 * (temperature - 18) ** 2

    # Holiday effects (random days with reduced demand)
    holidays = np.zeros(hours)
    holiday_days = np.random.choice(365 * 2, size=20, replace=False)
    for hd in holiday_days:
        start = hd * 24
        end = min(start + 24, hours)
        holidays[start:end] = -15

    # Base demand
    base = 150
    demand = base + daily + weekly + annual + trend + temp_effect + holidays
    demand += np.random.normal(0, 5, hours)  # noise
    demand = np.maximum(demand, 50)  # floor

    # Wind and solar (affect net demand)
    wind_speed = np.abs(5 + 3 * np.sin(2 * np.pi * t / (24 * 3)) + np.random.normal(0, 2, hours))
    solar_irradiance = np.maximum(0, np.sin(np.pi * (hour_of_day - 6) / 12)) * (0.8 + 0.2 * np.random.random(hours))
    solar_irradiance *= (1 + 0.3 * np.sin(2 * np.pi * t / (24 * 365)))  # seasonal

    df = pd.DataFrame({
        "timestamp": timestamps,
        "demand_mw": np.round(demand, 1),
        "temperature_c": np.round(temperature, 1),
        "wind_speed_ms": np.round(wind_speed, 1),
        "solar_irradiance": np.round(solar_irradiance, 3),
        "hour": hour_of_day,
        "day_of_week": day_of_week,
        "is_weekend": (day_of_week >= 5).astype(int),
        "month": (month + 1).astype(int),
    })

    df.to_csv(csv_path, index=False)
    print(f"  Generated {len(df)} rows -> {csv_path}")


DOWNLOADERS = {
    "stroop": download_stroop,
    "depression": download_depression,
    "marketing": download_marketing,
    "housing": download_housing,
    "text-sentiment": download_text_sentiment,
    "images": download_images,
    "eeg": download_eeg,
    "gene-expression": download_gene_expression,
    "climate": download_climate,
    "energy-forecast": download_energy_forecast,
}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download or generate test datasets for Urika integration testing."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Root output directory (default: dev/test-datasets/ relative to repo root)",
    )
    parser.add_argument(
        "--dataset",
        choices=DATASETS,
        default=None,
        help="Download a single dataset instead of all",
    )
    args = parser.parse_args()

    # Resolve output directory
    if args.output_dir is not None:
        output_dir = args.output_dir.resolve()
    else:
        # Default: dev/test-datasets/ relative to this script's location
        output_dir = Path(__file__).resolve().parent

    datasets = [args.dataset] if args.dataset else DATASETS

    print(f"Output directory: {output_dir}")
    print(f"Datasets: {', '.join(datasets)}\n")

    errors: list[str] = []
    for name in datasets:
        data_dir = output_dir / name / "data"
        print(f"[{name}]")
        try:
            DOWNLOADERS[name](data_dir)
        except Exception as exc:
            print(f"  ERROR: {exc}")
            errors.append(name)
        print()

    if errors:
        print(f"Completed with errors in: {', '.join(errors)}")
        sys.exit(1)
    else:
        print("All datasets ready.")


if __name__ == "__main__":
    main()
