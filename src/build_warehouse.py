"""Build the warehouse from the eight Dunnhumby source files.

LAYERS
------
    raw    the CSVs, read as delivered, nothing cast or renamed
    stg    types, names, and the price decomposition - no filtering
    core   the conformed model: one fact at transaction-line grain, one
           promotion fact at product x week, dimensions beside them
    mart   one table per question
    qa     what was checked, and what it found

The layer contract: stg may not lose a row, core may not change the row count
of the fact it is built from, and mart may not introduce a number that cannot
be derived from core.

THE PRICE DECOMPOSITION
-----------------------
This is the part everything else depends on, and the source does not state it.
Three discount columns, all stored negative:

    RETAIL_DISC          the retailer's own loyalty-card discount
    COUPON_DISC          a manufacturer coupon - the manufacturer funds this
    COUPON_MATCH_DISC    the retailer matching a manufacturer coupon

The shelf price is what the customer would have paid with no card and no
coupon, so the two RETAILER-funded discounts are added back:

    base_value = SALES_VALUE - RETAIL_DISC - COUPON_MATCH_DISC

COUPON_DISC is deliberately NOT added back. The manufacturer funds it, so the
retailer still receives that money; adding it to the shelf price would overstate
what the shopper was asked to pay. This is a judgement call and it is stated in
docs/assumptions.md rather than buried here.

Run:
    python src/build_warehouse.py --source-dir <path-to-dunnhumby-csvs> --project-root .
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb

SOURCES = [
    "transaction_data", "product", "hh_demographic",
    "campaign_table", "campaign_desc", "coupon", "coupon_redempt", "causal_data",
]

# Quantities above this are weighted or bulk items - produce sold by the pound,
# a case of water - where "units" is not a comparable quantity and a unit price
# is meaningless. The 99th percentile is 10 and the maximum is 89,638.
MAX_UNITS_PER_LINE = 20


def build(connection, source_dir: Path) -> None:
    for schema in ("raw", "stg", "core", "mart", "qa"):
        connection.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")

    # ------------------------------------------------------------------ raw
    for name in SOURCES:
        path = (source_dir / f"{name}.csv").as_posix()
        connection.execute(
            f"CREATE OR REPLACE VIEW raw.{name} AS SELECT * FROM read_csv_auto('{path}')"
        )

    # ------------------------------------------------------------------ stg
    connection.execute(
        """
        CREATE OR REPLACE VIEW stg.transactions AS
        SELECT
            household_key                        AS household_id,
            BASKET_ID                            AS basket_id,
            PRODUCT_ID                           AS product_id,
            STORE_ID                             AS store_id,
            DAY                                  AS day_number,
            WEEK_NO                              AS week_number,
            QUANTITY                             AS units,
            SALES_VALUE                          AS paid_value,
            RETAIL_DISC                          AS retailer_discount,
            COUPON_DISC                          AS manufacturer_coupon,
            COUPON_MATCH_DISC                    AS retailer_coupon_match,
            -- Shelf value: add back only the discounts the RETAILER funded.
            SALES_VALUE - RETAIL_DISC - COUPON_MATCH_DISC AS base_value
        FROM raw.transaction_data
        """
    )
    connection.execute(
        """
        CREATE OR REPLACE VIEW stg.products AS
        SELECT
            PRODUCT_ID            AS product_id,
            MANUFACTURER          AS manufacturer_id,
            NULLIF(TRIM(DEPARTMENT), '')         AS department,
            NULLIF(TRIM(BRAND), '')              AS brand_tier,
            NULLIF(TRIM(COMMODITY_DESC), '')     AS commodity,
            NULLIF(TRIM(SUB_COMMODITY_DESC), '') AS sub_commodity,
            NULLIF(TRIM(CURR_SIZE_OF_PRODUCT), '') AS pack_size
        FROM raw.product
        """
    )
    connection.execute(
        """
        CREATE OR REPLACE VIEW stg.promotion AS
        SELECT PRODUCT_ID AS product_id, STORE_ID AS store_id, WEEK_NO AS week_number,
               TRIM(display) AS display_code, TRIM(mailer) AS mailer_code
        FROM raw.causal_data
        """
    )
    connection.execute(
        """
        CREATE OR REPLACE VIEW stg.campaign_household AS
        SELECT household_key AS household_id, CAMPAIGN AS campaign_id,
               TRIM(DESCRIPTION) AS campaign_type
        FROM raw.campaign_table
        """
    )
    connection.execute(
        """
        CREATE OR REPLACE VIEW stg.campaign AS
        SELECT CAMPAIGN AS campaign_id, TRIM(DESCRIPTION) AS campaign_type,
               START_DAY AS start_day, END_DAY AS end_day
        FROM raw.campaign_desc
        """
    )

    # ----------------------------------------------------------------- core
    connection.execute("CREATE OR REPLACE TABLE core.dim_product AS SELECT * FROM stg.products")

    connection.execute(
        f"""
        CREATE OR REPLACE TABLE core.fact_sale AS
        SELECT
            t.*,
            t.paid_value / NULLIF(t.units, 0)  AS unit_paid_price,
            t.base_value / NULLIF(t.units, 0)  AS unit_base_price,
            CASE WHEN t.base_value > 0
                 THEN 1 - (t.paid_value / t.base_value) END AS discount_depth,
            -- Rows a price analysis can actually use. Flagged rather than
            -- filtered, so the exclusions stay countable.
            (t.units BETWEEN 1 AND {MAX_UNITS_PER_LINE}
             AND t.paid_value > 0
             AND t.base_value > 0
             AND t.base_value >= t.paid_value)             AS usable_for_pricing
        FROM stg.transactions t
        """
    )

    # Promotion is delivered at product x store x week. Prices and units in the
    # mart are at product x week, so promotion is collapsed to the share of
    # stores running each mechanic - an intensity, not a flag.
    connection.execute(
        """
        CREATE OR REPLACE TABLE core.fact_promotion AS
        SELECT
            product_id,
            week_number,
            COUNT(*)                                                   AS store_weeks,
            COUNT(*) FILTER (WHERE display_code <> '0')                AS display_store_weeks,
            COUNT(*) FILTER (WHERE mailer_code  <> '0')                AS mailer_store_weeks,
            COUNT(*) FILTER (WHERE display_code IN ('1','3','4','5','6','9'))
                                                                        AS feature_display_store_weeks,
            COUNT(*) FILTER (WHERE mailer_code IN ('D','H','Z'))       AS front_page_store_weeks,
            COUNT(*) FILTER (WHERE display_code <> '0')::DOUBLE / COUNT(*) AS display_intensity,
            COUNT(*) FILTER (WHERE mailer_code  <> '0')::DOUBLE / COUNT(*) AS mailer_intensity
        FROM stg.promotion
        GROUP BY product_id, week_number
        """
    )

    # ----------------------------------------------------------------- mart
    connection.execute(
        """
        CREATE OR REPLACE TABLE mart.product_week AS
        SELECT
            s.product_id,
            s.week_number,
            p.department,
            p.commodity,
            p.brand_tier,
            COUNT(*)                                   AS lines,
            COUNT(DISTINCT s.household_id)             AS households,
            SUM(s.units)                               AS units,
            SUM(s.paid_value)                          AS revenue,
            SUM(s.base_value)                          AS base_revenue,
            SUM(s.paid_value) / NULLIF(SUM(s.units), 0) AS unit_paid_price,
            SUM(s.base_value) / NULLIF(SUM(s.units), 0) AS unit_base_price,
            1 - SUM(s.paid_value) / NULLIF(SUM(s.base_value), 0) AS discount_depth,
            COALESCE(f.display_intensity, 0)           AS display_intensity,
            COALESCE(f.mailer_intensity, 0)            AS mailer_intensity,
            f.store_weeks IS NOT NULL                  AS has_promotion_record
        FROM core.fact_sale s
        JOIN core.dim_product p USING (product_id)
        LEFT JOIN core.fact_promotion f
               ON f.product_id = s.product_id AND f.week_number = s.week_number
        WHERE s.usable_for_pricing
        GROUP BY s.product_id, s.week_number, p.department, p.commodity, p.brand_tier,
                 f.display_intensity, f.mailer_intensity, f.store_weeks
        """
    )

    connection.execute(
        """
        CREATE OR REPLACE TABLE mart.household_week AS
        SELECT
            household_id,
            week_number,
            COUNT(DISTINCT basket_id)                  AS baskets,
            SUM(paid_value)                            AS spend,
            SUM(base_value)                            AS base_spend,
            SUM(-retailer_discount)                    AS retailer_discount,
            SUM(-manufacturer_coupon)                  AS manufacturer_coupon,
            SUM(units)                                 AS units
        FROM core.fact_sale
        GROUP BY household_id, week_number
        """
    )


def build_qa(connection) -> None:
    """Everything checked before a price or a lift is quoted."""
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE qa.source_quality AS
        SELECT 'units is zero' AS issue,
               COUNT(*) FILTER (WHERE units = 0) AS rows_affected,
               COUNT(*) AS rows_total,
               'A line with no units has no unit price. Excluded.' AS treatment
        FROM stg.transactions
        UNION ALL
        SELECT 'units above {MAX_UNITS_PER_LINE} (weighted or bulk)',
               COUNT(*) FILTER (WHERE units > {MAX_UNITS_PER_LINE}), COUNT(*),
               'Produce sold by weight. Units are not comparable. Excluded.'
        FROM stg.transactions
        UNION ALL
        SELECT 'paid value not positive',
               COUNT(*) FILTER (WHERE paid_value <= 0), COUNT(*),
               'Returns and adjustments. Excluded from pricing, kept in spend.'
        FROM stg.transactions
        UNION ALL
        SELECT 'retailer discount stored POSITIVE',
               COUNT(*) FILTER (WHERE retailer_discount > 0), COUNT(*),
               'A discount that raises the price. Anomaly - see assumptions.'
        FROM stg.transactions
        UNION ALL
        SELECT 'base value below paid value',
               COUNT(*) FILTER (WHERE base_value < paid_value), COUNT(*),
               'Shelf price below what was paid. Impossible. Excluded.'
        FROM stg.transactions
        """
    )
    connection.execute(
        """
        CREATE OR REPLACE TABLE qa.layer_contract AS
        SELECT 'raw -> stg: transactions' AS step,
               (SELECT COUNT(*) FROM raw.transaction_data) AS rows_in,
               (SELECT COUNT(*) FROM stg.transactions)     AS rows_out,
               (SELECT COUNT(*) FROM stg.transactions)
                 - (SELECT COUNT(*) FROM raw.transaction_data) AS delta
        UNION ALL
        SELECT 'stg -> core: fact_sale',
               (SELECT COUNT(*) FROM stg.transactions),
               (SELECT COUNT(*) FROM core.fact_sale),
               (SELECT COUNT(*) FROM core.fact_sale) - (SELECT COUNT(*) FROM stg.transactions)
        UNION ALL
        SELECT 'core -> mart: revenue ties',
               CAST(ROUND((SELECT SUM(paid_value) FROM core.fact_sale
                           WHERE usable_for_pricing)) AS BIGINT),
               CAST(ROUND((SELECT SUM(revenue) FROM mart.product_week)) AS BIGINT),
               CAST(ROUND((SELECT SUM(revenue) FROM mart.product_week)
                        - (SELECT SUM(paid_value) FROM core.fact_sale
                           WHERE usable_for_pricing)) AS BIGINT)
        """
    )
    connection.execute(
        """
        CREATE OR REPLACE TABLE qa.promotion_coverage AS
        SELECT
            (SELECT MIN(week_number) FROM core.fact_sale)      AS sales_first_week,
            (SELECT MAX(week_number) FROM core.fact_sale)      AS sales_last_week,
            (SELECT MIN(week_number) FROM core.fact_promotion) AS promo_first_week,
            (SELECT MAX(week_number) FROM core.fact_promotion) AS promo_last_week,
            (SELECT COUNT(*) FROM mart.product_week WHERE has_promotion_record) AS weeks_with_promo_record,
            (SELECT COUNT(*) FROM mart.product_week)           AS product_weeks_total
        """
    )


def run(project_root: Path, source_dir: Path) -> dict[str, int]:
    database = project_root / "artifacts" / "dunnhumby.duckdb"
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(database))
    try:
        build(connection, source_dir)
        build_qa(connection)
        tables = connection.execute(
            """
            SELECT schema_name || '.' || table_name AS name FROM duckdb_tables()
            WHERE schema_name IN ('core', 'mart', 'qa') ORDER BY 1
            """
        ).fetchall()
        counts = {
            name: connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            for (name,) in tables
        }
    finally:
        connection.close()
    return counts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument(
        "--project-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args()
    counts = run(args.project_root.resolve(), args.source_dir.resolve())
    width = max(len(name) for name in counts)
    for name, rows in counts.items():
        print(f"{name:<{width}}  {rows:>10,} rows")


if __name__ == "__main__":
    main()
