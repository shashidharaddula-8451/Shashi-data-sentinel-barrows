# pages/user_guide.py

import dash
from dash import html
import dash_bootstrap_components as dbc

dash.register_page(
    __name__,
    path = "/user-guide",
    name = "User Guide"
)

layout = html.Div([

    # Full-height iframe serving the static HTML file
    html.Iframe(
        src   = "/assets/datasentinel_user_guide.html",
        style = {
            "width"       : "100%",
            "height"      : "100vh",
            "border"      : "none",
            "display"     : "block",
            "marginTop"   : "-16px",   # remove container top gap
        }
    )

], style={
    "margin"  : "0",
    "padding" : "0",
    "overflow": "hidden",
})