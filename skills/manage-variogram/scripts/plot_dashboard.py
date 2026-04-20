# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""
Variogram Analysis Dashboard
------------------------------
Displays a 3D wireframe ellipsoid and 2D semivariance curves side-by-side
in a single plotly figure.

Usage (agent instructions):
1. Call staging_invoke_interaction(object_name="...", interaction_name="get_ellipsoid_details",
       params={"include_wireframe_points": True})
   Assign result["result"] to var_ellipsoid below.
2. Call staging_invoke_interaction(object_name="...", interaction_name="get_curve_details",
       params={"n_points": 200})
   Assign result["result"] to curves below.
3. Run this script.
"""

import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ── Paste result["result"] from get_ellipsoid_details here ─────────────────
var_ellipsoid = {
    "variogram_name": "My Variogram",
    "wireframe_points": {"x": [], "y": [], "z": []},
}

# ── Paste result["result"] from get_curve_details here ─────────────────────
curves = {
    "sill": 1.0,
    "nugget": 0.0,
    "variogram_curves": {
        "major": {"distance": [], "semivariance": []},
        "semi_major": {"distance": [], "semivariance": []},
        "minor": {"distance": [], "semivariance": []},
    },
}
# ───────────────────────────────────────────────────────────────────────────

fig = make_subplots(
    rows=1,
    cols=2,
    specs=[[{"type": "scatter3d"}, {"type": "scatter"}]],
    subplot_titles=("Ellipsoid Geometry", "Semivariance Curves"),
    horizontal_spacing=0.12,
    column_widths=[0.5, 0.5],
)

# Left: 3D wireframe ellipsoid
wp = var_ellipsoid["wireframe_points"]
fig.add_trace(
    go.Scatter3d(
        x=wp["x"],
        y=wp["y"],
        z=wp["z"],
        mode="lines",
        line=dict(color="darkblue", width=2),
        name="Ellipsoid",
        showlegend=False,
    ),
    row=1,
    col=1,
)

# Right: 2D semivariance curves
DIRECTION_STYLES = {
    "major": dict(color="red", width=2),
    "semi_major": dict(color="green", width=2),
    "minor": dict(color="blue", width=2),
}
for direction, style in DIRECTION_STYLES.items():
    curve = curves["variogram_curves"].get(direction)
    if curve:
        fig.add_trace(
            go.Scatter(
                x=curve["distance"],
                y=curve["semivariance"],
                mode="lines",
                name=direction.replace("_", "-").title(),
                line=style,
                showlegend=True,
            ),
            row=1,
            col=2,
        )

fig.add_hline(
    y=curves["sill"],
    line_dash="dash",
    line_color="black",
    annotation_text=f"Sill = {curves['sill']:.4g}",
    annotation_position="right",
    row=1,
    col=2,
)

if curves.get("nugget", 0) > 0:
    fig.add_hline(
        y=curves["nugget"],
        line_dash="dot",
        line_color="gray",
        annotation_text=f"Nugget = {curves['nugget']:.4g}",
        annotation_position="right",
        row=1,
        col=2,
    )

fig.update_xaxes(title_text="Distance (h)", row=1, col=2)
fig.update_yaxes(title_text="Semivariance γ(h)", row=1, col=2)
fig.update_scenes(
    xaxis_title="X",
    yaxis_title="Y",
    zaxis_title="Z",
    aspectmode="data",
    row=1,
    col=1,
)

fig.update_layout(
    title=f"Variogram analysis: {var_ellipsoid.get('variogram_name', '')}",
    height=600,
    width=1400,
    showlegend=True,
    hovermode="closest",
    template="plotly_white",
)
fig.show()
