"""Linear mixed model tool using statsmodels MixedLM."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import statsmodels.formula.api as smf

from urika.data.models import DatasetView
from urika.tools.base import ITool, ToolResult

if TYPE_CHECKING:
    import pandas as pd


class LinearMixedModelMethod(ITool):
    """Linear mixed model for repeated measures and nested data."""

    def name(self) -> str:
        return "linear_mixed_model"

    def description(self) -> str:
        return (
            "Linear mixed model (LMM) using statsmodels MixedLM. "
            "Suitable for repeated-measures designs, nested/hierarchical data, "
            "and datasets with random effects (random intercepts and slopes). "
            "Supports both formula-based and column-based specification."
        )

    def category(self) -> str:
        return "regression"

    def default_params(self) -> dict[str, Any]:
        return {
            "target": "",
            "features": None,
            "groups": "",
            "random_effects": None,
            "formula": None,
        }

    def run(self, data: DatasetView, params: dict[str, Any]) -> ToolResult:
        formula = params.get("formula")
        target = params.get("target", "")
        features = params.get("features")
        groups = params.get("groups", "")
        random_effects = params.get("random_effects")
        df = data.data.copy()

        # --- Formula mode ---
        if formula:
            return self._run_formula(df, formula, groups)

        # --- Column-based mode: validate inputs ---
        if target not in df.columns:
            return ToolResult(
                outputs={},
                metrics={},
                valid=False,
                error=f"Target column '{target}' not found",
            )

        if not groups or groups not in df.columns:
            return ToolResult(
                outputs={},
                metrics={},
                valid=False,
                error=f"Groups column '{groups}' not found",
            )

        n_groups = df[groups].nunique()
        if n_groups < 2:
            return ToolResult(
                outputs={},
                metrics={},
                valid=False,
                error=f"Insufficient groups: need at least 2, got {n_groups}",
            )

        numeric_df = df.select_dtypes(include="number")
        if features is None:
            feature_cols = [c for c in numeric_df.columns if c not in (target, groups)]
        else:
            feature_cols = [c for c in features if c in df.columns and c != target]

        if not feature_cols:
            return ToolResult(
                outputs={},
                metrics={},
                valid=False,
                error="No feature columns available",
            )

        # Build formula string
        rhs = " + ".join(feature_cols)
        formula_str = f"{target} ~ {rhs}"

        # Build random effects spec
        re_formula = None
        if random_effects:
            valid_re = [c for c in random_effects if c in feature_cols]
            if valid_re:
                re_formula = " + ".join(valid_re)

        return self._fit_model(df, formula_str, groups, re_formula)

    def _run_formula(self, df: "pd.DataFrame", formula: str, groups: str) -> ToolResult:
        """Run the model with an explicit formula string."""
        # Try to extract groups from formula or params
        if not groups or groups not in df.columns:
            # Attempt to find groups column from params
            return ToolResult(
                outputs={},
                metrics={},
                valid=False,
                error=f"Groups column '{groups}' not found (required even in formula mode)",
            )

        n_groups = df[groups].nunique()
        if n_groups < 2:
            return ToolResult(
                outputs={},
                metrics={},
                valid=False,
                error=f"Insufficient groups: need at least 2, got {n_groups}",
            )

        return self._fit_model(df, formula, groups, re_formula=None)

    def _fit_model(
        self,
        df: "pd.DataFrame",
        formula: str,
        groups: str,
        re_formula: str | None,
    ) -> ToolResult:
        """Fit the mixed model and return results."""
        try:
            model = smf.mixedlm(
                formula,
                data=df,
                groups=df[groups],
                re_formula=f"~{re_formula}" if re_formula else "~1",
            )
            result = model.fit(disp=False)
        except Exception as exc:
            return ToolResult(
                outputs={},
                metrics={},
                valid=False,
                error=f"Model fitting failed: {exc}",
            )

        # Extract fixed effects
        fixed_effects = {name: float(val) for name, val in result.fe_params.items()}

        # Extract random effects variance
        try:
            re_var = {name: float(val) for name, val in result.cov_re.unstack().items()}
        except Exception:
            re_var = {"group_var": float(result.cov_re.iloc[0, 0])}

        converged = 1.0 if result.converged else 0.0

        return ToolResult(
            outputs={
                "fixed_effects": fixed_effects,
                "random_effects_variance": re_var,
                "formula_used": formula,
            },
            metrics={
                "aic": float(result.aic),
                "bic": float(result.bic),
                "log_likelihood": float(result.llf),
                "converged": converged,
            },
        )


def get_tool() -> ITool:
    """Factory function for registry auto-discovery."""
    return LinearMixedModelMethod()
