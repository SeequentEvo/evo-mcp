"""
Combined Variogram + Search Ellipsoid Visualization
-----------------------------------------------------
Overlays a variogram structure ellipsoid with its scaled search neighborhood
in 3D so the user can visually confirm the search radius relative to the
variogram model.

Usage (agent instructions):
1. Call staging_invoke_interaction(object_name="...", interaction_name="get_ellipsoid_details",
       params={"include_surface_points": True})
   Assign result["result"] to var_ellipsoid_data below.
2. Call staging_invoke_interaction(object_name="...", interaction_name="get_search_parameters",
       params={"scale_factor": 2.0})
   Assign result["result"] to search_params below.
3. Run this script.
"""

import plotly.graph_objects as go
from evo.compute.tasks import Ellipsoid, EllipsoidRanges, Rotation

# ── Paste result["result"] from get_ellipsoid_details here ─────────────────
var_ellipsoid_data = {
    "variogram_name": "My Variogram",
    "selected_structure_index": 0,
    "structure": {"structure_type": "spherical"},
    "surface_points": {"x": [], "y": [], "z": []},
}

# ── Paste result["result"] from get_search_parameters here ─────────────────
search_params = {
    "scale_factor": 2.0,
    "scaled_ranges": {"major": 0.0, "semi_major": 0.0, "minor": 0.0},
    "rotation": {"dip_azimuth": 0.0, "dip": 0.0, "pitch": 0.0},
}
# ───────────────────────────────────────────────────────────────────────────

# Build search ellipsoid surface points from the scaled ranges
search_ellipsoid = Ellipsoid(
    ellipsoid_ranges=EllipsoidRanges(
        major=search_params["scaled_ranges"]["major"],
        semi_major=search_params["scaled_ranges"]["semi_major"],
        minor=search_params["scaled_ranges"]["minor"],
    ),
    rotation=Rotation(
        dip_azimuth=search_params["rotation"]["dip_azimuth"],
        dip=search_params["rotation"]["dip"],
        pitch=search_params["rotation"]["pitch"],
    ),
)
search_x, search_y, search_z = search_ellipsoid.surface_points(center=(0, 0, 0))

fig = go.Figure()

# Variogram structure ellipsoid (smaller, solid blue)
sp = var_ellipsoid_data["surface_points"]
fig.add_trace(
    go.Mesh3d(
        x=sp["x"],
        y=sp["y"],
        z=sp["z"],
        alphahull=0,
        opacity=0.4,
        color="blue",
        name=f"Variogram (structure {var_ellipsoid_data['selected_structure_index']}: "
        f"{var_ellipsoid_data['structure']['structure_type']})",
    )
)

# Search neighborhood ellipsoid (larger, transparent gold)
fig.add_trace(
    go.Mesh3d(
        x=search_x.tolist(),
        y=search_y.tolist(),
        z=search_z.tolist(),
        alphahull=0,
        opacity=0.15,
        color="gold",
        name=f"Search neighborhood ({search_params['scale_factor']}×)",
    )
)

fig.update_layout(
    title=f"Kriging setup: {var_ellipsoid_data['variogram_name']}",
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
