"""Render the figures that carry the findings.

Three charts, each one the visual form of a sentence in the README:

    elasticity_by_category   which categories respond to price, and which do not
    price_vs_mailer          the strategy split - elastic goods against traffic
                             drivers - in one view
    campaign_sign_flip       the naive estimate, the matched estimate, and the
                             fact that every sign changes

Colours match the portfolio site so the charts do not look borrowed from
somewhere else when they appear on it.

Run:
    python src/render_figures.py --project-root .
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

NAVY, BLUE, CYAN, ORANGE, MUTED = "#0b2545", "#1268d5", "#22b7c8", "#f47c48", "#64748b"
GRID = "#d6e4f0"

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "axes.edgecolor": GRID, "axes.labelcolor": NAVY, "axes.titlecolor": NAVY,
    "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.spines.top": False, "axes.spines.right": False,
    "figure.facecolor": "white", "axes.facecolor": "white",
})


def save(fig, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  {path.name:<34} {path.stat().st_size / 1024:>5.0f} KB")


def elasticity_by_category(connection, out: Path) -> None:
    frame = connection.execute(
        """
        (SELECT commodity, elasticity FROM mart.price_elasticity
         WHERE revenue > 25000 AND NOT implausible_sign ORDER BY elasticity LIMIT 9)
        UNION ALL
        (SELECT commodity, elasticity FROM mart.price_elasticity
         WHERE revenue > 25000 AND NOT implausible_sign ORDER BY elasticity DESC LIMIT 7)
        """
    ).fetchdf().sort_values("elasticity")

    fig, ax = plt.subplots(figsize=(9.4, 6.2))
    colours = [BLUE if v < -1 else CYAN for v in frame["elasticity"]]
    ax.barh(frame["commodity"], frame["elasticity"], color=colours, height=0.72)
    ax.axvline(-1, color=ORANGE, linestyle="--", linewidth=1.3)
    ax.text(-1.02, len(frame) - 0.4, "elastic  <  -1", color=ORANGE,
            fontsize=9, ha="right", va="center", fontweight="bold")
    for index, value in enumerate(frame["elasticity"]):
        ax.text(value - 0.04, index, f"{value:.2f}", va="center", ha="right",
                fontsize=8.5, color="white" if value < -0.3 else MUTED)
    ax.set_xlabel("Own-price elasticity  (% change in units per 1% change in price)")
    ax.set_title("Price sensitivity is not a property of the shop, it is a property "
                 "of the category\nStockpilable goods respond; staples barely move",
                 loc="left", fontsize=12.5, pad=14)
    ax.set_xlim(frame["elasticity"].min() * 1.18, 0.12)
    ax.grid(axis="x", color=GRID, linewidth=0.7)
    ax.set_axisbelow(True)
    save(fig, out / "elasticity_by_category.png")


def price_vs_mailer(connection, out: Path) -> None:
    frame = connection.execute(
        """
        SELECT commodity, elasticity, mailer_lift_pct, revenue
        FROM mart.price_elasticity
        WHERE revenue > 25000 AND NOT implausible_sign AND mailer_lift_pct < 320
        """
    ).fetchdf()

    fig, ax = plt.subplots(figsize=(9.4, 6.2))
    sizes = 24 + 240 * (frame["revenue"] / frame["revenue"].max())
    ax.scatter(frame["elasticity"], frame["mailer_lift_pct"], s=sizes,
               color=BLUE, alpha=0.5, edgecolor="white", linewidth=0.8)

    ax.axvline(-1, color=GRID, linewidth=1)
    ax.axhline(frame["mailer_lift_pct"].median(), color=GRID, linewidth=1)

    for row in frame.itertuples():
        if row.elasticity < -1.4 or row.mailer_lift_pct > 140 or row.elasticity > -0.2:
            ax.annotate(row.commodity.title(), (row.elasticity, row.mailer_lift_pct),
                        fontsize=7.6, color=NAVY, xytext=(5, 4),
                        textcoords="offset points")

    ax.text(0.02, 0.96, "Traffic drivers\nmove on the ad, not the price",
            transform=ax.transAxes, fontsize=9.4, color=ORANGE, fontweight="bold", va="top")
    ax.text(0.98, 0.04, "Price-led\ndiscount moves volume", transform=ax.transAxes,
            fontsize=9.4, color=BLUE, fontweight="bold", ha="right")

    ax.set_xlabel("Own-price elasticity")
    ax.set_ylabel("Lift from a mailer feature  (%)")
    ax.set_title("Two kinds of category, two opposite promotional strategies\n"
                 "Separable only because price, display and mailer are in the same model",
                 loc="left", fontsize=12.5, pad=14)
    ax.grid(color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    save(fig, out / "price_vs_mailer.png")


def campaign_sign_flip(connection, out: Path) -> None:
    frame = connection.execute(
        """
        SELECT campaign_id, campaign_type, effect_pct_of_baseline AS naive,
               matched_effect_pct AS matched, baseline_ratio
        FROM mart.campaign_effect ORDER BY matched_effect_pct
        """
    ).fetchdf()

    fig, ax = plt.subplots(figsize=(9.4, 6.6))
    y = np.arange(len(frame))

    for index, row in enumerate(frame.itertuples()):
        ax.plot([row.naive, row.matched], [index, index], color=GRID, linewidth=1.6,
                zorder=1, solid_capstyle="round")
    ax.scatter(frame["naive"], y, s=62, color=ORANGE, zorder=3,
               label="Naive — never-treated as the control group", edgecolor="white")
    ax.scatter(frame["matched"], y, s=62, color=BLUE, zorder=3,
               label="Matched on pre-period spend", edgecolor="white")

    ax.axvline(0, color=NAVY, linewidth=1.2)
    ax.set_yticks(y)
    ax.set_yticklabels([f"{r.campaign_type}  #{r.campaign_id}" for r in frame.itertuples()],
                       fontsize=8.6)
    ax.set_xlabel("Effect on weekly household spend  (% of baseline)")
    ax.set_title("Every sign flips once the comparison group starts from the same place\n"
                 "The parallel-trends test passed on 15 of 17 of these",
                 loc="left", fontsize=12.5, pad=14)
    ax.legend(frameon=False, fontsize=9.2, loc="lower right")
    ax.grid(axis="x", color=GRID, linewidth=0.7)
    ax.set_axisbelow(True)
    save(fig, out / "campaign_sign_flip.png")


def run(project_root: Path) -> None:
    connection = duckdb.connect(
        str(project_root / "artifacts" / "dunnhumby.duckdb"), read_only=True
    )
    out = project_root / "artifacts" / "figures"
    try:
        elasticity_by_category(connection, out)
        price_vs_mailer(connection, out)
        campaign_sign_flip(connection, out)
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args()
    run(args.project_root.resolve())


if __name__ == "__main__":
    main()
