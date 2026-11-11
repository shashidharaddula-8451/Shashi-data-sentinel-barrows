# DataSentinel — Change Log

## Template for each session:
## YYYY-MM-DD — [Session Theme]
## Files changed:
##   filename.py: what changed (surgical description)
## New components added:
## Open items resolved:
## New open items:

---

## 2026-07-30 — Auto-refresh OFF + Spinners + Cost Page

Files changed:
  dashboard.py      : disabled=True on interval, data=True on store,
                      dcc.Loading wraps agent summary + 4 agent sections
  ai_insights.py    : dcc.Loading with custom_spinner replaces dbc.Spinner
  quality_score.py  : disabled=True on interval, data=True on store,
                      dcc.Loading wraps qs-page-content
  status.py         : disabled=True on interval, data=True on store,
                      dcc.Loading wraps status-page-content
  pipeline_health.py: disabled=True on interval, data=True on store,
                      dcc.Loading wraps ph-page-content
  navbar.py         : Added Cost Analysis under Reports dropdown
  cost.py           : NEW FILE — full cost analysis page

New components:
  cost.py — sections: controls, summary cards, daily trend chart,
             efficiency chart, run detail table, assumptions footnote
  App cost sourced from system.billing.usage (3 app IDs)
  Agent cost = duration_seconds/3600 × 4 DBU/hr × $0.30/DBU

Open items resolved:
  None this session

New open items:
  Cost efficiency chart x-axis µ$ display (Plotly tickvals workaround applied)