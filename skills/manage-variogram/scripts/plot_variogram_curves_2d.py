# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""
2D Variogram Curve Visualization
---------------------------------
Plots semivariance curves for principal directions (and an optional arbitrary
direction) using data from the `get_curve_details` MCP interaction.

Usage (agent instructions):
1. Call staging_invoke_interaction(object_name="...", interaction_name="get_curve_details",
       params={"n_points": 200})
   Add params={"azimuth": X, "dip": Y} to include an arbitrary-direction curve.
2. Paste the value of result["result"] into the `curves_data` variable below.
3. Run this script.
"""

import plotly.graph_objects as go

# ── Paste result["result"] from get_curve_details here ─────────────────────
curves_data = {
    "variogram_name": "My Variogram",
    "sill": 1.0,
    "nugget": 0.0,
    "variogram_curves": {
        "major": {"distance": [], "semivariance": []},
        "semi_major": {"distance": [], "semivariance": []},
        "minor": {"distance": [], "semivariance": []},
    },
    # Present only when azimuth + dip were requested:
    # "arbitrary_direction_curve": {"distance": [], "semivariance": []},
}
# ───────────────────────────────────────────────────────────────────────────

fig = go.Figure()

DIRECTION_STYLES = {
    "major": dict(color="red", width=2),
    "semi_major": dict(color="green", width=2),
    "minor": dict(color="blue", width=2),
}

for direction, style in DIRECTION_STYLES.items():
    curve = curves_data["variogram_curves"].get(direction)
    if curve:
        fig.add_trace(
            go.Scatter(
                x=curve["distance"],
                y=curve["semivariance"],
                mode="lines",
                name=direction.replace("_", "-").title(),
                line=style,
            )
        )

# Optional arbitrary-direction curve
arb = curves_data.get("arbitrary_direction_curve")
if arb:
    fig.add_trace(
        go.Scatter(
            x=arb["distance"],
            y=arb["semivariance"],
            mode="lines+markers",
            name="Custom direction",
            line=dict(color="darkviolet", width=3),
            marker=dict(size=4),
        )
    )

# Sill reference line
fig.add_hline(
    y=curves_data["sill"],
    line_dash="dash",
    line_color="black",
    annotation_text=f"Sill = {curves_data['sill']:.4g}",
    annotation_position="right",
)

# Nugget reference line (if non-zero)
if curves_data.get("nugget", 0) > 0:
    fig.add_hline(
        y=curves_data["nugget"],
        line_dash="dot",
        line_color="gray",
        annotation_text=f"Nugget = {curves_data['nugget']:.4g}",
        annotation_position="right",
    )

fig.update_layout(
    title=f"Variogram Model — Principal Directions: {curves_data.get('variogram_name', '')}",
    xaxis_title="Distance (h)",
    yaxis_title="Semivariance γ(h)",
    hovermode="x unified",
    showlegend=True,
    height=500,
    width=900,
    template="plotly_white",
)
fig.show()
