<!--
SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated

SPDX-License-Identifier: Apache-2.0
-->

This document provides a comprehensive technical overview of Evo Geoscience Objects (GOs) listed in the Seequent Developer documentation, detailing their purpose and the required and optional parameters for their schema.

All Geoscience Objects inherit a set of **Base Required** properties (`name`, `uuid`, `bounding_box`, `coordinate_reference_system`, `schema`) and **Base Optional** properties (`description`, `extensions`, `tags`, `lineage`). The parameters listed below are the object-specific properties, including the components of nested objects where applicable.

---

### `design-geometry`

**Technical Description:** Represents a planned or engineered geometry, such as a mine pit, tunnel, or infrastructure design. The core data is typically a mesh or a set of polylines/points defining the design boundary.

| Parameter Type | Parameter Name | Description |
| :--- | :--- | :--- |
| **Required** | `geometry` | The geometric definition of the design (e.g., vertices and connectivity for a mesh or lines). |
| **Optional** | `attributes` | Any associated design attributes (e.g., material type, design phase). |

### `downhole-collection`

**Technical Description:** A collection of drill holes used to organize and store downhole data (e.g., lithology, assay) for a set of holes for downstream workflows like geological modeling.

| Parameter Type | Parameter Name | Description |
| :--- | :--- | :--- |
| **Required** | `locations` | The geographic reference (XYZ coordinates) of each drill hole collar. |
| **Required** | `path` | The trajectory of each drill hole, represented by a series of depth, azimuth, and dip values (raw survey data). |
| **Optional** | `collections` | The downhole data stored in a series of related arrays (e.g., `lithology`, `assay` data). |

### `downhole-intervals`

**Technical Description:** Represents data collected over intervals (e.g., lithology, assay) within a set of drill holes.

| Parameter Type | Parameter Name | Description |
| :--- | :--- | :--- |
| **Required** | `intervals` | The start and end depths for each interval within the drill holes. |
| **Optional** | `collections` | The downhole data stored in a series of related arrays (e.g., `lithology`, `assay` data). |

### `drilling-campaign`

**Technical Description:** Stores data about the entire lifecycle of planning and drilling exploratory drillholes, including planned trajectories, predicted geology, and interim field results.

| Parameter Type | Parameter Name | Description |
| :--- | :--- | :--- |
| **Required** | `planned_holes` | A list of planned drillholes, each with a collar location and parametric trajectory definition. |
| **Optional** | `prognoses` | Predicted geological intervals or other data to aid in drilling operations. |
| **Optional** | `interim_results` | Partial or complete field data collected prior to final analysis. |

### `frequency-domain-electromagnetic`

**Technical Description:** Captures the properties and measurements related to frequency domain electromagnetic (FDEM) surveys, used to study the electrical properties of the subsurface.

| Parameter Type | Parameter Name | Description |
| :--- | :--- | :--- |
| **Required** | `survey_type` | The mode of acquisition (e.g., "GROUND" or "AIR"). |
| **Required** | `data_type` | The type of data measured (e.g., string identifier). |
| **Required** | `channels` | Information about the measurement channels (e.g., coil configuration, standard deviations). |
| **Required** | `line_list` | Definitions for one or more survey lines (e.g., line number, date, location channels). |
| **Optional** | `survey_information` | Additional details about the survey setup. |

### `geological-model-meshes`

**Technical Description:** A collection of one or more meshes from a geological model, organized by folder. Volumes are triangular mesh hulls, and surfaces are triangular mesh surfaces.

| Parameter Type | Parameter Name | Description |
| :--- | :--- | :--- |
| **Required** | `folders` | A recursive list of folders for organizational hierarchy. |
| **Required** | `mesh` | The embedded mesh, defining vertices, triangles, and parts. |
| **Optional** | `materials` | Materials used by this mesh collection. |
| **Optional** | `volumes` | A list of embedded volumes (closed triangle mesh hulls). |
| **Optional** | `surfaces` | A list of embedded surfaces (continuous triangle meshes). |

### `geological-sections`

**Technical Description:** Represents a 2D cross-section, long section, or serial section, typically used to display and evaluate geological models and data along a defined plane or polyline.

| Parameter Type | Parameter Name | Description |
| :--- | :--- | :--- |
| **Required** | `definition` | The geometric definition of the section (e.g., plane coordinates, polyline vertices). |
| **Required** | `evaluations` | The models or data that are evaluated and displayed on the section. |
| **Optional** | `flatten_to_2d` | Boolean flag indicating if the section is flattened to a 2D plane. |

### `geophysical-records-1d`

**Technical Description:** Captures physical properties related to 1D geophysical records, typically the product of geophysical inversion, composed of a series of vertical (columnar) datasets.

| Parameter Type | Parameter Name | Description |
| :--- | :--- | :--- |
| **Required** | `number_of_layers` | The consistent number of layers for all records. |
| **Required** | `locations` | An array of coordinates (x, y, z) for each record. |
| **Required** | `depths` | An array of depth values for each layer. |
| **Optional** | `line_numbers` | Line numbers associated with the records. |

### `global-ellipsoid`

**Technical Description:** Captures the parameters of a single, global ellipsoid, typically used to represent the anisotropy or main direction of continuity for spatial geological properties in geostatistical workflows.

| Parameter Type | Parameter Name | Description |
| :--- | :--- | :--- |
| **Required** | `ellipsoid_ranges` | The three lengths for the major, semi-major, and minor axes. |
| **Required** | `rotation` | The rotation of the ellipsoid in 3D space (azimuth, dip, and pitch). |
| **Optional** | `domain` | The domain the ellipsoid is modeled for. |
| **Optional** | `attribute` | The attribute the ellipsoid is modeled for. |

### `gravity`

**Technical Description:** Represents geolocated, time-stamped gravity survey data, used to infer the density of subsurface materials.

| Parameter Type | Parameter Name | Description |
| :--- | :--- | :--- |
| **Required** | `type` | The survey mode (e.g., "GROUND", "AIR", or "MARINE"). |
| **Required** | `survey_type` | The type of measurement (e.g., "GRAV", "FTG", or "AGG"). |
| **Required** | `base_stations` | At least one base station definition (name, location, associated lines). |
| **Required** | `gravity_line_list` | Definitions for one or more survey lines. |
| **Optional** | `survey_information` | Additional details about the survey setup. |

### `line-segments`

**Technical Description:** A fundamental geometric object representing a collection of 3D line segments, often used for polylines, fault traces, or other linear features.

| Parameter Type | Parameter Name | Description |
| :--- | :--- | :--- |
| **Required** | `lines` | The line data, which must contain `vertices` (XYZ coordinates) and `indices` (pairs of vertex indices defining the segments). |
| **Optional** | `attributes` | Attributes associated with the line segments (e.g., color, thickness, type). |

### `lineations-data-pointset`

**Technical Description:** A variant of the `pointset` schema that associates structural lineation data (trend and plunge angles) with each point.

| Parameter Type | Parameter Name | Description |
| :--- | :--- | :--- |
| **Required** | `locations` | The points, which must contain `coordinates` (XYZ) and `lineations` (trend and plunge). |
| **Optional** | `locations` (attributes) | Optional attributes within `locations` such as `values`, `colors`, or `labels`. |

### `local-ellipsoids`

**Technical Description:** Captures a set of spatially located ellipsoids, used to model spatially varying anisotropy for geostatistical workflows.

| Parameter Type | Parameter Name | Description |
| :--- | :--- | :--- |
| **Required** | `locations` | The 3D coordinates of the ellipsoids. |
| **Required** | `ellipsoids` | The six ellipsoid parameters (major, semi-major, minor, azimuth, dip, and pitch) for each location. |
| **Required** | `domain` | The domain the local ellipsoids are modeled for. |
| **Required** | `attribute` | The attribute the local ellipsoids are modeled for. |

### `magnetics`

**Technical Description:** Represents geolocated, time-stamped geomagnetic survey data, used to infer the magnetic properties of subsurface materials.

| Parameter Type | Parameter Name | Description |
| :--- | :--- | :--- |
| **Required** | `type` | The survey mode (e.g., "GROUND", "AIR", or "MARINE"). |
| **Required** | `survey_type` | The type of measurement (e.g., "TMI", "VMG", or "MGRM"). |
| **Required** | `line_list` | Definitions for one or more survey lines. |
| **Optional** | `base_stations` | Base station definitions. |
| **Optional** | `gradient_details` | Details for magnetic gradiometry. |
| **Optional** | `qa_qc_lists` | Lists for quality assurance/quality control tests. |

### `non-parametric-continuous-cumulative-distribution`

**Technical Description:** Represents the empirical cumulative distribution function (CDF) of a dataset without assuming a predefined shape, used in geostatistical methods like conditional simulation.

| Parameter Type | Parameter Name | Description |
| :--- | :--- | :--- |
| **Required** | `distribution_data` | The calculated cumulative probabilities and corresponding values defining the CDF. |
| **Optional** | `tail_extrapolations` | Parameters defining the extrapolation model for the upper and lower tails of the distribution. |

### `planar-data-pointset`

**Technical Description:** A variant of the `pointset` schema that associates structural planar data (dip azimuth, dip, and polarity) with each point.

| Parameter Type | Parameter Name | Description |
| :--- | :--- | :--- |
| **Required** | `locations` | The points, which must contain `coordinates` (XYZ), `plane_orientations` (dip azimuth, dip), and `plane_polarity`. |
| **Optional** | `locations` (attributes) | Optional attributes within `locations` such as `values`, `colors`, or `labels`. |

### `pointset`

**Technical Description:** Captures a set of points in space and their associated attributes, commonly used for spatial data like sampling locations or observation points.

| Parameter Type | Parameter Name | Description |
| :--- | :--- | :--- |
| **Required** | `locations` | The points, which must contain `coordinates` (XYZ). |
| **Optional** | `locations` (attributes) | Optional attributes within `locations` such as `values`, `colors`, or `labels`. |

### `radiometric`

**Technical Description:** Represents geolocated, time-stamped radiometric survey data, measuring naturally occurring gamma-rays from elements like Potassium, Uranium, and Thorium.

| Parameter Type | Parameter Name | Description |
| :--- | :--- | :--- |
| **Required** | `survey_type` | The mode of acquisition (e.g., "GROUND" or "AIR"). |
| **Required** | `dead_time` | Timing characteristic of the survey measurement (in milliseconds). |
| **Required** | `live_time` | Timing characteristic of the survey measurement (in milliseconds). |
| **Required** | `idle_time` | Timing characteristic of the survey measurement (in milliseconds). |
| **Required** | `array_dimension` | The dimensions of the detector array. |
| **Required** | `energy_level` | The energy level of the array elements (in meV). |
| **Required** | `line_list` | Definitions for one or more survey lines. |
| **Optional** | `survey_information` | Additional details about the survey setup. |

### `regular-2d-grid`

**Technical Description:** Represents a regularly-sampled two-dimensional grid (like an image) with data attached to the cells and vertices, where all cells are of equal size.

| Parameter Type | Parameter Name | Description |
| :--- | :--- | :--- |
| **Required** | `origin` | The coordinates of the grid origin [x, y, z]. |
| **Required** | `size` | The number of cells in each direction [grid_size_x, grid_size_y]. |
| **Required** | `cell_size` | The size of each cell in the grid [cell_size_x, cell_size_y]. |
| **Optional** | `rotation` | Orientation of the grid. |
| **Optional** | `cell_attributes` | Attributes associated with the cells. |
| **Optional** | `vertex_attributes` | Attributes associated with the vertices. |

### `regular-3d-grid`

**Technical Description:** Represents a regularly-sampled three-dimensional grid with data attached to the cells and vertices, where all cells are of equal size.

| Parameter Type | Parameter Name | Description |
| :--- | :--- | :--- |
| **Required** | `origin` | The coordinates of the grid origin [x, y, z]. |
| **Required** | `size` | The number of cells in each direction [grid_size_x, grid_size_y, grid_size_z]. |
| **Required** | `cell_size` | The size of each cell in the grid [cell_size_x, cell_size_y, cell_size_z]. |
| **Optional** | `rotation` | Orientation of the grid. |
| **Optional** | `cell_attributes` | Attributes associated with the cells. |
| **Optional** | `vertex_attributes` | Attributes associated with the vertices. |

### `regular-masked-3d-grid`

**Technical Description:** A 3D regular grid where a boolean mask indicates which cells have values (active cells), allowing for a smaller attribute data size by only considering active cells.

| Parameter Type | Parameter Name | Description |
| :--- | :--- | :--- |
| **Required** | `origin` | The coordinates of the grid origin [x, y, z]. |
| **Required** | `size` | The number of cells in each direction [grid_size_x, grid_size_y, grid_size_z]. |
| **Required** | `cell_size` | The size of each cell in the grid [cell_size_x, cell_size_y, cell_size_z]. |
| **Required** | `mask` | A boolean attribute that indicates which cells have values (active cells). |
| **Required** | `number_of_active_cells` | The total count of active cells. |
| **Optional** | `rotation` | Orientation of the grid. |
| **Optional** | `cell_attributes` | Attributes associated with the cells. |

### `resistivity-ip`

**Technical Description:** Represents geolocated, time-stamped resistivity and induced polarization (IP) survey data, used to infer the electrical properties of subsurface materials.

| Parameter Type | Parameter Name | Description |
| :--- | :--- | :--- |
| **Required** | `number_of_dimensions` | The survey dimension ("1D", "2D", or "3D"). |
| **Required** | `number_contributing_electrodes` | The number of contributing electrodes (excluding remote electrodes). |
| **Required** | `survey_type` | The type of survey (e.g., "DCIP", "SIP", "PHASEIP", or "DCRES"). |
| **Required** | `configuration` | Details about the survey configuration and remote element locations. |
| **Required** | `line_list` | Definitions for one or more survey lines. |
| **Optional** | `survey_information` | Additional details about the survey setup. |

### `tensor-2d-grid`

**Technical Description:** Represents a two-dimensional grid where cells may have different sizes along the x and y axes.

| Parameter Type | Parameter Name | Description |
| :--- | :--- | :--- |
| **Required** | `origin` | The coordinates of the grid origin [x, y, z]. |
| **Required** | `size` | The number of cells in each direction [grid_size_x, grid_size_y]. |
| **Required** | `grid_cells_2d` | The cell sizes for each dimension (arrays of sizes for x and y). |
| **Optional** | `rotation` | Orientation of the grid. |
| **Optional** | `cell_attributes` | Attributes associated with the cells. |
| **Optional** | `vertex_attributes` | Attributes associated with the vertices. |

### `tensor-3d-grid`

**Technical Description:** Represents a three-dimensional tensor grid where cells may have different sizes along the x, y, and z axes.

| Parameter Type | Parameter Name | Description |
| :--- | :--- | :--- |
| **Required** | `origin` | The coordinates of the grid origin [x, y, z]. |
| **Required** | `size` | The number of cells in each direction [grid_size_x, grid_size_y, grid_size_z]. |
| **Required** | `grid_cells_3d` | The cell sizes for each dimension (arrays of sizes for x, y, and z). |
| **Optional** | `rotation` | Orientation of the grid. |
| **Optional** | `cell_attributes` | Attributes associated with the cells. |
| **Optional** | `vertex_attributes` | Attributes associated with the vertices. |

### `time-domain-electromagnetic`

**Technical Description:** Represents geolocated, time-stamped time-domain electromagnetic (TDEM) survey data, used to infer the electrical conductivity of subsurface materials.

| Parameter Type | Parameter Name | Description |
| :--- | :--- | :--- |
| **Required** | `survey_type` | The mode of acquisition (e.g., "GROUND" or "AIR"). |
| **Required** | `channels` | Information about the measurement channels (e.g., timing, waveform, gates). |
| **Required** | `line_list` | Definitions for one or more survey lines. |
| **Optional** | `geometry_category` | The geometry of the survey (e.g., loop configuration). |
| **Optional** | `gps_location` | Location of GPS relative to the point of reference. |

### `triangle-mesh`

**Technical Description:** A mesh composed of triangles, defined by triplets of indices into a vertex list. Used to represent surfaces or volumes.

| Parameter Type | Parameter Name | Description |
| :--- | :--- | :--- |
| **Required** | `triangles` | The triangle data, which must contain `vertices` (XYZ coordinates) and `indices` (vertex triplets defining the triangles). |
| **Optional** | `parts` | Groups of triangles for partitioning the mesh. |
| **Optional** | `edges` | Optional edge data for the mesh. |

### `unstructured-grid`

**Technical Description:** Represents a grid where cells can have arbitrary shapes and sizes, defined by vertices and connectivity.

| Parameter Type | Parameter Name | Description |
| :--- | :--- | :--- |
| **Required** | `geometry` | The grid geometry, which must contain `vertices` (XYZ coordinates) and `cells` (connectivity/topology). |
| **Optional** | `cell_attributes` | Attributes associated with the cells. |
| **Optional** | `vertex_attributes` | Attributes associated with the vertices. |

### `unstructured-hex-grid`

**Technical Description:** Represents an unstructured grid where all cells are hexahedrons (six-sided polyhedrons).

| Parameter Type | Parameter Name | Description |
| :--- | :--- | :--- |
| **Required** | `hexahedrons` | The connectivity/topology data defining the hexahedral cells. |
| **Optional** | `cell_attributes` | Attributes associated with the cells. |
| **Optional** | `vertex_attributes` | Attributes associated with the vertices. |

### `unstructured-quad-grid`

**Technical Description:** Represents an unstructured grid where all cells are quadrilaterals.

| Parameter Type | Parameter Name | Description |
| :--- | :--- | :--- |
| **Required** | `quadrilaterals` | The connectivity/topology data defining the quadrilateral cells. |
| **Optional** | `cell_attributes` | Attributes associated with the cells. |
| **Optional** | `vertex_attributes` | Attributes associated with the vertices. |

### `unstructured-tet-grid`

**Technical Description:** Represents an unstructured grid where all cells are tetrahedrons (four-sided polyhedrons).

| Parameter Type | Parameter Name | Description |
| :--- | :--- | :--- |
| **Required** | `tetrahedrons` | The connectivity/topology data defining the tetrahedral cells. |
| **Optional** | `cell_attributes` | Attributes associated with the cells. |
| **Optional** | `vertex_attributes` | Attributes associated with the vertices. |

### `variogram`

**Technical Description:** A geostatistical model used to quantify the spatial variability (autocorrelation) of a property, defined by a model type, sill, range, and orientation.

| Parameter Type | Parameter Name | Description |
| :--- | :--- | :--- |
| **Required** | `model_type` | The mathematical model used (e.g., Spherical, Exponential, Gaussian). |
| **Required** | `structures` | A list of nested structures, each defining a `sill`, `range`, and `model_type`. |
| **Required** | `rotation` | The orientation of the variogram ellipsoid (Dip, Dip Azimuth, Pitch). |
| **Optional** | `nugget` | The nugget effect (a discontinuity at the origin). |