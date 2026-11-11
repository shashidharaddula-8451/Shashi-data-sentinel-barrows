# DataSentinel — Compact Context Document
# Last Updated: 2026-07-30
# Purpose: Paste this at the start of every new chat session

═══════════════════════════════════════════════════════════
SECTION 1: PROJECT IDENTITY
═══════════════════════════════════════════════════════════

Project Name    : DataSentinel
Type            : Four-agent AI-assisted data quality platform
Principle       : Deterministic checks find problems. AI explains them.
                  Never the other way around.

Stack:
  UI Framework  : Python/Dash with DARKLY Bootstrap theme
  Deployment    : Databricks Apps
  Entry Point   : admin_ui/app.py
  AI Model      : databricks-gpt-oss-20b
                  max_tokens=8192, temperature=0.1 (agents) 0.2 (insights)
                  timeout=180s
                  CRITICAL: returns content as list of blocks not string
                  Use extract_content_from_response() in all notebooks

Infrastructure:
  Host          : https://adb-8005091109336306.6.azuredatabricks.net
  Catalog       : learning_dev
  Schema        : s115118
  Cluster       : 0220-160255-4reafcow (Standard_E8as_v4, min1 max8 nodes)
  SQL Warehouse : 18a5ca649627f957
  Serverless    : NOT available
  Cluster create: NOT permitted
  Secret Scope  : agent1-secrets  key=teams-webhook-url
  Teams Channel : platform-support (MessageCard format NOT Adaptive Cards)

═══════════════════════════════════════════════════════════
SECTION 2: FILE STRUCTURE
═══════════════════════════════════════════════════════════

Root: /Users/s115118@8451.com/data_sentinel/

admin_ui/
  app.py
  app.yaml                    ⚠️ PAT token — ROTATE BEFORE DEMO
  requirements.txt
  assets/custom.css           Dark theme + font sizes
  components/
    alerts.py                 All shared functions
    navbar.py
  config/settings.py
  db/connection.py
  db/queries.py
  pages/
    dashboard.py              /
    quality_score.py          /quality-score
    status.py                 /status
    pipeline_health.py        /pipeline-health
    table_registry.py         /table-registry
    column_registry.py        /column-registry
    validations.py            /validations
    baselines.py              /baselines
    validations_results.py    /validation-results
    layer_registry.py         /layer-registry
    recon_config.py           /recon-config
    reconciliation.py         /reconciliation
    sql_review.py             /sql-review
    transformation_registry.py /transformation-registry
    kpi_registry.py           /kpi-registry
    kpi_baselines.py          /kpi-baselines
    kpi_validation.py         /kpi-validation
    ai_insights.py            /ai-insights
    financial_report.py       /financial-report
    weekly_report.py          /weekly-report
    sentinel_investigation.py /sentinel-investigation
    baseline_explorer.py      /baseline-explorer
    cost.py                   /cost
    debug.py                  /debug

agent1/pipeline/
  01_baseline_computation
  02_validation_agent
  03_ai_summarization
  04_teams_alert_dispatcher

agent2/pipeline/
  01_reconciliation_agent
  02_ai_summarization
  03_alert_dispatcher

agent3/pipeline/
  01_sql_review_agent         ⚠️ does not write business_date yet
  02_alert_dispatcher

agent4/pipeline/
  01_kpi_baseline_computation
  02_kpi_validation_agent
  03_ai_summarization
  04_teams_alert_dispatcher

═══════════════════════════════════════════════════════════
SECTION 3: NAVBAR STRUCTURE
═══════════════════════════════════════════════════════════

Dashboard
Agent 1 ▾   Table Registry | Column Registry | Validations | Baselines | ─ | Validation Results
Agent 2 ▾   Layer Registry | Reconciliation Config | Reconciliation Results
Agent 3 ▾   Transformation Registry | SQL Review
Agent 4 ▾   KPI Registry | KPI Baselines | KPI Validation
Reports ▾   Financial Report | Weekly Report | Investigation | ─ | Cost Analysis
🤖 AI Insights
📊 Quality Score
🏥 Pipeline Health
⚡ Platform Status
📖 User Guide

═══════════════════════════════════════════════════════════
SECTION 4: PAGE COMPONENT IDs
═══════════════════════════════════════════════════════════

dashboard.py
  interval  : dashboard-refresh-interval
  store     : db-refresh-paused  (data=True = paused by default)
  toggle    : db-refresh-toggle
  indicator : db-refresh-indicator
  content   : combined-summary-cards, agent1-recent-validations,
              agent2-recent-reconciliations, agent3-recent-reviews,
              agent4-recent-validations
  loading   : dashboard-main-loading

quality_score.py
  interval  : qs-refresh-interval
  store     : qs-refresh-paused  (data=True = paused by default)
  content   : qs-page-content
  loading   : qs-loading

status.py
  interval  : status-refresh-interval
  store     : status-refresh-paused  (data=True = paused by default)
  content   : status-page-content
  loading   : status-loading

pipeline_health.py
  interval  : ph-refresh-interval
  store     : ph-refresh-paused  (data=True = paused by default)
  content   : ph-page-content
  loading   : ph-loading

validations_results.py
  runs table: val-runs-table
  detail    : check-detail-container
  ai panel  : ai-analysis-panel
  header    : check-detail-header
  loading   : val-runs-loading, val-results-loading

reconciliation.py
  runs table: recon-runs-table
  detail    : recon-detail-container
  ai panel  : recon-ai-panel
  header    : recon-detail-header
  loading   : recon-runs-loading, recon-detail-loading

kpi_validation.py
  summary   : agent4-summary-cards
  tabs      : kpi-tabs
  loading   : kpiv-summary-loading, kpiv-tabs-loading

ai_insights.py
  summary   : insights-summary-section
  narrative : insights-narrative-section
  generate  : ai-generate-btn
  date      : ai-date-picker
  loading   : ai-insights-loading, ai-summary-loading

sql_review.py
  history   : review-history-container
  detail    : failed-check-detail-panel
  ai panel  : ai-summary-panel
  header    : review-history-header
  loading   : sqlrev-history-loading, sqlrev-detail-loading

baselines.py
  content   : baselines-table-container
  loading   : baselines-loading

kpi_baselines.py
  summary   : kpi-baselines-summary-cards
  grid      : kpi-baselines-grid-container
  detail    : kpi-baseline-detail-panel
  loading   : kpibl-summary-loading, kpibl-grid-loading, kpibl-detail-loading

cost.py
  date range: cost-date-range
  dbu price : cost-dbu-price
  dbu/hour  : cost-dbu-per-hour
  app/hour  : cost-app-per-hour
  button    : cost-calculate-btn
  alert     : cost-alert
  content   : cost-main-content
  loading   : cost-loading
  presets   : cost-preset-7, cost-preset-30, cost-preset-90

═══════════════════════════════════════════════════════════
SECTION 5: DATABASE TABLES
═══════════════════════════════════════════════════════════

Agent 1 (prefix: uc1_)
  uc1_table_registry
  uc1_column_registry
  uc1_column_validation_registry
  uc1_table_validation_registry
  uc1_baseline_metrics
  uc1_validation_run              partitioned by business_date
  uc1_validation_results          partitioned by business_date

Agent 2 (prefix: uc2_)
  uc2_layer_registry
  uc2_layer_check_config
  uc2_reconciliation_metric_config
  uc2_reconciliation_run          partitioned by business_date
  uc2_reconciliation_results      partitioned by business_date
  uc2_silver_store_transactions   partitioned by transaction_date
  uc2_silver_inventory_movements  partitioned by business_date
  uc2_gold_daily_store_metrics    partitioned by business_date
  uc2_gold_daily_inventory_summary partitioned by business_date

Agent 3 (prefix: uc3_)
  uc3_transformation_registry
  uc3_review_results              ⚠️ business_date column exists but
                                     not written by notebook yet

Agent 4 (prefix: uc4_)
  uc4_kpi_registry
  uc4_kpi_baseline_metrics        baseline_date=2026-06-25
                                  window: 2026-05-19 to 2026-06-19
  uc4_kpi_validation_run          partitioned by business_date
  uc4_kpi_validation_results      partitioned by business_date

Billing (system tables)
  system.billing.usage            used for cost page
  system.billing.list_prices      used for cost page
  App IDs tracked in cost.py:
    8a0ce546-fdb4-4e85-b6b4-427e8bbb3e0d  data-sentinel
    e15a21dc-48c9-4eba-bdcf-3b0ce8a99a74  data-trust-layer-admin-ui
    e6a6665d-48e8-43ba-bd2d-161f2df39725  agent1-admin-ui
  App SKU price: $0.95/DBU
  Jobs SKU price: $0.30/DBU (PREMIUM_JOBS_COMPUTE)
  Jobs DBU rate: 4 DBU/hr (Standard_E8as_v4)

═══════════════════════════════════════════════════════════
SECTION 6: SHARED PATTERNS — CRITICAL
═══════════════════════════════════════════════════════════

Write Pattern (NEVER use saveAsTable):
  df.createOrReplaceTempView("staging")
  spark.sql("""
      INSERT INTO {table}
      SELECT CAST(col AS TYPE), ...
      FROM staging
  """)

Workflow Flag Pattern (NEVER use dbutils.notebook.exit()):
  if not pending_runs:
      NO_PENDING_RUNS = True
  # Later cells check flag and skip

Raw Inventory _rescued_data:
  Use None not "" → None maps to SQL NULL correctly

AI Confidence Threshold:
  Agents 1,2,4: trigger when ≥2 failures AND ≥1 CRITICAL
  Agent 3: trigger when ≥1 failure any level

SQL Quirks:
  Use SUBSTRING_INDEX not SPLIT
  SHOW SCHEMAS → column "databaseName"
  SHOW TABLES  → column "tableName"
  Dash filter_query strings need double quotes: '{col} = "CRITICAL"'

Auto-refresh Default: OFF
  dcc.Interval → disabled=True
  dcc.Store    → data=True (True = paused)
  Toggle callback already handles both directions correctly

Spinner Standard:
  dcc.Loading(type="circle", color="#00c851", children=...)
  AI Insights uses custom_spinner with blur overlay (longer wait)

═══════════════════════════════════════════════════════════
SECTION 7: SHARED COMPONENTS — alerts.py
═══════════════════════════════════════════════════════════

Alert functions:
  success_alert(message)
  error_alert(message)
  warning_alert(message)
  info_alert(message)

Constants:
  STATUS_EMOJI  : CRITICAL=🔴  WARNING=🟡  PASS=🟢  ERROR=⚫
  STATUS_COLOR  : CRITICAL=danger WARNING=warning PASS=success ERROR=secondary
  STATUS_BORDER : CRITICAL=#ff4444 WARNING=#ffa500 PASS=#00c851 ERROR=#555
  STATUS_CODE   : CRITICAL=1 WARNING=2 PASS=3 ERROR=4

Formatting functions:
  fmt_optional(val, decimals=None)     None/nan → "—"
  fmt_number(val)                      20.0→"20"  0.0977→"0.10"
  fmt_deviation(val, check_type="")   signed: -24.45  +455.76
  fmt_threshold(val)                   40.0→"40"  0.5→"0.50"
  compute_signed_deviation(obs, base, check_type)

DataTable pattern (every page):
  1. rows = add_status_code(rows, "status_col")
  2. columns include {"name":"","id":"_status_code","hidden":True}
  3. style_data_conditional = get_status_style_conditions(
         status_col, text_cols, bold_cols)
  4. style_cell_conditional hides _status_code column
  5. style_header_conditional hides _status_code header

Modal functions:
  build_alert_modal(modal_id)
  build_alert_card_body(agent_name, table_name, fqn, business_date,
      status, checks_run, checks_passed, checks_warned, checks_critical,
      failed_checks, ai_summary, ai_action, ai_category, ai_confidence,
      run_id, extra_facts=None)

═══════════════════════════════════════════════════════════
SECTION 8: DEMO SCENARIOS
═══════════════════════════════════════════════════════════

Clean baseline  : 2026-05-19 to 2026-06-17
Demo 1 (06-21)  : Silver bug — null spike net_amount 21.99%
                  A1 CRITICAL txn, A2 CRITICAL survival 69.5%
                  A3 CRITICAL store txn, A4 CRITICAL return_rate
Demo 2 (06-24)  : Formula error — net_qty_change +9999 all rows
Demo 3 (07-19)  : Silent failure — raw txn=0 rows (-100%)
Demo 3 (07-20)  : Partial recovery — raw txn=80 rows (-87.7%)
                  A4 total_net CRITICAL £815.73 vs £5483.11 (-85.12%)

KPI Baselines:
  return_rate        mean=0.0977  stddev=0.0630
  avg_basket_value   mean=220.91  stddev=36.86
  net_quantity_change mean=2323.66 stddev=8375.54
  total_net_amount   mean=5483.11  stddev=1544.83

═══════════════════════════════════════════════════════════
SECTION 9: OPEN ITEMS
═══════════════════════════════════════════════════════════

CRITICAL:
  [ ] Agent 3 (01_sql_review_agent) does not write business_date column
      Fix: add business_date to build_review_record() and write path

KNOWN ISSUES:
  [ ] _status_code empty column header still visible in some tables
  [ ] AI Analysis panel font size CSS not overriding
  [ ] Cost page efficiency chart x-axis µ$ formatting (Plotly version issue)
      Workaround: tickvals/ticktext explicitly set

NOT YET IMPLEMENTED:
  [ ] PARTITION_FRESHNESS check (configured but skipped)
  [ ] DUPLICATE_INGESTION check (configured but skipped)
  [ ] Alert deduplication
  [ ] Alert acknowledgement
  [ ] Threshold management UI
  [ ] Baseline auto-refresh (30-day rolling window)

BEFORE PRODUCTION:
  [ ] Rotate PAT token in app.yaml

DEACTIVATED KPIs:
  kpi-store-003 net_vs_gross_consistency (wrong rule)
  kpi-inv-003   total_cost_impact (baseline unreliable)
  kpi-inv-001   ANOMALY check removed (false positives)

═══════════════════════════════════════════════════════════
SECTION 10: RECENT CHANGES LOG
═══════════════════════════════════════════════════════════

2026-07-30:
  [UI] Auto-refresh defaulted to OFF on all pages with interval
       Affected: dashboard.py, quality_score.py, status.py,
                 pipeline_health.py
       Pattern: disabled=True on Interval, data=True on Store
  [UI] dcc.Loading spinners added (color=#00c851, type=circle)
       Affected: dashboard.py, ai_insights.py, quality_score.py,
                 status.py, pipeline_health.py
  [UI] Cost page added (/cost) under Reports dropdown
       File: pages/cost.py
       Source: duration×DBU rate for agents, system.billing.usage for app
       App IDs: 3 tracked (data-sentinel + 2 previous names)
       App SKU: PREMIUM_ALL_PURPOSE_SERVERLESS_COMPUTE_US_EAST_2 $0.95/DBU
  [UI] Cost efficiency chart x-axis fixed with explicit tickvals/ticktext