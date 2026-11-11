# app.py

import dash
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
import diskcache
from components.navbar_dbc import create_navbar
from components.sidebar import create_sidebar
from config.settings import validate_config
import logging
from dash import html, dcc, Input, Output, State, DiskcacheManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

config_valid = validate_config()

# Backs the wizard "background=True" callbacks (e.g. onboarding execution):
# Databricks Apps' reverse proxy hard-kills any single HTTP request past 120s
# with no way to configure it, so long onboarding runs must execute out of
# request/response cycle. Dash polls job status itself with short requests,
# so no request-level change is needed beyond marking those callbacks
# background=True. /tmp is guaranteed writable in the app container; the
# source code path is not.
background_callback_manager = DiskcacheManager(
    diskcache.Cache("/tmp/data_sentinel_cache")
)

app = dash.Dash(
    __name__,
    use_pages=True,
    external_stylesheets=[
        dbc.themes.DARKLY,
        "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css",
    ],
    suppress_callback_exceptions=True,
    background_callback_manager=background_callback_manager,
)

server = app.server


def get_config_banner():
    if not config_valid:
        return dmc.Alert(
            title="Configuration Warning",
            children=(
                "Database environment variables are not set. "
                "Please configure DATABRICKS_HOST, DATABRICKS_TOKEN, "
                "and DATABRICKS_HTTP_PATH in the Databricks Apps settings."
            ),
            color="yellow",
            variant="filled",
            withCloseButton=True,
            radius=0,
            mb=0,
        )
    return html.Div()


app.layout = dmc.MantineProvider(
    forceColorScheme="dark",
    theme={
        "primaryColor": "blue",
        "fontFamily": "Inter, -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif",
        "colors": {
            "dark": [
                "#C1C2C5", "#A6A7AB", "#909296", "#5C5F66",
                "#373A40", "#2C2E33", "#25262B", "#1A1B1E",
                "#141517", "#101113",
            ],
        },
        "components": {
            "Card": {"defaultProps": {"radius": "md", "withBorder": True}},
            "Button": {"defaultProps": {"radius": "md"}},
            "TextInput": {"defaultProps": {"radius": "md"}},
            "Select": {"defaultProps": {"radius": "md"}},
            "Badge": {"defaultProps": {"radius": "sm"}},
            "Paper": {"defaultProps": {"radius": "md"}},
        },
    },
    children=[
        dcc.Store(id="nav-mode-store", storage_type="local", data="horizontal"),
        dcc.Location(id="app-location", refresh=False),
        html.Div(
            id="app-navbar-container",
            children=[create_navbar()],
        ),
        html.Div(
            [
                html.Div(id="app-sidebar-container", children=[create_sidebar()]),
                html.Div(
                    id="app-page-content",
                    children=[get_config_banner(), dash.page_container],
                ),
            ],
            id="app-shell-body",
        ),
    ]
)


# ── Navbar / sidebar mode switching ─────────────────────────────────────────

@app.callback(
    Output("nav-mode-store", "data"),
    Input("toggle-to-vertical-btn", "n_clicks"),
    Input("toggle-to-horizontal-btn", "n_clicks"),
    prevent_initial_call=True,
)
def switch_nav_mode(_to_vertical, _to_horizontal):
    trigger = dash.ctx.triggered_id
    if trigger == "toggle-to-vertical-btn":
        return "vertical"
    if trigger == "toggle-to-horizontal-btn":
        return "horizontal"
    return dash.no_update


@app.callback(
    Output("app-navbar-container", "style"),
    Output("app-sidebar-container", "style"),
    Output("app-shell-body", "className"),
    Input("app-location", "pathname"),
    Input("nav-mode-store", "data"),
)
def toggle_navbar(pathname, nav_mode):
    """
    Hides the Dash navbar/sidebar on the user guide page because the
    guide has its own sticky sidebar navigation. Otherwise, shows
    exactly one of the navbar/sidebar based on nav_mode.
    """
    if pathname == "/user-guide":
        return {"display": "none"}, {"display": "none"}, "ds-shell-body"

    is_vertical = nav_mode == "vertical"
    navbar_style = {"display": "none"} if is_vertical else {"display": "block"}
    sidebar_style = {"display": "block"} if is_vertical else {"display": "none"}
    body_class = "ds-shell-body ds-shell-vertical" if is_vertical else "ds-shell-body"
    return navbar_style, sidebar_style, body_class


if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=8050)