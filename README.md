# Dunnhumby — price elasticity and promotion effectiveness

Own-price elasticity for 147 grocery categories, display and mailer lift
estimated alongside it, and a difference-in-differences evaluation of 17 coupon
campaigns against a comparison group that exists in the data.

Two years, 2,500 households, **2.6M transactions**, 92,353 products, 582 stores,
and **36.8M product-store-week promotion records**.

---

## The finding this project is really about

A standard difference-in-differences said the coupon campaigns made households
spend **less**. Six of 17 campaigns showed a statistically significant negative
effect, up to −8.7% of baseline weekly spend.

Coupons do not make people spend less. So the design was wrong, and the job was
to find out how.

| | Naive DiD | After matching |
|---|---|---|
| Campaigns with a negative effect | **12 of 17** | 0 of 17 |
| Significantly negative | **6** | 0 |
| Significantly positive | 0 | **13** |
| Median effect | negative | **+23.7% of baseline** |
| Treated vs control spend before the campaign | **7.0×** | 1.003× |

### The part worth dwelling on

**The parallel-trends test passed for 15 of the 17 campaigns.** The standard
check for a difference-in-differences gave the green light while the comparison
group was spending **one seventh** of what the treated group spent.

That is not a flaw in the test, it is a fact about what it tests. Parallel
trends is a statement about *slopes*. Two groups can move in parallel and still
be incomparable, and a group averaging $10 a week has so little variance that
its slope will look parallel to almost anything.

The diagnostic that caught it was not clever. It was looking at the levels.

| Campaign | Treated spend before | Control spend before | Ratio | Naive effect | Pre-trend test |
|---|---|---|---|---|---|
| 25 (TypeB) | $99.65 | $14.11 | 7.1× | **−8.12** (t = −3.1) | **passes** |
| 23 (TypeB) | $99.95 | $14.30 | 7.0× | **−7.06** (t = −2.6) | **passes** |
| 11 (TypeB) | $79.38 | $9.78 | 8.1× | **−6.87** (t = −3.2) | **passes** |

Dunnhumby targeted these campaigns at their heaviest shoppers. The 916
households who received nothing are a different population, not a control group.
What the naive estimate measured was those heavy shoppers reverting toward their
own mean.

### The fix, and what it cost

Nearest-neighbour matching on pre-period weekly spend, inside a caliper of 0.25
standard deviations. Balance after matching is within **$0.22 on bases of
$44–76** — treated and control now start from the same place.

**612 of 6,407 treated households (9.6%) were dropped** for having no control
inside the caliper. That number is reported rather than absorbed: it is the
measure of how far outside the comparison group's range the targeting went.

| Campaign | Matched treated | Matched control | Effect | t | % of baseline |
|---|---|---|---|---|---|
| 26 (TypeA) | $47.08 | $46.92 | +19.51 | 6.8 | **+41.4%** |
| 30 (TypeA) | $43.76 | $43.66 | +16.80 | 4.2 | **+38.4%** |
| 20 (TypeC) | $64.27 | $64.04 | +23.26 | 4.8 | **+36.2%** |
| 18 (TypeA) | $49.60 | $49.56 | +8.40 | 3.6 | +16.9% |

### What I would still not claim

**Matching fixes selection on what you can see.** It does nothing about
selection on what you cannot.

And there is a bias running the other way that is easy to miss. Matching on a
single noisy pre-period measure selects control households who happened to be
having a good spell at that level — and they revert *down*, which flatters the
treated group. The naive estimate is biased low; the matched estimate is
probably biased high.

The honest reading is that the true effect lies between them, and closer to the
matched one. A randomised holdout would settle it, and that is what should have
been run.

---

## Price elasticity

Estimated per commodity on a product × week panel, with product and week fixed
effects absorbed by alternating-projection demeaning:

```
log(units) = b·log(price) + g·display_intensity + d·mailer_intensity
           + product FE + week FE + e
```

All three in one equation deliberately. Price, display and mailer move together
— a retailer discounts in the same week it features. Estimate price alone and it
absorbs the display effect, and the elasticity comes out too large.

### 147 commodities

| | |
|---|---|
| Elastic (β < −1) | 33 |
| Inelastic (−1 < β < 0) | 112 |
| Wrong sign, flagged not reported | 2 |
| Statistically significant (\|t\| > 2) | **134** |
| Median elasticity | **−0.71** (IQR −0.94 to −0.41) |
| Mean display lift | +7.4% |
| Mean mailer lift | **+42.9%** |

### Most and least price-sensitive

| Commodity | Elasticity | t | Display lift | Mailer lift |
|---|---|---|---|---|
| **BACON** | **−1.77** | −18.7 | +8.9% | **+298.7%** |
| REFRGRATD JUICES | −1.71 | −32.0 | +4.0% | +26.1% |
| PAPER TOWELS | −1.63 | −10.5 | +12.6% | +96.2% |
| HOT DOGS | −1.62 | −21.8 | +16.7% | +79.7% |
| COLD CEREAL | −1.51 | −25.2 | +11.5% | +45.6% |
| SOFT DRINKS | −1.21 | −28.6 | +18.5% | +45.0% |
| BEEF | −0.24 | −9.0 | +37.8% | +160.7% |

**The pattern is the commercial point.** Stockpilable, branded, frequently
promoted goods are elastic — a shopper can buy bacon this week instead of next.
Fresh meat is inelastic on price but moves enormously on the mailer: it is a
traffic driver, bought because the trip happened, not because the price fell.

Those two facts imply opposite promotional strategies, and the model separates
them because display and mailer are in the equation beside price.

### Where I do not trust the estimate

Fresh produce returns elasticities indistinguishable from zero — potatoes
−0.00, apples −0.01, other vegetables −0.01. That is almost certainly
**measurement, not behaviour**: produce is sold by weight, so "units" and
therefore unit price are not comparable between baskets. The filter at 20 units
per line removes the worst of it and does not fix it.

Reported with the flag rather than dropped, because a reader who finds it
themselves will wonder what else was removed.

---

## The identifying assumption, stated

Within a product and a week, the remaining variation in price is assumed
unrelated to demand. **It is not, and the direction is knowable:** retailers
discount what they expect to sell. A product-specific demand spike the retailer
anticipated will be attributed to the price cut.

Every elasticity here should be read as an **upper bound on sensitivity**. The
display and mailer controls remove the main channel through which that
anticipation operates — promotion — but not all of it.

---

## Checks

| Check | Result |
|---|---|
| raw → stg row count | **0 delta** — 2,595,732 in, 2,595,732 out |
| stg → core row count | **0 delta** |
| core → mart revenue ties | **0 delta** — $7,447,281 both sides |
| Lines usable for pricing | 98.4% of rows, 92.4% of revenue |
| Units = 0 | 14,466 rows — no unit price exists. Excluded |
| Units > 20 (weighted/bulk) | 23,445 rows — units not comparable. Excluded |
| Paid value ≤ 0 | 18,850 rows — returns. Excluded from pricing, kept in spend |
| **Retailer discount stored positive** | **36 rows** — a discount that raises the price. Anomaly |
| Shelf price below price paid | 35 rows — impossible. Excluded |
| Promotion coverage | weeks 9–101 of 102; 461,074 of 1,072,295 product-weeks have a record |

---

## The price decomposition

The source does not state it, and everything depends on it.

```
base_value = SALES_VALUE - RETAIL_DISC - COUPON_MATCH_DISC
```

Three discount columns, all stored negative. `RETAIL_DISC` is the retailer's
loyalty discount and `COUPON_MATCH_DISC` is the retailer matching a manufacturer
coupon — both are retailer-funded, so both are added back to recover the shelf
price.

`COUPON_DISC` is **deliberately not added back.** The manufacturer funds it, so
the retailer still receives that money; adding it to the shelf price would
overstate what the shopper was asked to pay. That is a judgement call, and it is
in `docs/assumptions.md` rather than buried in the SQL.

---

## Running it

```bash
python src/run_all.py --source-dir <path-to-dunnhumby-csvs> --project-root .
```

Or stage by stage:

```bash
python src/build_warehouse.py  --source-dir <path> --project-root .
python src/elasticity.py       --project-root .
python src/campaign_effect.py  --project-root .
```

The source CSVs are not in this repository — `causal_data.csv` alone is 664 MB.
Download "The Complete Journey" from Dunnhumby and point `--source-dir` at it.

---

## Layout

```
dunnhumby_pricing/
├── src/
│   ├── build_warehouse.py   # raw -> stg -> core -> mart -> qa
│   ├── elasticity.py        # two-way FE elasticity + promo lift
│   ├── campaign_effect.py   # naive DiD, parallel trends, matched DiD
│   └── run_all.py
├── notebooks/
│   └── 00_walkthrough.ipynb # the whole project, top to bottom
├── docs/
│   ├── assumptions.md
│   └── method.md
└── artifacts/
    └── dunnhumby.duckdb     # rebuilt by the pipeline (git-ignored)
```
