"""Did the coupon campaigns make households spend more?

WHY THIS IS THE INTERESTING PART
--------------------------------
Everything else in this project is observational. This is the one question the
data can get close to a causal answer on, because `campaign_table` records WHICH
households received each campaign - and 916 of the 2,500 received none at all.
That gives a comparison group that exists in the data rather than one assembled
by assumption.

THE ESTIMATOR
-------------
Difference-in-differences on weekly household spend:

    effect = (treated_after - treated_before) - (control_after - control_before)

Subtracting the control's own change removes anything that moved every
household at once - a holiday, a price war, the season.

THE ASSUMPTION IT RESTS ON, AND THE TEST FOR IT
-----------------------------------------------
Difference-in-differences is only valid if the two groups were on PARALLEL
TRENDS before the campaign. Not at the same level - at the same slope.

That is testable and this module tests it, by estimating the same difference
week by week over the eight weeks BEFORE the campaign began. If the groups were
already diverging then, the post-period difference cannot be attributed to the
campaign, and the estimate is reported as failed rather than quietly published.

This matters more here than in a textbook case, because the assignment was not
random. Dunnhumby targeted these campaigns. Treated households are therefore
expected to differ in level, and may differ in trend - which is exactly what the
pre-period test is for.

Run:
    python src/campaign_effect.py --project-root .
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

PRE_WEEKS = 8      # the window used for the parallel-trends test
POST_WEEKS = 8     # the window the effect is measured over
MIN_TREATED = 150  # below this a campaign is too small to estimate

# Matching caliper, in standard deviations of pre-period weekly spend. A
# treated household with no control inside this distance is dropped, and the
# number dropped is reported - it is the measure of how far outside the
# comparison group's range the campaign was targeted.
CALIPER_SD = 0.25


def campaign_panel(connection, campaign_id: int, start_week: int) -> pd.DataFrame:
    """Weekly spend per household, for treated and never-treated, around a campaign."""
    return connection.execute(
        f"""
        WITH treated AS (
            SELECT DISTINCT household_id FROM stg.campaign_household
            WHERE campaign_id = {campaign_id}
        ),
        never_treated AS (
            SELECT DISTINCT household_id FROM core.fact_sale
            WHERE household_id NOT IN (SELECT household_id FROM stg.campaign_household)
        ),
        cohort AS (
            SELECT household_id, TRUE AS is_treated FROM treated
            UNION ALL
            SELECT household_id, FALSE FROM never_treated
        ),
        weeks AS (
            SELECT UNNEST(RANGE({start_week - PRE_WEEKS}, {start_week + POST_WEEKS})) AS week_number
        )
        SELECT c.household_id, c.is_treated, w.week_number,
               w.week_number - {start_week}                      AS weeks_from_start,
               COALESCE(h.spend, 0)                              AS spend,
               COALESCE(h.baskets, 0)                            AS baskets
        FROM cohort c
        CROSS JOIN weeks w
        LEFT JOIN mart.household_week h
               ON h.household_id = c.household_id AND h.week_number = w.week_number
        """
    ).fetchdf()


def household_means(panel: pd.DataFrame) -> pd.DataFrame:
    """One pre and one post mean per household.

    Collapsing before estimating is deliberate: weekly observations on the same
    household are not independent, and treating them as if they were would
    shrink the standard error to something the data does not support.
    """
    panel = panel.copy()
    panel["after"] = panel["weeks_from_start"] >= 0
    household = (
        panel.groupby(["household_id", "is_treated", "after"])["spend"]
        .mean().unstack("after")
    )
    household.columns = ["before", "after"]
    household = household.dropna().reset_index()
    household["change"] = household["after"] - household["before"]
    return household


def estimate(household: pd.DataFrame, weights: pd.Series | None = None) -> dict[str, float]:
    """Difference-in-differences from collapsed household means."""
    treated = household.loc[household["is_treated"]]
    control = household.loc[~household["is_treated"]]
    w = weights if weights is not None else pd.Series(1.0, index=control.index)
    w = w.reindex(control.index).fillna(0.0)

    control_change = float(np.average(control["change"], weights=w)) if w.sum() else float("nan")
    control_before = float(np.average(control["before"], weights=w)) if w.sum() else float("nan")
    control_after = float(np.average(control["after"], weights=w)) if w.sum() else float("nan")

    effect = float(treated["change"].mean() - control_change)
    # Effective sample size for a weighted mean, so reused controls do not
    # inflate the precision.
    ess = float(w.sum() ** 2 / (w ** 2).sum()) if (w ** 2).sum() else 0.0
    control_var = float(np.average((control["change"] - control_change) ** 2, weights=w)) if w.sum() else np.nan
    se = float(np.sqrt(treated["change"].var(ddof=1) / len(treated) + control_var / max(ess, 1)))
    baseline = float(treated["before"].mean())
    return {
        "treated_households": int(len(treated)),
        "control_households": int((w > 0).sum()),
        "treated_before": baseline,
        "treated_after": float(treated["after"].mean()),
        "control_before": control_before,
        "control_after": control_after,
        "effect_per_week": effect,
        "effect_se": se,
        "effect_t": effect / se if se else float("nan"),
        "effect_pct_of_baseline": 100 * effect / baseline if baseline else float("nan"),
    }


def match_on_pre_spend(household: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series, dict]:
    """Nearest-neighbour match on pre-period spend, inside a caliper.

    The naive comparison fails because the campaigns were targeted: treated
    households already spent far more than the never-treated ones. Matching
    rebuilds a comparison group that starts from the same place.

    Treated households with no control inside the caliper are DROPPED. The
    number dropped is the honest measure of how far outside the comparison
    group's range the targeting went, and it is reported rather than absorbed.
    """
    treated = household.loc[household["is_treated"]].copy()
    control = household.loc[~household["is_treated"]].copy()
    caliper = CALIPER_SD * float(household["before"].std(ddof=1))

    control_sorted = control.sort_values("before").reset_index()
    values = control_sorted["before"].to_numpy()

    use_count = np.zeros(len(control_sorted))
    matched_rows = []
    for row in treated.itertuples():
        position = int(np.searchsorted(values, row.before))
        lower, upper = max(position - 1, 0), min(position + 1, len(values) - 1)
        candidates = range(lower, upper + 1)
        best, best_distance = None, np.inf
        for candidate in candidates:
            distance = abs(values[candidate] - row.before)
            if distance < best_distance:
                best, best_distance = candidate, distance
        if best is not None and best_distance <= caliper:
            use_count[best] += 1
            matched_rows.append(row.Index)

    weights = pd.Series(use_count, index=control_sorted["index"].to_numpy())
    kept = household.loc[household.index.isin(matched_rows) | ~household["is_treated"]]
    diagnostics = {
        "caliper": caliper,
        "treated_matched": int(len(matched_rows)),
        "treated_dropped": int(len(treated) - len(matched_rows)),
        "controls_used": int((use_count > 0).sum()),
    }
    return kept, weights, diagnostics


def parallel_trends(panel: pd.DataFrame) -> dict[str, float]:
    """Test whether the groups were already diverging before the campaign.

    Regresses the weekly treated-minus-control gap on time over the pre-period.
    A slope indistinguishable from zero supports the assumption; a significant
    slope means the difference-in-differences estimate is not interpretable.
    """
    pre = panel[panel["weeks_from_start"] < 0]
    weekly = (
        pre.groupby(["weeks_from_start", "is_treated"])["spend"].mean().unstack("is_treated")
    )
    weekly.columns = ["control", "treated"]
    weekly["gap"] = weekly["treated"] - weekly["control"]

    x = weekly.index.to_numpy(dtype=float)
    y = weekly["gap"].to_numpy(dtype=float)
    design = np.column_stack([np.ones_like(x), x])
    beta, *_ = np.linalg.lstsq(design, y, rcond=None)
    residual = y - design @ beta
    dof = max(len(x) - 2, 1)
    sigma2 = float((residual ** 2).sum() / dof)
    se = float(np.sqrt(sigma2 * np.linalg.pinv(design.T @ design)[1, 1]))
    t_statistic = float(beta[1] / se) if se else float("nan")
    return {
        "pre_trend_slope": float(beta[1]),
        "pre_trend_se": se,
        "pre_trend_t": t_statistic,
        "pre_trend_passes": bool(abs(t_statistic) < 2.0),
        "pre_weeks_used": int(len(x)),
    }


def event_study(panel: pd.DataFrame, campaign_id: int) -> pd.DataFrame:
    """The gap week by week, so the reader can see the trends rather than trust them."""
    weekly = (
        panel.groupby(["weeks_from_start", "is_treated"])["spend"].mean().unstack("is_treated")
    )
    weekly.columns = ["control_spend", "treated_spend"]
    weekly["gap"] = weekly["treated_spend"] - weekly["control_spend"]
    weekly["campaign_id"] = campaign_id
    weekly["period"] = np.where(weekly.index < 0, "before", "after")
    return weekly.reset_index()


def run(project_root: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    connection = duckdb.connect(str(project_root / "artifacts" / "dunnhumby.duckdb"))
    try:
        campaigns = connection.execute(
            f"""
            SELECT c.campaign_id, c.campaign_type, c.start_day, c.end_day,
                   CAST(CEIL(c.start_day / 7.0) AS INTEGER) AS start_week,
                   COUNT(DISTINCT h.household_id)           AS treated_households
            FROM stg.campaign c
            JOIN stg.campaign_household h USING (campaign_id, campaign_type)
            GROUP BY ALL
            HAVING COUNT(DISTINCT h.household_id) >= {MIN_TREATED}
            ORDER BY treated_households DESC
            """
        ).fetchdf()

        results, events = [], []
        for row in campaigns.itertuples():
            panel = campaign_panel(connection, row.campaign_id, row.start_week)
            if panel.empty:
                continue
            household = household_means(panel)
            naive = estimate(household)
            trends = parallel_trends(panel)

            kept, weights, diagnostics = match_on_pre_spend(household)
            matched = estimate(kept, weights) if diagnostics["treated_matched"] else {}

            results.append(
                {
                    "campaign_id": int(row.campaign_id),
                    "campaign_type": row.campaign_type,
                    "start_week": int(row.start_week),
                    **naive,
                    **trends,
                    # The gap in starting level is the diagnostic that matters
                    # more than the trend test here - see docs/assumptions.md.
                    "baseline_gap": naive["treated_before"] - naive["control_before"],
                    "baseline_ratio": (
                        naive["treated_before"] / naive["control_before"]
                        if naive["control_before"] else float("nan")
                    ),
                    **{f"matched_{k}": v for k, v in diagnostics.items()},
                    "matched_effect_per_week": matched.get("effect_per_week", float("nan")),
                    "matched_effect_se": matched.get("effect_se", float("nan")),
                    "matched_effect_t": matched.get("effect_t", float("nan")),
                    "matched_effect_pct": matched.get("effect_pct_of_baseline", float("nan")),
                    "matched_treated_before": matched.get("treated_before", float("nan")),
                    "matched_control_before": matched.get("control_before", float("nan")),
                    # An estimate whose assumption failed is not a weaker
                    # estimate, it is a different quantity. Marked, not ranked.
                    "interpretable": bool(trends["pre_trend_passes"]),
                }
            )
            events.append(event_study(panel, int(row.campaign_id)))

        estimates = pd.DataFrame(results)
        event_frame = pd.concat(events, ignore_index=True) if events else pd.DataFrame()

        connection.register("campaign_df", estimates)
        connection.register("event_df", event_frame)
        connection.execute(
            "CREATE OR REPLACE TABLE mart.campaign_effect AS SELECT * FROM campaign_df"
        )
        connection.execute(
            "CREATE OR REPLACE TABLE mart.campaign_event_study AS SELECT * FROM event_df"
        )
    finally:
        connection.close()
    return estimates, event_frame


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args()
    estimates, _ = run(args.project_root.resolve())
    print(f"{len(estimates)} campaigns estimated\n")
    print("NAIVE - never-treated households as the comparison group")
    print(
        estimates[
            ["campaign_id", "campaign_type", "treated_households",
             "treated_before", "control_before", "baseline_ratio",
             "effect_per_week", "effect_t", "pre_trend_t", "interpretable"]
        ].to_string(index=False, float_format=lambda v: f"{v:8.2f}")
    )
    print("\nMATCHED - controls matched on pre-period weekly spend")
    print(
        estimates[
            ["campaign_id", "campaign_type", "matched_treated_matched",
             "matched_treated_dropped", "matched_controls_used",
             "matched_treated_before", "matched_control_before",
             "matched_effect_per_week", "matched_effect_t", "matched_effect_pct"]
        ].to_string(index=False, float_format=lambda v: f"{v:8.2f}")
    )
    passed = int(estimates["interpretable"].sum())
    print(f"\nparallel-trends assumption holds: {passed} of {len(estimates)}")
    print(f"treated households dropped for lack of a comparable control: "
          f"{int(estimates['matched_treated_dropped'].sum()):,} of "
          f"{int(estimates['treated_households'].sum()):,}")


if __name__ == "__main__":
    main()
