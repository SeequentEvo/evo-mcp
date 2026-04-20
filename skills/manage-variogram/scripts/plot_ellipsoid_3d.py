# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""
3D Ellipsoid Visualization
--------------------------
Plots a variogram or search ellipsoid in 3D using data from the
`get_ellipsoid_details` MCP interaction.

Usage (agent instructions):
1. Call staging_invoke_interaction(object_name="...", interaction_name="get_ellipsoid_details",
       params={"include_surface_points": True, "include_wireframe_points": True})
2. Paste the value of result["result"] into the `ellipsoid_data` variable below.
3. Run this script.
"""

import plotly.graph_objects as go

# ── Paste result["result"] from get_ellipsoid_details here ─────────────────
ellipsoid_data = {
    "variogram_name": "My Variogram",
    "selected_structure_index": 0,
    "surface_points": {"x": [], "y": [], "z": []},
    "wireframe_points": {"x": [], "y": [], "z": []},
    "ranges": {"major": 0.0, "semi_major": 0.0, "minor": 0.0},
    "center": {"x": 0.0, "y": 0.0, "z": 0.0},
}
# ───────────────────────────────────────────────────────────────────────────

MODE = "surface"  # "surface" | "wireframe" | "both"

fig = go.Figure()

if MODE in ("surface", "both") and ellipsoid_data.get("surface_points"):
    sp = ellipsoid_data["surface_points"]
    fig.add_trace(
        go.Mesh3d(
            x=sp["x"],
            y=sp["y"],
            z=sp["z"],
            alphahull=0,
            opacity=0.3,
            color="blue",
            name=f"Ellipsoid (structure {ellipsoid_data['selected_structure_index']})",
        )
    )

if MODE in ("wireframe", "both") and ellipsoid_data.get("wireframe_points"):
    wp = ellipsoid_data["wireframe_points"]
    fig.add_trace(
        go.Scatter3d(
            x=wp["x"],
            y=wp["y"],
            z=wp["z"],
            mode="lines",
            line=dict(color="darkblue", width=2),
            name=f"Ellipsoid wireframe (structure {ellipsoid_data['selected_structure_index']})",
        )
    )

fig.update_layout(
    title=f"Variogram Ellipsoid: {ellipsoid_data['variogram_name']}",
    scene=dict(
        xaxis_title="X",
        yaxis_title="Y",
        zaxis_title="Z",
        aspectmode="data",
    ),
    showlegend=True,
    height=700,
    width=900,
)
fig.show()
