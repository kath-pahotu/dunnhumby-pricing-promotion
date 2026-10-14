# Assumptions

Every choice this project made that the data did not make for it, and what
happens to the conclusion if it is wrong.

---

## 1 · The shelf price excludes the manufacturer coupon

```sql
base_value = SALES_VALUE - RETAIL_DISC - COUPON_MATCH_DISC
```

`COUPON_DISC` — the manufacturer's coupon — is **not** added back.

**Reasoning.** The shelf price is what a shopper with no card and no coupon
would have been asked to pay. A manufacturer coupon is funded by the
manufacturer, so the retailer receives that money either way; adding it to the
shelf price would overstate the price the shopper faced.

**If it is wrong.** Shelf prices are understated on coupon transactions, so the
measured discount depth is too small and elasticities are biased *toward* zero
on heavily couponed categories. Coupon transactions are a small share of lines,
so the effect is limited, but it is not zero.

**What would settle it.** Nothing in this data. The dataset does not record a
posted price.

---

## 2 · Lines above 20 units are excluded from pricing

Median quantity is 1, the 99th percentile is 10, the 99.9th is 16,944, and the
maximum is 89,638. Those tails are produce sold by weight and bulk items where
"units" is not a comparable quantity and a unit price is meaningless.

**23,445 of 2,595,732 lines (0.9%)** are excluded. They are flagged on the row
via `usable_for_pricing` rather than filtered in a `WHERE` clause, so the
exclusion stays countable.

**It does not fully work.** Fresh produce still returns elasticities
indistinguishable from zero — potatoes −0.00, apples −0.01. Those are reported
with a caveat rather than dropped, because they are measurement error and a
reader should see that they were looked at.

---

## 3 · The identifying assumption for elasticity

Within a product and a week, the remaining variation in price is assumed
unrelated to demand.

**It is not, and the direction is knowable.** Retailers discount what they
expect to sell. A product-specific demand spike the retailer anticipated and
priced into will be attributed to the price cut.

| | |
|---|---|
| **Direction of the bias** | elasticities too large in magnitude |
| **How it is reduced** | display and mailer are in the equation. Anticipated demand is usually acted on by promoting, so controlling for promotion removes the main channel |
| **How it is not removed** | any anticipation that did not result in a display or a feature |
| **How to read the output** | every elasticity is an **upper bound on sensitivity** |

**What would settle it.** Randomised price variation, or an instrument —
wholesale cost shocks, competitor pricing. Neither is in this data.

---

## 4 · The campaign comparison group

**The naive version.** Treated households against the 916 who received no
campaign. This is what the data invites, and it is wrong: treated households
spent **7.0× more per week** before the campaign started. Dunnhumby targeted
their heaviest shoppers.

**Why the standard check did not catch it.** Parallel trends is a statement
about slopes. Fifteen of 17 campaigns passed it. A group averaging $10 a week
has so little variance that its slope looks parallel to almost anything.

**The matched version.** Nearest-neighbour on pre-period weekly spend, caliper
0.25 standard deviations, matching with replacement. Balance after matching is
within $0.22 on bases of $44–76.

| Choice | Value | If it is wrong |
|---|---|---|
| Caliper | 0.25 SD | Wider keeps more treated households at worse balance; narrower drops more. At 0.25 the balance gap is $0.22 |
| Matching variable | pre-period mean weekly spend | A richer vector — frequency, basket size, demographics — would match better. Only 801 of 2,500 households have demographics, so it would shrink the sample |
| Pre/post window | 8 weeks each | Shorter is noisier; longer overlaps neighbouring campaigns, of which there are 30 |
| Matching with replacement | yes | The control pool is 916. Without replacement the match quality would collapse. Effective sample size is used in the standard error so reuse does not inflate precision |

**612 of 6,407 treated households (9.6%) are dropped** for having no control
inside the caliper. That is the honest measure of how far outside the
comparison group's range the targeting went.

---

## 5 · The bias that remains after matching, in the other direction

This is the one most easily missed, and it is why the headline number is not
presented as the answer.

Matching on a **single noisy pre-period measure** selects control households who
happened to be having a good spell at that spend level. They revert *down* over
the following weeks, which flatters the treated group.

| | |
|---|---|
| Naive estimate | biased **low** — treated are at a transient peak and revert |
| Matched estimate | biased **high** — matched controls are at a transient peak and revert |
| Honest reading | the true effect is between them, nearer the matched one |

**What would settle it.** A randomised holdout: 10% of the targeted list
receives nothing. One campaign run that way answers this properly, and it costs
10% of one campaign's coupons.

---

## 6 · Promotion intensity is a share, not a flag

`causal_data` is delivered at product × store × week. Prices and units in the
mart are at product × week, so promotion is collapsed to the **share of stores
running each mechanic**.

A product on display in 300 of 500 stores gets `display_intensity = 0.6`. The
coefficient is therefore the lift at *full* coverage, and `exp(g) − 1` reads as
"what display would do if every store ran it".

**The gap.** Promotion records cover weeks 9–101 of 102, and 461,074 of
1,072,295 product-weeks. Product-weeks with no record are treated as having no
promotion, which is right for most of them and wrong for any that fell outside
the file's coverage. Weeks 1–8 and 102 should be read with that in mind.

---

## 7 · What would change the conclusions

In order of how much.

1. **A randomised holdout on one campaign.** Converts the campaign effect from
   an argument about bias into a measurement.
2. **An instrument for price** — wholesale cost, competitor price. Converts
   elasticity from an upper bound into an estimate.
3. **Weight data for produce.** Would make the fresh categories estimable
   instead of excluded.
4. **A richer matching vector.** Demographics exist for 801 of 2,500
   households; a demographic match on that subset would be a useful robustness
   check on the 23.7% figure.
