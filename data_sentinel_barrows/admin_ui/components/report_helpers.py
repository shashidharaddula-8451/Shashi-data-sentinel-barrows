# components/report_helpers.py
"""
Shared formatting helpers for financial and weekly report pages.
Used by financial_report.py and weekly_report.py.
"""

import re
from dash import html


def format_ai_explanation(ai_text: str) -> html.Div:
    """
    Formats AI explanation text as structured bullet points.
    Splits on sentence boundaries and groups into findings
    and summary sections.
    """
    if not ai_text or not ai_text.strip():
        return html.Div()

    sentences = [
        s.strip()
        for s in re.split(r'(?<=[.!?])\s+', ai_text.strip())
        if s.strip() and len(s.strip()) > 15
    ]

    date_bullets    = []
    summary_bullets = []

    for sentence in sentences:
        lower = sentence.lower()
        if (
            lower.startswith("on 2026") or
            lower.startswith("both issues") or
            lower.startswith("both days")
        ):
            date_bullets.append(sentence)
        else:
            summary_bullets.append(sentence)

    elements = []

    if date_bullets:
        elements.append(
            html.Div(
                "What was found:",
                style={
                    "color"        : "#64748b",
                    "fontSize"     : "11px",
                    "fontWeight"   : "700",
                    "textTransform": "uppercase",
                    "letterSpacing": "0.5px",
                    "marginBottom" : "8px",
                }
            )
        )
        for bullet in date_bullets:
            elements.append(
                html.Div([
                    html.Span(
                        "→ ",
                        style={
                            "color"      : "#4a9edd",
                            "fontWeight" : "700",
                            "marginRight": "6px",
                        }
                    ),
                    html.Span(
                        bullet,
                        style={
                            "color"     : "#94a3b8",
                            "fontSize"  : "13px",
                            "lineHeight": "1.6",
                        }
                    ),
                ], style={"marginBottom": "8px", "paddingLeft": "4px"})
            )

    if summary_bullets:
        if date_bullets:
            elements.append(
                html.Hr(style={
                    "borderColor": "#1e3a5f",
                    "margin"     : "10px 0"
                })
            )
        for bullet in summary_bullets:
            elements.append(
                html.Div([
                    html.Span(
                        "▸ ",
                        style={
                            "color"      : "#ffa500",
                            "fontWeight" : "700",
                            "marginRight": "6px",
                        }
                    ),
                    html.Span(
                        bullet,
                        style={
                            "color"     : "#cbd5e1",
                            "fontSize"  : "13px",
                            "lineHeight": "1.6",
                        }
                    ),
                ], style={"marginBottom": "6px", "paddingLeft": "4px"})
            )

    return html.Div(elements)


def format_analyst_body(sentences_or_text) -> html.Div:
    """
    Formats analyst body text as readable structured paragraphs.
    Accepts either a list of sentences or a single string.
    First sentence is rendered larger as the opening observation.
    """
    if isinstance(sentences_or_text, str):
        sentences = [
            s.strip()
            for s in re.split(
                r'(?<=[.!?])\s+', sentences_or_text.strip()
            )
            if s.strip() and len(s.strip()) > 10
        ]
    else:
        sentences = [
            s.strip()
            for s in sentences_or_text
            if s and s.strip()
        ]

    elements = []
    for i, sentence in enumerate(sentences):
        if i == 0:
            elements.append(
                html.P(
                    sentence,
                    style={
                        "color"       : "#ffffff",
                        "fontSize"    : "15px",
                        "fontWeight"  : "500",
                        "marginBottom": "10px",
                        "lineHeight"  : "1.6",
                    }
                )
            )
        else:
            elements.append(
                html.P(
                    sentence,
                    style={
                        "color"       : "#cbd5e1",
                        "fontSize"    : "14px",
                        "marginBottom": "8px",
                        "lineHeight"  : "1.7",
                    }
                )
            )

    return html.Div(elements)


def format_missed(missed_text) -> html.Div:
    """
    Formats 'what they missed' text as bullet points.
    Accepts either a list of bullet strings or a single string.
    """
    if isinstance(missed_text, list):
        bullets = [b.strip() for b in missed_text if b and b.strip()]
    else:
        bullets = [
            s.strip()
            for s in re.split(
                r'(?<=[.!?])\s+', str(missed_text).strip()
            )
            if s.strip() and len(s.strip()) > 10
        ]

    return html.Div([
        html.Div([
            html.Span(
                "• ",
                style={
                    "color"      : "#ff6b6b",
                    "fontWeight" : "700",
                    "marginRight": "6px",
                }
            ),
            html.Span(
                bullet,
                style={
                    "color"     : "#94a3b8",
                    "fontSize"  : "13px",
                    "lineHeight": "1.6",
                }
            ),
        ], style={"marginBottom": "6px", "paddingLeft": "4px"})
        for bullet in bullets
    ])