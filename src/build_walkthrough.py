"""Generate notebooks/00_walkthrough.ipynb.

Generated rather than hand-edited, so it cannot drift from the pipeline.

Run:
    python src/build_walkthrough.py --project-root .
    jupyter nbconvert --execute --to notebook --inplace notebooks/00_walkthrough.ipynb
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def md(text: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": text.splitlines(keepends=True)}


def code(text: str) -> dict:
    return {"cell_type": "code", "execution_count": None, "metadata": {},
            "outputs": [], "source": text.splitlines(keepends=True)}


def section(number: str, title: str, what: str, built_by: str, written_to: str) -> dict:
    return md(
        f"---\n\n## {number} - {title}\n\n{what}\n\n"
        f"| | |\n|---|---|\n| **Built by** | {built_by} |\n| **Written to** | {written_to} |\n"
    )


def conclusion(text: str) -> dict:
    return md(f"> **Conclusion.** {text}\n")


SETUP = '''import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()
sys.path.insert(0, str(ROOT / "src"))

pd.set_option("display.width", 230)
pd.set_option("display.max_columns", 60)
pd.set_option("display.max_colwidth", 44)
# Previews show at least 10 rows throughout. Three is not enough to see a
# pattern, a null cluster, or a grain finer than you assumed.
pd.set_option("display.max_rows", 40)
pd.set_option("display.min_rows", 20)

db = duckdb.connect(str(ROOT / "artifacts" / "dunnhumby.duckdb"), read_only=True)


def q(sql):
    return db.execute(sql).fetchdf()


def show_py(filename, func, lines=None):
    """Print the production code that does something, read at run time.

    Not a copy - the file is read as this cell runs, so what you see is what
    executed.
    """
    path = ROOT / "src" / filename
    rows = path.read_text(encoding="utf-8").splitlines()
    start = next((i for i, r in enumerate(rows)
                  if r.startswith((f"def {func}(", f"{func} = "))), None)
    if start is None:
        print(f"{func} not found in {filename}")
        return
    end = start + 1
    while end < len(rows) and not rows[end].startswith(("def ", "class ", "@")):
        end += 1
    body = rows[start:end]
    if lines:
        body = body[:lines]
    print(f"# {filename}, line {start + 1}\\n")
    print("\\n".join(body).rstrip())


print("schemas:", ", ".join(
    r[0] for r in db.execute(
        "SELECT DISTINCT schema_name FROM duckdb_tables() ORDER BY 1").fetchall()))
'''


def build(project_root: Path) -> Path:
    cells: list[dict] = []

    cells += [
        md(
            "# Dunnhumby - price elasticity and promotion effectiveness\n"
            "\n"
            "### Read this top to bottom and you have the whole project\n"
            "\n"
            "Two years of a grocery retailer's transactions: **2.6M lines, 2,500 households,\n"
            "92,353 products, 582 stores**, plus **36.8M product-store-week promotion records**\n"
            "and a coupon campaign log recording which households were targeted.\n"
            "\n"
            "Three questions:\n"
            "\n"
            "1. How much does demand move when price moves?\n"
            "2. What does putting an item on display, or in the mailer, actually do?\n"
            "3. Did the coupon campaigns make households spend more?\n"
            "\n"
            "**The third one is where the project earns its keep.** The first answer it gave\n"
            "was that coupons made people spend less, and most of what follows is about why\n"
            "that happened and what it took to get a believable number instead.\n"
        ),
        md(
            "### The route through\n"
            "\n"
            "| Part | |\n"
            "|---|---|\n"
            "| 1 | The price decomposition everything rests on |\n"
            "| 2 | Checks: the layer contract, and what the source gets wrong |\n"
            "| 3 | Is there enough price variation to measure anything? |\n"
            "| 4 | Elasticity and promotion lift, estimated together |\n"
            "| 5 | What the elasticities say, and where I do not believe them |\n"
            "| 6 | The campaign question, answered badly |\n"
            "| 7 | Parallel trends passes. The answer is still wrong |\n"
            "| 8 | Looking at the levels |\n"
            "| 9 | Matching, and what it costs |\n"
            "| 10 | The answer, and the bias still in it |\n"
        ),
        code(SETUP),
    ]

    # ---------------------------------------------------------------- PART 1
    cells += [
        section(
            "Part 1", "The price decomposition everything rests on",
            "**The problem.** To measure a response to price you need a price, and the source\n"
            "does not contain one. It contains what the customer paid and three separate\n"
            "discount columns, all stored negative, with no statement of how they combine.",
            "`src/build_warehouse.py`",
            "`stg.transactions`, `core.fact_sale`",
        ),
        md(
            "| Column | What it is | Who funds it |\n"
            "|---|---|---|\n"
            "| `SALES_VALUE` | what the customer paid | - |\n"
            "| `RETAIL_DISC` | loyalty-card discount | the retailer |\n"
            "| `COUPON_MATCH_DISC` | the retailer matching a manufacturer coupon | the retailer |\n"
            "| `COUPON_DISC` | a manufacturer coupon | **the manufacturer** |\n"
            "\n"
            "The shelf price is what a shopper with no card and no coupon would have paid, so\n"
            "the two **retailer-funded** discounts are added back:\n"
            "\n"
            "```sql\n"
            "base_value = SALES_VALUE - RETAIL_DISC - COUPON_MATCH_DISC\n"
            "```\n"
            "\n"
            "`COUPON_DISC` is deliberately **not** added back. The manufacturer funds it, so the\n"
            "retailer still receives that money - adding it to the shelf price would overstate\n"
            "what the shopper was asked to pay.\n"
            "\n"
            "That is a judgement call, not a fact in the data. It is stated here, in the module\n"
            "docstring and in `docs/assumptions.md`, because every elasticity in this project\n"
            "inherits it.\n"
        ),
        code(
            'q("""\n'
            "    SELECT product_id, week_number, units,\n"
            "           ROUND(paid_value, 2)       AS paid,\n"
            "           ROUND(retailer_discount, 2) AS retail_disc,\n"
            "           ROUND(manufacturer_coupon, 2) AS mfr_coupon,\n"
            "           ROUND(retailer_coupon_match, 2) AS coupon_match,\n"
            "           ROUND(base_value, 2)       AS shelf_value,\n"
            "           ROUND(unit_paid_price, 3)  AS unit_paid,\n"
            "           ROUND(unit_base_price, 3)  AS unit_shelf,\n"
            "           ROUND(discount_depth, 3)   AS depth\n"
            "    FROM core.fact_sale\n"
            "    WHERE retailer_discount < 0 AND units BETWEEN 1 AND 4\n"
            "    ORDER BY paid_value DESC LIMIT 12\n"
            '""")'
        ),
        conclusion(
            "Nothing downstream works until this is decided, and the source decides none of "
            "it. Writing the rule down - including the part that is a choice rather than a "
            "derivation - is the difference between an elasticity someone can check and one "
            "they have to trust."
        ),
    ]

    # ---------------------------------------------------------------- PART 2
    cells += [
        section(
            "Part 2", "Checks: the layer contract, and what the source gets wrong",
            "**The contract.** `stg` may not lose a row. `core` may not change the row count of\n"
            "the fact it is built from. `mart` may not introduce a number that cannot be\n"
            "derived from `core`.\n"
            "\n"
            "Stated before the SQL was written, then tested.",
            "`src/build_warehouse.py` - `build_qa()`",
            "`qa.layer_contract`, `qa.source_quality`",
        ),
        code('q("SELECT * FROM qa.layer_contract")'),
        md(
            "Zero at every step, and the revenue ties to the dollar between `core` and `mart`.\n"
            "\n"
            "### What the source gets wrong\n"
        ),
        code('q("SELECT * FROM qa.source_quality ORDER BY rows_affected DESC")'),
        md(
            "Four of these are ordinary and handled by exclusion. **One is an anomaly worth\n"
            "naming:** 36 rows store the retailer discount as a *positive* number - a discount\n"
            "that raises the price.\n"
            "\n"
            "It is 36 rows in 2.6 million, so it changes nothing. The reason to report it is\n"
            "that a reader who finds it themselves will wonder what else went unexamined.\n"
        ),
        code(
            'q("""\n'
            "    SELECT COUNT(*) FILTER (WHERE usable_for_pricing)        AS usable_lines,\n"
            "           COUNT(*)                                          AS total_lines,\n"
            "           ROUND(100.0 * COUNT(*) FILTER (WHERE usable_for_pricing)\n"
            "               / COUNT(*), 1)                                AS pct_of_lines,\n"
            "           ROUND(100.0 * SUM(paid_value) FILTER (WHERE usable_for_pricing)\n"
            "               / SUM(paid_value), 1)                         AS pct_of_revenue\n"
            "    FROM core.fact_sale\n"
            '""")'
        ),
        conclusion(
            "98.4% of lines and 92.4% of revenue survive into the pricing analysis. The "
            "exclusions are flagged on the row rather than filtered away in a WHERE clause, "
            "so they stay countable."
        ),
    ]

    # ---------------------------------------------------------------- PART 3
    cells += [
        section(
            "Part 3", "Is there enough price variation to measure anything?",
            "**The question before the question.** Elasticity is identified by a product being\n"
            "cheaper than its *own* normal price. If prices barely move, there is nothing to\n"
            "estimate from, and a regression will return a number anyway.\n"
            "\n"
            "This is the check that decides whether the rest of the project is possible - and\n"
            "it is the check that TheLook failed, which is why the elasticity work is here and\n"
            "not there.",
            "`mart.product_week`",
            "-",
        ),
        code(
            'q("""\n'
            "    WITH v AS (\n"
            "        SELECT product_id, commodity, COUNT(*) AS weeks,\n"
            "               STDDEV(LN(unit_paid_price)) AS sd_log_price,\n"
            "               AVG(discount_depth)         AS avg_depth\n"
            "        FROM mart.product_week\n"
            "        WHERE unit_paid_price > 0 AND units > 0\n"
            "        GROUP BY 1, 2 HAVING COUNT(*) >= 20\n"
            "    )\n"
            "    SELECT COUNT(*)                                          AS products,\n"
            "           ROUND(AVG(sd_log_price), 4)                       AS mean_sd_log_price,\n"
            "           COUNT(*) FILTER (WHERE sd_log_price > 0.05)       AS with_real_variation,\n"
            "           ROUND(100.0 * COUNT(*) FILTER (WHERE sd_log_price > 0.05)\n"
            "               / COUNT(*), 1)                                AS pct,\n"
            "           ROUND(AVG(avg_depth), 4)                          AS mean_discount_depth\n"
            "    FROM v\n"
            '""")'
        ),
        md("### Which categories actually discount\n"),
        code(
            'q("""\n'
            "    SELECT commodity,\n"
            "           COUNT(DISTINCT product_id)        AS products,\n"
            "           COUNT(*)                          AS product_weeks,\n"
            "           ROUND(SUM(revenue))               AS revenue,\n"
            "           ROUND(AVG(discount_depth), 3)     AS avg_discount_depth\n"
            "    FROM mart.product_week WHERE commodity IS NOT NULL\n"
            "    GROUP BY 1 ORDER BY revenue DESC LIMIT 14\n"
            '""")'
        ),
        conclusion(
            "14,170 of 16,310 products carry real price variation, and mean discount depth is "
            "11%. Note BEERS/ALES and CIGARETTES at ~0% depth - price-controlled categories "
            "where no elasticity can be identified, whatever a regression returns."
        ),
    ]

    # ---------------------------------------------------------------- PART 4
    cells += [
        section(
            "Part 4", "Elasticity and promotion lift, estimated together",
            "**The model.** On a product x week panel, per commodity:\n"
            "\n"
            "```\n"
            "log(units) = b*log(price) + g*display + d*mailer + product FE + week FE + e\n"
            "```\n"
            "\n"
            "All three regressors in one equation, deliberately.",
            "`src/elasticity.py`",
            "`mart.price_elasticity` - one row per commodity",
        ),
        md(
            "### Why together\n"
            "\n"
            "Price, display and mailer move at the same time - a retailer discounts in the same\n"
            "week it features. Estimate price alone and it absorbs the display effect, and the\n"
            "elasticity comes out too large.\n"
            "\n"
            "### Why fixed effects\n"
            "\n"
            "| | |\n"
            "|---|---|\n"
            "| **product** | absorbs the level difference between a 40-cent item and a 12-dollar one, so the estimate comes from a product being cheaper than its *own* normal price |\n"
            "| **week** | absorbs anything that moved every product at once - a holiday, a pay week, the weather |\n"
            "\n"
            "Both are absorbed by alternating-projection demeaning rather than dummies, because\n"
            "a commodity can contain two thousand products across a hundred weeks.\n"
        ),
        code('show_py("elasticity.py", "absorb")'),
        code('show_py("elasticity.py", "fit", lines=34)'),
        conclusion(
            "The standard errors are heteroskedasticity-robust and the degrees of freedom are "
            "charged for every absorbed effect. Prices and volumes are both heavily skewed, so "
            "classical errors here would be too narrow and every t-statistic too confident."
        ),
    ]

    # ---------------------------------------------------------------- PART 5
    cells += [
        section(
            "Part 5", "What the elasticities say, and where I do not believe them",
            "147 commodities estimated, 134 of them statistically significant.",
            "`src/elasticity.py`",
            "`mart.price_elasticity`",
        ),
        code(
            'q("""\n'
            "    SELECT COUNT(*)                                        AS commodities,\n"
            "           COUNT(*) FILTER (WHERE elasticity < -1)         AS elastic,\n"
            "           COUNT(*) FILTER (WHERE elasticity BETWEEN -1 AND 0) AS inelastic,\n"
            "           COUNT(*) FILTER (WHERE elasticity > 0)          AS wrong_sign,\n"
            "           COUNT(*) FILTER (WHERE ABS(elasticity_t) > 2)   AS significant,\n"
            "           ROUND(quantile_cont(elasticity, 0.25), 2)       AS p25,\n"
            "           ROUND(quantile_cont(elasticity, 0.50), 2)       AS median,\n"
            "           ROUND(quantile_cont(elasticity, 0.75), 2)       AS p75,\n"
            "           ROUND(AVG(display_lift_pct), 1)                 AS mean_display_lift,\n"
            "           ROUND(AVG(mailer_lift_pct), 1)                  AS mean_mailer_lift\n"
            "    FROM mart.price_elasticity\n"
            '""")'
        ),
        md("### The most and least price-sensitive categories\n"),
        code(
            'q("""\n'
            "    SELECT commodity,\n"
            "           ROUND(elasticity, 2)        AS elasticity,\n"
            "           ROUND(elasticity_t, 1)      AS t_stat,\n"
            "           ROUND(display_lift_pct, 1)  AS display_lift_pct,\n"
            "           ROUND(mailer_lift_pct, 1)   AS mailer_lift_pct,\n"
            "           ROUND(revenue)              AS revenue,\n"
            "           observations\n"
            "    FROM mart.price_elasticity\n"
            "    WHERE revenue > 25000 AND NOT implausible_sign\n"
            "    ORDER BY elasticity LIMIT 14\n"
            '""")'
        ),
        md(
            "### The pattern is the commercial point\n"
            "\n"
            "**Stockpilable, branded, frequently promoted goods are elastic.** Bacon at −1.77,\n"
            "refrigerated juice at −1.71, cold cereal at −1.51. A shopper can buy bacon this\n"
            "week instead of next, so a price cut mostly moves *when* they buy.\n"
            "\n"
            "**Fresh meat is inelastic on price but enormous on the mailer.** Beef: elasticity\n"
            "−0.24, mailer lift **+161%**. It is a traffic driver - bought because the trip\n"
            "happened, not because the price fell.\n"
            "\n"
            "Those two facts imply opposite promotional strategies, and the model can separate\n"
            "them only because display and mailer sit in the equation beside price.\n"
        ),
        md("### Where I do not believe the estimate\n"),
        code(
            'q("""\n'
            "    SELECT commodity, ROUND(elasticity, 3) AS elasticity,\n"
            "           ROUND(elasticity_t, 2) AS t_stat, ROUND(revenue) AS revenue,\n"
            "           observations\n"
            "    FROM mart.price_elasticity\n"
            "    WHERE revenue > 20000 AND elasticity > -0.12\n"
            "    ORDER BY elasticity DESC LIMIT 12\n"
            '""")'
        ),
        conclusion(
            "Potatoes, apples and other vegetables return elasticities indistinguishable from "
            "zero. That is almost certainly **measurement, not behaviour**: produce is sold by "
            "weight, so 'units' and therefore unit price are not comparable between baskets. "
            "The 20-unit filter removes the worst of it and does not fix it. Reported with the "
            "flag rather than dropped."
        ),
        md(
            "### The assumption underneath all of it\n"
            "\n"
            "Within a product and a week, the remaining price variation is assumed unrelated to\n"
            "demand. **It is not, and the direction is knowable:** retailers discount what they\n"
            "expect to sell, so a demand spike the retailer anticipated gets attributed to the\n"
            "price cut.\n"
            "\n"
            "Every elasticity here should be read as an **upper bound on sensitivity**. The\n"
            "display and mailer controls remove the main channel through which that happens -\n"
            "promotion - but not all of it.\n"
        ),
    ]

    # ---------------------------------------------------------------- PART 6
    cells += [
        section(
            "Part 6", "The campaign question, answered badly",
            "**The question.** 2,500 households, 1,584 of whom received at least one coupon\n"
            "campaign. Did the campaigns make them spend more?\n"
            "\n"
            "916 households received nothing. That is a comparison group that exists in the\n"
            "data rather than one assembled by assumption - which is rare, and is why this\n"
            "dataset is worth the trouble.",
            "`src/campaign_effect.py`",
            "`mart.campaign_effect`",
        ),
        md(
            "**The estimator.** Difference-in-differences on weekly household spend:\n"
            "\n"
            "```\n"
            "effect = (treated after - treated before) - (control after - control before)\n"
            "```\n"
            "\n"
            "Subtracting the control's own change removes anything that moved every household\n"
            "at once - a holiday, a price war, the season.\n"
        ),
        code(
            'q("""\n'
            "    SELECT campaign_id, campaign_type, treated_households,\n"
            "           ROUND(effect_per_week, 2)        AS effect_per_week,\n"
            "           ROUND(effect_se, 2)              AS std_error,\n"
            "           ROUND(effect_t, 2)               AS t_stat,\n"
            "           ROUND(effect_pct_of_baseline, 1) AS pct_of_baseline\n"
            "    FROM mart.campaign_effect ORDER BY effect_t\n"
            '""")'
        ),
        conclusion(
            "**Twelve of 17 campaigns show a negative effect, six of them significantly so** - "
            "up to -8.7% of baseline weekly spend. Coupons do not make people spend less. The "
            "estimate is not a surprising finding, it is a broken one, and the rest of this "
            "notebook is about finding out how."
        ),
    ]

    # ---------------------------------------------------------------- PART 7
    cells += [
        section(
            "Part 7", "Parallel trends passes. The answer is still wrong",
            "**The standard check.** Difference-in-differences is valid only if the two groups\n"
            "were on parallel trends beforehand - not at the same level, at the same *slope*.\n"
            "\n"
            "That is testable: regress the weekly treated-minus-control gap on time over the\n"
            "eight weeks before the campaign and see whether the slope differs from zero.",
            "`src/campaign_effect.py` - `parallel_trends()`",
            "`mart.campaign_effect`",
        ),
        code('show_py("campaign_effect.py", "parallel_trends")'),
        code(
            'q("""\n'
            "    SELECT campaign_id, campaign_type,\n"
            "           ROUND(pre_trend_slope, 3) AS pre_trend_slope,\n"
            "           ROUND(pre_trend_t, 2)     AS pre_trend_t,\n"
            "           pre_trend_passes,\n"
            "           ROUND(effect_per_week, 2) AS naive_effect,\n"
            "           ROUND(effect_t, 2)        AS naive_t\n"
            "    FROM mart.campaign_effect ORDER BY campaign_id\n"
            '""")'
        ),
        conclusion(
            "**Fifteen of 17 pass.** The standard check gives the green light on exactly the "
            "campaigns producing an impossible answer. A test that passes while the result is "
            "wrong is more dangerous than no test, because it ends the enquiry."
        ),
    ]

    # ---------------------------------------------------------------- PART 8
    cells += [
        section(
            "Part 8", "Looking at the levels",
            "**The diagnostic that caught it was not clever.** Parallel trends is a statement\n"
            "about slopes. It says nothing about whether the two groups are comparable at all.\n"
            "\n"
            "So: how much did each group spend before the campaign started?",
            "`mart.campaign_effect`",
            "-",
        ),
        code(
            'q("""\n'
            "    SELECT campaign_id, campaign_type, treated_households,\n"
            "           ROUND(treated_before, 2)  AS treated_spend_before,\n"
            "           ROUND(control_before, 2)  AS control_spend_before,\n"
            "           ROUND(baseline_ratio, 1)  AS ratio,\n"
            "           ROUND(effect_per_week, 2) AS naive_effect,\n"
            "           pre_trend_passes\n"
            "    FROM mart.campaign_effect ORDER BY baseline_ratio DESC\n"
            '""")'
        ),
        md(
            "### Between four and ten times\n"
            "\n"
            "The treated households spend **$44 to $100 a week**. The comparison group spends\n"
            "**$8 to $14**. The average ratio is **7.0x**.\n"
            "\n"
            "Dunnhumby targeted these campaigns at their heaviest shoppers. The 916 households\n"
            "who received nothing are not a control group - they are a different population.\n"
            "\n"
            "And a group averaging $10 a week has so little variance that its slope will look\n"
            "parallel to almost anything. **That is why the test passed.** It was not wrong; it\n"
            "was answering a question about slopes while the problem was about comparability.\n"
            "\n"
            "What the naive estimate measured was heavy shoppers reverting toward their own\n"
            "mean, with the campaign happening to sit at the peak.\n"
        ),
        conclusion(
            "A diagnostic that passes is not evidence the design is sound - only that one "
            "specific failure did not occur. The habit worth taking from this is to look at "
            "the levels of both groups before trusting any difference between them."
        ),
    ]

    # ---------------------------------------------------------------- PART 9
    cells += [
        section(
            "Part 9", "Matching, and what it costs",
            "**The fix.** Build a comparison group that starts from the same place: for each\n"
            "treated household, find a never-treated household with similar pre-period weekly\n"
            "spend, inside a caliper of 0.25 standard deviations.\n"
            "\n"
            "Treated households with no control inside the caliper are **dropped**, and the\n"
            "number dropped is reported - it measures how far outside the comparison group's\n"
            "range the targeting went.",
            "`src/campaign_effect.py` - `match_on_pre_spend()`",
            "`mart.campaign_effect`",
        ),
        code('show_py("campaign_effect.py", "match_on_pre_spend", lines=42)'),
        md("### Did it work? The test is whether the two groups now start level.\n"),
        code(
            'q("""\n'
            "    SELECT campaign_id, campaign_type,\n"
            "           matched_treated_matched  AS treated_kept,\n"
            "           matched_treated_dropped  AS treated_dropped,\n"
            "           matched_controls_used    AS controls_used,\n"
            "           ROUND(matched_treated_before, 2) AS treated_before,\n"
            "           ROUND(matched_control_before, 2) AS control_before,\n"
            "           ROUND(matched_treated_before - matched_control_before, 3) AS balance_gap\n"
            "    FROM mart.campaign_effect ORDER BY campaign_id\n"
            '""")'
        ),
        conclusion(
            "Balance within **$0.22 on bases of $44-76**, against a 7x gap before. The cost is "
            "**612 of 6,407 treated households dropped** for having no comparable control - "
            "9.6%, and the honest measure of how targeted these campaigns were."
        ),
    ]

    # --------------------------------------------------------------- PART 10
    cells += [
        section(
            "Part 10", "The answer, and the bias still in it",
            "Same estimator, same households, same weeks. Only the comparison group changed.",
            "`src/campaign_effect.py`",
            "`mart.campaign_effect`",
        ),
        code(
            'q("""\n'
            "    SELECT campaign_id, campaign_type,\n"
            "           ROUND(effect_per_week, 2)          AS naive_effect,\n"
            "           ROUND(effect_t, 2)                 AS naive_t,\n"
            "           ROUND(matched_effect_per_week, 2)  AS matched_effect,\n"
            "           ROUND(matched_effect_t, 2)         AS matched_t,\n"
            "           ROUND(matched_effect_pct, 1)       AS matched_pct_of_baseline\n"
            "    FROM mart.campaign_effect ORDER BY matched_effect_pct DESC\n"
            '""")'
        ),
        code(
            'q("""\n'
            "    SELECT COUNT(*) FILTER (WHERE effect_per_week < 0)        AS naive_negative,\n"
            "           COUNT(*) FILTER (WHERE effect_t < -2)              AS naive_sig_negative,\n"
            "           COUNT(*) FILTER (WHERE matched_effect_per_week > 0) AS matched_positive,\n"
            "           COUNT(*) FILTER (WHERE matched_effect_t > 2)       AS matched_sig_positive,\n"
            "           ROUND(quantile_cont(matched_effect_pct, 0.5), 1)   AS median_pct_lift\n"
            "    FROM mart.campaign_effect\n"
            '""")'
        ),
        md(
            "### Every sign flips\n"
            "\n"
            "| | Naive | Matched |\n"
            "|---|---|---|\n"
            "| Negative effects | **12 of 17** | 0 |\n"
            "| Significantly negative | **6** | 0 |\n"
            "| Significantly positive | 0 | **13** |\n"
            "| Median effect | negative | **+23.7% of baseline** |\n"
            "\n"
            "### What I would still not claim\n"
            "\n"
            "**Matching fixes selection on what you can see.** It does nothing about selection\n"
            "on what you cannot.\n"
            "\n"
            "And there is a bias running the *other* way that is easy to miss. Matching on a\n"
            "single noisy pre-period measure selects control households who happened to be\n"
            "having a good spell at that level - and they revert **down**, which flatters the\n"
            "treated group.\n"
            "\n"
            "So the naive estimate is biased low and the matched estimate is probably biased\n"
            "high. The true effect is somewhere between them, nearer the matched one.\n"
            "\n"
            "**A randomised holdout would settle it in one campaign**, and that is the\n"
            "recommendation: hold out 10% of the targeted list, send them nothing, and the next\n"
            "campaign answers this question properly instead of by argument.\n"
        ),
        conclusion(
            "The deliverable is not '+23.7%'. It is that the first answer was negative, the "
            "standard check endorsed it, and it took looking at the levels to find out why - "
            "and that the corrected answer still carries a bias in the opposite direction "
            "which only an experiment removes."
        ),
    ]

    cells += [
        md(
            "---\n"
            "\n"
            "## What this project demonstrates\n"
            "\n"
            "| | |\n"
            "|---|---|\n"
            "| **Price economics** | own-price elasticity for 147 categories, with display and mailer lift separated from it rather than absorbed into it |\n"
            "| **Panel econometrics** | two-way fixed effects absorbed by alternating projection, robust standard errors, degrees of freedom charged for every absorbed effect |\n"
            "| **Causal inference** | difference-in-differences, a parallel-trends test, and the recognition that passing it was not enough |\n"
            "| **Diagnosis** | an implausible result traced to its cause rather than reported or discarded |\n"
            "| **Scope discipline** | elasticities labelled as an upper bound, produce flagged as measurement error, both directions of remaining bias stated |\n"
            "\n"
            "### Limitations, stated\n"
            "\n"
            "- Elasticities are an **upper bound on sensitivity**: retailers discount what they\n"
            "  expect to sell, and the controls remove the main channel but not all of it.\n"
            "- Fresh produce elasticities are **measurement error**, not behaviour. Sold by weight.\n"
            "- Two of 147 commodities return a positive sign and are flagged, not reported.\n"
            "- The matched campaign estimate is **probably biased high**, for the reason in Part 10.\n"
            "- Promotion records cover weeks 9-101 of 102, and 43% of product-weeks.\n"
            "- `COUPON_DISC` is excluded from the shelf price. That is a judgement call.\n"
            "\n"
            "---\n"
            "\n"
            "*Assumptions: `docs/assumptions.md` - Method: `docs/method.md`*\n"
        ),
        code('db.close()\nprint("Walkthrough complete.")'),
    ]

    notebook = {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    out = project_root / "notebooks" / "00_walkthrough.ipynb"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(notebook, indent=1, ensure_ascii=False), encoding="utf-8")
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args()
    root = args.project_root.resolve()
    path = build(root)
    count = len(json.loads(path.read_text(encoding="utf-8"))["cells"])
    print(f"{path.relative_to(root)}: {count} cells")


if __name__ == "__main__":
    main()
