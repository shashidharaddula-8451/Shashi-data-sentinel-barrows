CREATE OR REPLACE TABLE learning_dev.s819534.uc2_gold_daily_store_kpis AS
WITH txn_agg AS (
    SELECT
        store_id,
        transaction_date AS business_date,
        COUNT(*) AS transaction_count,
        SUM(gross_amount) AS total_gross_amount,
        SUM(discount_amount) AS total_discount_amount,
        SUM(net_amount) AS total_net_amount
    FROM learning_dev.s819534.uc2_silver_store_transactions
    GROUP BY store_id, transaction_date
),
inv_agg AS (
    -- store_id is only populated on store-attributable events (SALE/TRANSFER/WRITE_OFF/ADJUSTMENT);
    -- warehouse RECEIPT events have store_id = NULL and are excluded (a warehouse serves multiple
    -- stores with no clean per-store allocation, so receipts aren't modeled at this grain).
    SELECT
        store_id,
        business_date,
        SUM(CASE WHEN quantity_change < 0 THEN -quantity_change ELSE 0 END) AS quantity_depleted,
        SUM(total_cost_impact) AS total_inventory_cost_impact
    FROM learning_dev.s819534.uc2_silver_inventory_movements
    WHERE store_id IS NOT NULL
    GROUP BY store_id, business_date
)
SELECT
    COALESCE(t.store_id, i.store_id) AS store_id,
    COALESCE(t.business_date, i.business_date) AS business_date,

    COALESCE(t.transaction_count, 0) AS transaction_count,
    COALESCE(t.total_gross_amount, 0.0) AS total_gross_amount,
    COALESCE(t.total_discount_amount, 0.0) AS total_discount_amount,
    COALESCE(t.total_net_amount, 0.0) AS total_net_amount,

    -- Discount effectiveness: discount as a % of gross sales
    ROUND(
        CASE WHEN t.total_gross_amount > 0
             THEN 100.0 * t.total_discount_amount / t.total_gross_amount
             ELSE 0.0 END,
        2
    ) AS discount_pct_of_gross,

    COALESCE(i.quantity_depleted, 0) AS quantity_depleted,
    COALESCE(i.total_inventory_cost_impact, 0.0) AS total_inventory_cost_impact,

    -- Sales-to-inventory ratio: net sales relative to the cost impact of inventory depleted
    ROUND(
        CASE WHEN i.total_inventory_cost_impact > 0
             THEN t.total_net_amount / i.total_inventory_cost_impact
             ELSE NULL END,
        4
    ) AS sales_to_inventory_ratio,

    CURRENT_TIMESTAMP() AS gold_load_timestamp

FROM txn_agg t
FULL OUTER JOIN inv_agg i
    ON t.store_id = i.store_id AND t.business_date = i.business_date
