# Plotting Examples for Variogram Visualization

Use this reference to generate plotly code for visualizing variogram inspection results.

## 3D Ellipsoid Visualization

### Surface Mesh (Opaque)

Use this when you want a solid 3D ellipsoid surface representation.

**Input data:**
- `ellipsoid_result` from `get_variogram_ellipsoid_details(include_surface_points=true)`
- Data fields: `surface_points.x`, `surface_points.y`, `surface_points.z` (list of coordinates)
- Also use: `center` (location), `ranges` (major/semi_major/minor)

**Code:**
```python
import plotly.graph_objects as go

# From get_variogram_ellipsoid_details
ellipsoid_data = {...}  # result dict

# Extract surface points
surface_x = ellipsoid_data["surface_points"]["x"]
surface_y = ellipsoid_data["surface_points"]["y"]
surface_z = ellipsoid_data["surface_points"]["z"]

# Create 3D mesh
fig = go.Figure()
fig.add_trace(go.Mesh3d(
    x=surface_x,
    y=surface_y,
    z=surface_z,
    alphahull=0,  # Makes a solid surface using convex hull
    opacity=0.3,
    color="blue",
    name=f"Variogram Ellipsoid (Structure {ellipsoid_data['selected_structure_index']})"
))

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
```

### Wireframe (Lightweight)

Use this for a faster, cleaner 3D representation without filling.

**Input data:**
- `ellipsoid_result` from `get_variogram_ellipsoid_details(include_wireframe_points=true)`
- Data fields: `wireframe_points.x`, `wireframe_points.y`, `wireframe_points.z`

**Code:**
```python
import plotly.graph_objects as go

# From get_variogram_ellipsoid_details with include_wireframe_points=true
ellipsoid_data = {...}

fig = go.Figure()
fig.add_trace(go.Scatter3d(
    x=ellipsoid_data["wireframe_points"]["x"],
    y=ellipsoid_data["wireframe_points"]["y"],
    z=ellipsoid_data["wireframe_points"]["z"],
    mode="lines",
    line=dict(color="darkblue", width=2),
    name=f"Variogram Range (Structure {ellipsoid_data['selected_structure_index']})"
))

fig.update_layout(
    title=f"Variogram Ellipsoid Wireframe: {ellipsoid_data['variogram_name']}",
    scene=dict(
        xaxis_title="X",
        yaxis_title="Y",
        zaxis_title="Z",
        aspectmode="data",
    ),
    height=700,
    width=900,
)
fig.show()
```

### Combined: Variogram + Search Ellipsoid

Compare the variogram structure with a scaled search neighborhood.

**Input data:**
- `var_ellipsoid` from `get_variogram_ellipsoid_details(surface_points=true)`
- `search_params` from `get_variogram_search_params(scale_factor=2.0)`
- Generate a second ellipsoid from the scaled ranges (using same rotation)

**Code:**
```python
import plotly.graph_objects as go
from evo.compute.tasks import Ellipsoid, EllipsoidRanges, Rotation

# 1. Get variogram structure
var_ellipsoid_data = get_variogram_ellipsoid_details(
    variogram_name=variogram_name,
    include_surface_points=True
)

# 2. Get scaled search params
search_params = get_variogram_search_params(
    variogram_name=variogram_name,
    scale_factor=2.0
)

# 3. Generate search ellipsoid points
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

# 4. Plot both
fig = go.Figure()

# Variogram ellipsoid (smaller, opaque blue)
fig.add_trace(go.Mesh3d(
    x=var_ellipsoid_data["surface_points"]["x"],
    y=var_ellipsoid_data["surface_points"]["y"],
    z=var_ellipsoid_data["surface_points"]["z"],
    alphahull=0,
    opacity=0.4,
    color="blue",
    name=f"Variogram Structure (Type: {var_ellipsoid_data['structure']['structure_type']})"
))

# Search ellipsoid (larger, transparent gold)
fig.add_trace(go.Mesh3d(
    x=search_x.tolist(),
    y=search_y.tolist(),
    z=search_z.tolist(),
    alphahull=0,
    opacity=0.15,
    color="gold",
    name=f"Search Neighborhood ({search_params['scale_factor']}x)"
))

fig.update_layout(
    title=f"Kriging Setup: {var_ellipsoid_data['variogram_name']}",
    scene=dict(xaxis_title="X", yaxis_title="Y", zaxis_title="Z", aspectmode="data"),
    showlegend=True,
    height=700,
    width=900,
)
fig.show()
```

---

## 2D Variogram Curve Visualization

### Principal-Direction Curves

Plot semivariance vs. distance for the three principal directions (major, semi-major, minor).

**Input data:**
- `curves_result` from `get_variogram_curve_details(n_points=200)`
- Data structure: `variogram_curves.major|semi_major|minor.distance` and `.semivariance` (each a list)
- Reference lines: `sill` and `nugget`

**Code:**
```python
import plotly.graph_objects as go

# From get_variogram_curve_details
curves_data = {...}

fig = go.Figure()

# Add traces for each principal direction
for direction, color in [("major", "red"), ("semi_major", "green"), ("minor", "blue")]:
    curve = curves_data["variogram_curves"][direction]
    fig.add_trace(go.Scatter(
        x=curve["distance"],
        y=curve["semivariance"],
        mode="lines",
        name=direction.replace("_", "-").title(),
        line=dict(color=color, width=2),
    ))

# Add sill reference line
fig.add_hline(
    y=curves_data["sill"],
    line_dash="dash",
    line_color="black",
    annotation_text=f"Sill = {curves_data['sill']:.3f}",
    annotation_position="right",
)

# Add nugget reference line (if non-zero)
if curves_data["nugget"] > 0:
    fig.add_hline(
        y=curves_data["nugget"],
        line_dash="dot",
        line_color="gray",
        annotation_text=f"Nugget = {curves_data['nugget']:.3f}",
        annotation_position="right",
    )

fig.update_layout(
    title=f"Variogram Model - Principal Directions: {curves_data.get('variogram_name', 'Imported')}",
    xaxis_title="Distance (h)",
    yaxis_title="Semivariance γ(h)",
    hovermode="x unified",
    showlegend=True,
    height=500,
    width=900,
    template="plotly_white",
)

fig.show()
```

### Arbitrary-Direction Curve

Plot a single curve in a custom direction alongside principal curves for comparison.

**Input data:**
- `curves_result` from `get_variogram_curve_details(azimuth=45.0, dip=15.0)`
- Contains: `all principal curves` + `arbitrary_direction_curve` (distance/semivariance)
- Parameters: the `azimuth` and `dip` used to request the curve

**Code:**
```python
import plotly.graph_objects as go

# From get_variogram_curve_details with azimuth and dip
curves_data = {...}
requested_azimuth = 45.0
requested_dip = 15.0

fig = go.Figure()

# Add principal directions in light colors
for direction, color in [("major", "red"), ("semi_major", "green"), ("minor", "blue")]:
    curve = curves_data["variogram_curves"][direction]
    fig.add_trace(go.Scatter(
        x=curve["distance"],
        y=curve["semivariance"],
        mode="lines",
        name=f"{direction.replace('_', '-').title()} (baseline)",
        line=dict(color=color, width=1, dash="dash"),
        opacity=0.6,
    ))

# Add arbitrary-direction curve prominently
arb_curve = curves_data["arbitrary_direction_curve"]
fig.add_trace(go.Scatter(
    x=arb_curve["distance"],
    y=arb_curve["semivariance"],
    mode="lines+markers",
    name=f"Custom (Az={requested_azimuth}°, Dip={requested_dip}°)",
    line=dict(color="darkviolet", width=3),
    marker=dict(size=4),
))

# Add sill reference
fig.add_hline(
    y=curves_data["sill"],
    line_dash="dash",
    line_color="black",
    annotation_text=f"Sill = {curves_data['sill']:.3f}",
    annotation_position="right",
)

fig.update_layout(
    title=f"Variogram: Principal vs. Custom Direction (Az={requested_azimuth}°, Dip={requested_dip}°)",
    xaxis_title="Distance (h)",
    yaxis_title="Semivariance γ(h)",
    hovermode="x unified",
    showlegend=True,
    height=500,
    width=900,
    template="plotly_white",
)

fig.show()
```

---

## Combined Dashboard

Display 3D ellipsoid and 2D curves side-by-side in one dashboard.

**Code:**
```python
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Gather all data
var_ellipsoid = get_variogram_ellipsoid_details(variogram_name=variogram_name, include_wireframe_points=True)
curves = get_variogram_curve_details(variogram_name=variogram_name, n_points=200)

# Create subplots: 1 row, 2 columns (3D left, 2D right)
fig = make_subplots(
    rows=1, cols=2,
    specs=[[{"type": "scatter3d"}, {"type": "scatter"}]],
    subplot_titles=("Ellipsoid Geometry", "Semivariance Curves"),
    horizontal_spacing=0.12,
    column_widths=[0.5, 0.5],
)

# Left: 3D wireframe
fig.add_trace(
    go.Scatter3d(
        x=var_ellipsoid["wireframe_points"]["x"],
        y=var_ellipsoid["wireframe_points"]["y"],
        z=var_ellipsoid["wireframe_points"]["z"],
        mode="lines",
        line=dict(color="darkblue", width=2),
        name="Ellipsoid",
        showlegend=False,
    ),
    row=1, col=1,
)

# Right: 2D curves
for direction, color in [("major", "red"), ("semi_major", "green"), ("minor", "blue")]:
    curve = curves["variogram_curves"][direction]
    fig.add_trace(
        go.Scatter(
            x=curve["distance"],
            y=curve["semivariance"],
            mode="lines",
            name=direction.replace("_", "-").title(),
            line=dict(color=color, width=2),
            showlegend=True,
        ),
        row=1, col=2,
    )

# Add sill line to 2D plot
fig.add_hline(
    y=curves["sill"],
    line_dash="dash",
    line_color="black",
    annotation_text=f"Sill = {curves['sill']:.3f}",
    row=1, col=2,
)

fig.update_xaxes(title_text="Distance (h)", row=1, col=2)
fig.update_yaxes(title_text="Semivariance γ(h)", row=1, col=2)
fig.update_scenes(xaxis_title="X", yaxis_title="Y", zaxis_title="Z", aspectmode="data", row=1, col=1)

fig.update_layout(
    title=f"Variogram Analysis: {var_ellipsoid['variogram_name']}",
    height=600,
    width=1400,
    showlegend=True,
    hovermode="closest",
)

fig.show()
```

---

## Field Mapping Reference

Quick lookup for mapping tool outputs to plot inputs:

| Visualization | Tool | Field Path | Data Type |
| --- | --- | --- | --- |
| 3D Surface Mesh | `get_variogram_ellipsoid_details` | `surface_points.x/y/z` | list[float] |
| 3D Wireframe | `get_variogram_ellipsoid_details` | `wireframe_points.x/y/z` | list[float] |
| 2D Major Curve | `get_variogram_curve_details` | `variogram_curves.major.distance/semivariance` | list[float] |
| 2D Semi-major Curve | `get_variogram_curve_details` | `variogram_curves.semi_major.distance/semivariance` | list[float] |
| 2D Minor Curve | `get_variogram_curve_details` | `variogram_curves.minor.distance/semivariance` | list[float] |
| 2D Arbitrary Curve | `get_variogram_curve_details` | `arbitrary_direction_curve.distance/semivariance` | list[float] |
| Reference Line (Sill) | `get_variogram_curve_details` | `sill` | float |
| Reference Line (Nugget) | `get_variogram_curve_details` | `nugget` | float |
| Ellipsoid Center | `get_variogram_ellipsoid_details` | `center.x/y/z` | float |
| Ellipsoid Ranges | `get_variogram_ellipsoid_details` | `ranges.major/semi_major/minor` | float |
| Rotation Parameters | `get_variogram_ellipsoid_details` | `rotation.dip_azimuth/dip/pitch` | float (degrees) |

---

## Tips

- For large datasets or interactive dashboards, use `wireframe_points` instead of `surface_points` for faster rendering
- Include both sill and nugget reference lines for complete model understanding
- When comparing multiple structures, iterate through `structure_index` and display side-by-side
- Use `n_points=100-200` for smooth curves; increase for publication quality
- For arbitrary-direction curves, test key directions (0°, 45°, 90°) to understand anisotropy
