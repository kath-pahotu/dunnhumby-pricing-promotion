"""Rebuild everything in one command.

    python src/run_all.py --source-dir <path-to-dunnhumby-csvs> --project-root .

Three stages in dependency order, as separate modules so a failure names the
stage it happened in and a single stage can be re-run on its own.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_warehouse  # noqa: E402
import campaign_effect  # noqa: E402
import elasticity  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument(
        "--project-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args()
    root = args.project_root.resolve()
    source = args.source_dir.resolve()

    missing = [
        name for name in build_warehouse.SOURCES
        if not (source / f"{name}.csv").exists()
    ]
    if missing:
        raise SystemExit(
            "Missing source files in " + str(source) + ":\n  " + "\n  ".join(missing)
            + "\n\nDownload 'The Complete Journey' from Dunnhumby. The files are not\n"
            "in this repository - causal_data.csv alone is 664 MB."
        )

    print("1/3  building the warehouse")
    counts = build_warehouse.run(root, source)
    print(f"     {len(counts)} tables, {sum(counts.values()):,} rows")

    print("2/3  estimating elasticity and promotion lift")
    results = elasticity.run(root)
    flagged = int(results["implausible_sign"].sum())
    print(f"     {len(results)} commodities, {flagged} flagged for an implausible sign")

    print("3/3  evaluating campaigns")
    estimates, _ = campaign_effect.run(root)
    passed = int(estimates["interpretable"].sum())
    positive = int((estimates["matched_effect_t"] > 2).sum())
    print(f"     {len(estimates)} campaigns, {passed} pass parallel trends, "
          f"{positive} significantly positive after matching")

    print("\ndone.")


if __name__ == "__main__":
    main()
