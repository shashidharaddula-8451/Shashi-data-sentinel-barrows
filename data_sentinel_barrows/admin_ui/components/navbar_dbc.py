# components/navbar_dbc.py  — DBC-based navbar (replaces DMC version)

import dash_bootstrap_components as dbc
from dash import html


_LINK_STYLE = {
    "color": "#C1C2C5", "fontWeight": "600", "fontSize": "14px",
    "textDecoration": "none", "padding": "6px 12px", "borderRadius": "6px",
}
_HL_STYLE = {**_LINK_STYLE, "color": "#87ceeb"}
_DD_ITEM_STYLE = {"color": "#C1C2C5", "fontSize": "13px"}
_DD_HDR_STYLE = {
    "color": "#5C5F66", "fontSize": "11px", "fontWeight": "700",
    "textTransform": "uppercase", "letterSpacing": "0.5px",
}


def _dd_menu(label, items):
    return dbc.DropdownMenu(
        label=label, children=items, nav=True, in_navbar=True,
        toggle_style={"color": "#C1C2C5", "fontWeight": "600", "fontSize": "14px"},
        menu_variant="dark", style={"marginRight": "2px"},
    )


def _dd_item(label, href, icon=None):
    prefix = f"{icon} " if icon else ""
    return dbc.DropdownMenuItem(f"{prefix}{label}", href=href, style=_DD_ITEM_STYLE)


def _dd_header(text):
    return dbc.DropdownMenuItem(text, header=True, style=_DD_HDR_STYLE)


def _dd_divider():
    return dbc.DropdownMenuItem(divider=True)


def create_navbar():
    return dbc.Navbar(
        dbc.Container([
            # Brand
            dbc.NavbarBrand([
                html.Span("\U0001f6e1\ufe0f", style={"fontSize": "22px", "marginRight": "8px"}),
                "DataSentinel",
            ], href="/", style={"fontWeight": "700", "color": "#ffffff", "fontSize": "18px"}),

            dbc.NavbarToggler(id="navbar-toggler"),

            dbc.Collapse(
                dbc.Nav([
                    dbc.NavItem(dbc.NavLink("Dashboard", href="/", style=_LINK_STYLE)),
                    dbc.NavItem(dbc.NavLink("\U0001f5c3️ Control Plane", href="/control-plane", style=_LINK_STYLE)),

                    _dd_menu("\U0001f9d9 Wizards", [
                        _dd_item("Table Onboarding Wizard", "/onboarding", "\U0001f4cb"),
                        _dd_item("Layer Recon Wizard", "/layer-onboarding", "\U0001f517"),
                        _dd_item("Transformation Wizard", "/transformation-onboarding", "\U0001f50d"),
                        _dd_item("Onboarding History", "/onboarding-history", "\U0001f4d6"),
                        _dd_divider(),
                        _dd_item("Threshold Management", "/threshold-wizard", "\u2699\ufe0f"),
                    ]),

                    dbc.NavItem(dbc.NavLink("\U0001f916 AI Insights", href="/ai-insights", style=_HL_STYLE)),
                    dbc.NavItem(dbc.NavLink("\U0001f4ca Quality Score", href="/quality-score", style=_LINK_STYLE)),
                    dbc.NavItem(dbc.NavLink("\U0001f6a6 Status", href="/status", style=_HL_STYLE)),
                    dbc.NavItem(dbc.NavLink("\u26a1 Health", href="/pipeline-health", style=_LINK_STYLE)),

                    _dd_menu("Validation Agent", [
                        _dd_header("Configuration"),
                        _dd_item("Table Registry", "/table-registry"),
                        _dd_item("Column Registry", "/column-registry"),
                        _dd_item("Validations", "/validations"),
                        _dd_item("Baselines", "/baselines"),
                        _dd_item("Baseline Explorer", "/baseline-explorer"),
                        _dd_divider(),
                        _dd_header("Results"),
                        _dd_item("Validation Results", "/validation-results"),
                    ]),

                    _dd_menu("Reconciliation Agent", [
                        _dd_header("Configuration"),
                        _dd_item("Layer Registry", "/layer-registry"),
                        _dd_item("Reconciliation Config", "/recon-config"),
                        _dd_divider(),
                        _dd_header("Results"),
                        _dd_item("Reconciliation Results", "/reconciliation"),
                    ]),

                    _dd_menu("Transformation Agent", [
                        _dd_header("Configuration"),
                        _dd_item("Transformation Registry", "/transformation-registry"),
                        _dd_divider(),
                        _dd_header("Results"),
                        _dd_item("SQL Review", "/sql-review"),
                    ]),

                    _dd_menu("KPI Assurance Agent", [
                        _dd_header("Configuration"),
                        _dd_item("KPI Registry", "/kpi-registry"),
                        _dd_item("KPI Baselines", "/kpi-baselines"),
                        _dd_divider(),
                        _dd_header("Results"),
                        _dd_item("KPI Validation", "/kpi-validation"),
                    ]),

                    _dd_menu("Reports", [
                        _dd_item("Financial Report", "/financial-report", "\U0001f4ca"),
                        _dd_item("Weekly Report", "/weekly-report", "\U0001f4c8"),
                        _dd_item("Investigation", "/sentinel-investigation", "\U0001f50d"),
                        _dd_divider(),
                        _dd_item("Cost Analysis", "/cost", "\U0001f4b0"),
                    ]),

                    dbc.NavItem(dbc.NavLink("\U0001f4d6 Guide", href="/user-guide", style=_HL_STYLE)),

                    dbc.NavItem(
                        dbc.Button(
                            "☰ Try Sidebar Menu",
                            id="toggle-to-vertical-btn",
                            size="sm",
                            outline=True,
                            color="secondary",
                            className="ms-2",
                        )
                    ),
                ], navbar=True),
                id="navbar-collapse", navbar=True,
            ),
        ], fluid=True),
        color="#1A1B1E", dark=True, sticky="top",
        style={"borderBottom": "1px solid #373A40", "zIndex": 1000, "padding": "4px 0"},
    )
