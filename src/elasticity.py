"""Own-price elasticity and promotion lift, estimated together.

THE MODEL
---------
For each commodity, on a product x week panel:

    log(units) = b * log(price)
               + g * display_intensity
               + d * mailer_intensity
               + product fixed effect
               + week fixed effect
               + e

`b` is the own-price elasticity: the percentage change in units for a one
percent change in price. `exp(g) - 1` is the lift from putting an item on
display in every store, and `exp(d) - 1` the lift from featuring it in the
mailer.

WHY ALL THREE IN ONE EQUATION
-----------------------------
Price, display and mailer move together - a retailer discounts an item in the
same week it features it. Estimate the price effect alone and it absorbs the
display effect, and the elasticity comes out too large. Each coefficient here
is purged of the other two.

WHY FIXED EFFECTS
-----------------
    product   absorbs the level difference between a 40-cent item and a
              12-dollar one, so the estimate comes from a product being
              cheaper than its OWN normal price, not from cheap products
              selling more than expensive ones
    week      absorbs anything that moved every product at once - a holiday,
              a pay week, the weather

Both are absorbed by alternating-projection demeaning rather than dummies,
because a commodity can contain two thousand products and a hundred weeks.

THE IDENTIFYING ASSUMPTION, AND WHY IT IS NOT SAFE
--------------------------------------------------
Within a product and a week, the remaining variation in price is assumed
unrelated to demand. It is not, and the direction is knowable: retailers
discount what they expect to sell. A product-specific demand spike that the
retailer anticipated and priced into will be attributed to the price cut, and
the elasticity will come out TOO LARGE in magnitude.

The display and mailer controls remove the main channel through which that
happens, because anticipated demand is usually acted on by promoting. They do
not remove all of it. Every number this module produces should be read as an
upper bound on sensitivity, and that is stated beside the output rather than in
a footnote.

Run:
    python src/elasticity.py --project-root .
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

# A product needs enough weeks for a within-product estimate to mean anything.
MIN_WEEKS_PER_PRODUCT = 12
# And the panel needs enough products for the week effects to be identified.
MIN_PRODUCTS_PER_COMMODITY = 30
MIN_ROWS_PER_COMMODITY = 600
# Demeaning passes. Two-way demeaning is exact in one pass only on a balanced
# panel; these are unbalanced, so the projections are alternated to convergence.
DEMEAN_PASSES = 12


def absorb(frame: pd.DataFrame, columns: list[str], keys: list[str]) -> pd.DataFrame:
    """Remove the fixed effects in `keys` from `columns` by alternating projection."""
    out = frame[columns].astype(float).copy()
    for _ in range(DEMEAN_PASSES):
        before = out.to_numpy(copy=True)
        for key in keys:
            out = out - out.groupby(frame[key].to_numpy()).transform("mean")
        if np.nanmax(np.abs(out.to_numpy() - before)) < 1e-10:
            break
    return out


def fit(panel: pd.DataFrame) -> dict[str, float] | None:
    """OLS of demeaned log-units on demeaned regressors, with robust errors."""
    regressors = ["log_price", "display_intensity", "mailer_intensity"]
    data = panel.dropna(subset=["log_units", *regressors])
    if len(data) < MIN_ROWS_PER_COMMODITY:
        return None

    demeaned = absorb(data, ["log_units", *regressors], ["product_id", "week_number"])
    y = demeaned["log_units"].to_numpy()
    X = demeaned[regressors].to_numpy()
    if np.linalg.matrix_rank(X) < X.shape[1] or np.allclose(X[:, 0].std(), 0):
        return None

    xtx_inv = np.linalg.pinv(X.T @ X)
    beta = xtx_inv @ (X.T @ y)
    residual = y - X @ beta

    # Degrees of freedom: the absorbed effects cost one parameter each.
    absorbed = data["product_id"].nunique() + data["week_number"].nunique() - 1
    dof = max(len(data) - X.shape[1] - absorbed, 1)

    # HC1 heteroskedasticity-robust covariance. Prices and volumes are both
    # heavily skewed, so the classical standard errors would be too narrow.
    meat = (X * (residual ** 2)[:, None]).T @ X
    cov = xtx_inv @ meat @ xtx_inv * (len(data) / dof)
    se = np.sqrt(np.diag(cov))

    total = float(((y - y.mean()) ** 2).sum())
    return {
        "elasticity": float(beta[0]),
        "elasticity_se": float(se[0]),
        "display_coefficient": float(beta[1]),
        "display_se": float(se[1]),
        "mailer_coefficient": float(beta[2]),
        "mailer_se": float(se[2]),
        "observations": int(len(data)),
        "products": int(data["product_id"].nunique()),
        "weeks": int(data["week_number"].nunique()),
        "within_r_squared": float(1 - (residual ** 2).sum() / total) if total else float("nan"),
    }


def run(project_root: Path) -> pd.DataFrame:
    connection = duckdb.connect(str(project_root / "artifacts" / "dunnhumby.duckdb"))
    try:
        panel = connection.execute(
            f"""
            WITH eligible AS (
                SELECT product_id
                FROM mart.product_week
                WHERE units > 0 AND unit_paid_price > 0
                GROUP BY product_id
                HAVING COUNT(*) >= {MIN_WEEKS_PER_PRODUCT}
                   AND STDDEV(LN(unit_paid_price)) > 0.02
            )
            SELECT w.commodity, w.department, w.product_id, w.week_number,
                   w.units, w.unit_paid_price, w.revenue,
                   w.display_intensity, w.mailer_intensity
            FROM mart.product_week w
            JOIN eligible USING (product_id)
            WHERE w.units > 0 AND w.unit_paid_price > 0 AND w.commodity IS NOT NULL
            """
        ).fetchdf()

        panel["log_units"] = np.log(panel["units"].astype(float))
        panel["log_price"] = np.log(panel["unit_paid_price"].astype(float))

        rows = []
        for commodity, group in panel.groupby("commodity", sort=False):
            if group["product_id"].nunique() < MIN_PRODUCTS_PER_COMMODITY:
                continue
            result = fit(group)
            if result is None:
                continue
            rows.append(
                {
                    "commodity": commodity,
                    "department": group["department"].mode().iat[0],
                    "revenue": float(group["revenue"].sum()),
                    **result,
                }
            )

        results = pd.DataFrame(rows)
        results["elasticity_t"] = results["elasticity"] / results["elasticity_se"]
        results["display_lift_pct"] = (np.exp(results["display_coefficient"]) - 1) * 100
        results["mailer_lift_pct"] = (np.exp(results["mailer_coefficient"]) - 1) * 100
        # A positive own-price elasticity is not a finding, it is a warning: the
        # within-product price variation in that category is too weak, too
        # confounded, or both. Flagged rather than reported as a result.
        results["implausible_sign"] = results["elasticity"] > 0
        results = results.sort_values("revenue", ascending=False).reset_index(drop=True)

        connection.register("elasticity_df", results)
        connection.execute(
            "CREATE OR REPLACE TABLE mart.price_elasticity AS SELECT * FROM elasticity_df"
        )
    finally:
        connection.close()
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args()
    results = run(args.project_root.resolve())
    print(f"{len(results)} commodities estimated\n")
    show = results.head(18)[
        ["commodity", "elasticity", "elasticity_se", "elasticity_t",
         "display_lift_pct", "mailer_lift_pct", "observations", "within_r_squared"]
    ]
    print(show.to_string(index=False, float_format=lambda v: f"{v:9.3f}"))
    flagged = int(results["implausible_sign"].sum())
    print(f"\ncommodities with an implausible positive elasticity: {flagged}")


if __name__ == "__main__":
    main()
