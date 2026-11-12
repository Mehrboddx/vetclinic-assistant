"""Altair charts following one spec: 2px lines, >=8px ringed markers, recessive axes, hover tooltips.

Colors are slots 1-2 of the reference categorical palette (validated all-pairs in light and dark).
Axis/label text is left to the Streamlit theme so it follows light/dark mode.
"""

import altair as alt
import pandas as pd

SERIES_1 = "#2a78d6"  # blue
SERIES_2 = "#eb6834"  # orange
GRID = "#e1e0d9"


def _base(chart: alt.Chart, height: int) -> alt.Chart:
    return (
        chart.properties(height=height)
        .configure_axis(gridColor=GRID, gridOpacity=0.6, domain=False, tickColor=GRID, labelFontSize=11,
                        titleFontWeight="normal")
        .configure_view(strokeWidth=0)
        .configure_legend(orient="top", title=None, symbolType="stroke", symbolStrokeWidth=3)
    )


def trend_chart(df: pd.DataFrame, value: str, title: str, unit: str = "", height: int = 220,
                ring: str = "white") -> alt.Chart:
    """Single-series line over time. `df` has columns date (datetime), jalali (label), and `value`."""
    y_title = f"{title} ({unit})" if unit else title
    x = alt.X("date:T", title=None, axis=alt.Axis(format="%Y-%m-%d", labelAngle=0, tickCount=6))
    y = alt.Y(f"{value}:Q", title=y_title, scale=alt.Scale(zero=False, nice=True))
    tooltip = [alt.Tooltip("jalali:N", title="Date (تاریخ)"), alt.Tooltip(f"{value}:Q", title=y_title, format=",.1f")]
    line = alt.Chart(df).mark_line(color=SERIES_1, strokeWidth=2, strokeCap="round", strokeJoin="round").encode(x, y)
    points = alt.Chart(df).mark_point(
        filled=True, size=90, color=SERIES_1, stroke=ring, strokeWidth=2, opacity=1
    ).encode(x, y, tooltip=tooltip)
    # wide invisible hit targets so hovering near a point is enough
    hits = alt.Chart(df).mark_point(size=500, opacity=0).encode(x, y, tooltip=tooltip)
    return _base(alt.layer(line, points, hits), height)


def revenue_chart(daily: pd.DataFrame, height: int = 280, ring: str = "white") -> alt.Chart:
    """Two series over time (lab vs clinic) with a shared hover rule and legend."""
    long = daily.melt(id_vars=["date", "jalali"], value_vars=["lab", "clinic"], var_name="source", value_name="amount")
    long["source"] = long["source"].map({"lab": "Laboratory (آزمایشگاه)", "clinic": "Clinic (مطب)"})
    color = alt.Color(
        "source:N",
        scale=alt.Scale(domain=["Laboratory (آزمایشگاه)", "Clinic (مطب)"], range=[SERIES_1, SERIES_2]),
    )
    x = alt.X("date:T", title=None, axis=alt.Axis(format="%m-%d", labelAngle=0, tickCount=8))
    y = alt.Y("amount:Q", title="Revenue (ریال)", axis=alt.Axis(format="~s"))
    lines = alt.Chart(long).mark_line(strokeWidth=2, strokeCap="round", strokeJoin="round").encode(x, y, color)
    hover = alt.selection_point(fields=["date"], nearest=True, on="pointerover", empty=False, clear="pointerout")
    wide = daily.assign(total=daily["lab"] + daily["clinic"])
    rule = alt.Chart(wide).mark_rule(color="#898781", strokeWidth=1).encode(
        x,
        opacity=alt.condition(hover, alt.value(0.8), alt.value(0)),
        tooltip=[
            alt.Tooltip("jalali:N", title="Date (تاریخ)"),
            alt.Tooltip("lab:Q", title="Laboratory", format=","),
            alt.Tooltip("clinic:Q", title="Clinic", format=","),
            alt.Tooltip("total:Q", title="Total", format=","),
        ],
    ).add_params(hover)
    points = alt.Chart(long).mark_point(filled=True, size=80, stroke=ring, strokeWidth=2, opacity=1).encode(
        x, y, color, opacity=alt.condition(hover, alt.value(1), alt.value(0))
    ).transform_filter(hover)
    return _base(alt.layer(lines, rule, points), height)


def top_tests_chart(df: pd.DataFrame, height_per_bar: int = 30) -> alt.Chart:
    """Horizontal bars, single series, value at the tip."""
    y = alt.Y("test:N", sort="-x", title=None, axis=alt.Axis(labelLimit=260))
    x = alt.X("count:Q", title="Times ordered (تعداد)", axis=alt.Axis(tickMinStep=1, format="d"))
    tooltip = [alt.Tooltip("test:N", title="Test"), alt.Tooltip("count:Q", title="Count"),
               alt.Tooltip("revenue:Q", title="Revenue (ریال)", format=",")]
    bars = alt.Chart(df).mark_bar(color=SERIES_1, size=18, cornerRadiusEnd=4).encode(y, x, tooltip=tooltip)
    labels = alt.Chart(df).mark_text(align="left", dx=6, fontSize=11).encode(y, x, text=alt.Text("count:Q"))
    return _base(alt.layer(bars, labels), max(120, height_per_bar * len(df)))
