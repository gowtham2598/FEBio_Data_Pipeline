# FEBio to ML Data Extraction Pipeline

## 1. Project Overview

This repository contains an automated Python-based data extraction pipeline designed to bridge finite element biomechanics simulations (conducted in FEBio) with downstream Machine Learning (ML) surrogate models. The pipeline ingests raw 3D active muscle contraction simulation files (`.feb` and `.vtk`) and transforms them into flat, ML-ready CSV datasets and JSON metadata structures suitable for training neural networks.

---

## 2. Repository Structure

```text
data_pipeline/
├── data_pipeline_extraction.ipynb         # Interactive data extraction notebook
├── ellipsoid-muscle-contraction.feb        # Baseline FEBio input file (geometry, physics, controllers)
├── ellipsoid-muscle-contraction.fsm        # FEBio Studio project file
├── nodal_timeseries.csv                   # Extracted nodal time-series dataset (32,334 rows)
├── element_timeseries.csv                 # Extracted element time-series dataset (128,316 rows)
├── node_to_element_map.json               # Inverted mesh topology map (node -> adjacent elements)
├── simulation_metadata.json               # Extracted material, solver, and load curve metadata
├── scripts/
│   └── data_extraction.py                # Standalone extraction script
├── sample_ellipsoid_parametric_dataset/   # Parametric dataset generator module
│   ├── ellipsoid-muscle-contraction.feb   # Base template (<plotfile type="vtk">)
│   ├── dataset_manifest.csv              # Summary table of all simulation runs
│   ├── dataset_manifest.json             # Provenance manifest (constants, ranges, metrics)
│   ├── scripts/
│   │   ├── config.py                     # Parameter bounds, precision, and solver path
│   │   ├── data_extraction.py            # Local extraction routines
│   │   └── generate_dataset.py           # Automated batch execution loop
│   └── dataset/                          # Individual run directories (sim_001, sim_002, ...)
├── vtk_files/                             # Sequential timestep mesh exports (.t00.vtk - .t50.vtk)
└── jobs/                                  # FEBio solver outputs (.log, .xplt, .feb)
```

---

## 3. Scope & Load Curve Processing

The pipeline extracts the active contraction excitation signal by parsing the `<LoadData>` element from the `.feb` XML file.

### Interpolation Scope
* **Supported Methods:** The current implementation natively evaluates piecewise **LINEAR** load curves.
* **Fail-Safe Checks:** The parser includes automated verification checks:
  * If a `math` controller is detected, the script issues a warning and returns a zero array to prevent silent simulation mismatches.
  * If non-linear interpolation splines (e.g., cubic splines) are specified, a warning is raised regarding potential interpolation discrepancies with FEBio internal evaluations.

### Boundary Extension Rules
FEBio allows load curves to define behavior beyond specified time endpoints. The parser uses NumPy and SciPy (`interp1d`) to mathematically recreate the 4 FEBio extension rules across the entire simulation duration:

* **`CONSTANT`**: Clamps the activation value to the boundary value defined at the nearest endpoint.
* **`EXTRAPOLATE`**: Continues the initial or final linear slope into unbounded time.
* **`REPEAT`**: Periodically loops the load curve over the base cycle period ($T = t_{\max} - t_{\min}$).
* **`REPEAT OFFSET`**: Periodically loops the cycle while adding cumulative offset gain from previous cycles, creating a progressive staircase response.

---

## 4. Data Preprocessing Features

* **Vector & Tensor Flattening:** Multi-dimensional tensor fields cannot be ingested directly as matrices by standard dense neural networks. The pipeline unrolls:
  * 3D spatial vectors (coordinates, displacements, velocities, reaction forces) into 3 scalar columns (`*_0`, `*_1`, `*_2` representing Cartesian $X, Y, Z$).
  * $3\times 3$ second-order tensors (Cauchy stress $\boldsymbol{\sigma}$ and Green-Lagrange strain $\mathbf{E}$) into 9 scalar components (`*_0` through `*_8` in row-major order: $[11, 12, 13, 21, 22, 23, 31, 32, 33]$).
* **Nodal Velocity Integration:** The extraction pipeline specifically captures nodal velocities requested from FEBio outputs. This guarantees velocities map directly to mesh vertices ($X, Y, Z$ coordinates) rather than element centroids.

---

## 5. Dataset Specifications

### 5.1 Nodal Dataset (`nodal_timeseries.csv`)
* **Total Rows:** 32,334 (634 nodes $\times$ 51 timesteps)
* **Total Columns:** 15

| Column Name | Type | Description |
| :--- | :--- | :--- |
| `timestep` | Integer | Simulation time index ($0 \dots 50$) |
| `node_id` | Integer | Node identifier ($0 \dots 633$) |
| `activation` | Float | Calculated muscle activation signal $\alpha(t)$ |
| `coord_x`, `coord_y`, `coord_z` | Float | Reference (undeformed) Cartesian coordinates |
| `displacement_0`, `displacement_1`, `displacement_2` | Float | Nodal displacements $(u_x, u_y, u_z)$ |
| `reaction_forces_0`, `reaction_forces_1`, `reaction_forces_2` | Float | Nodal reaction forces $(F_x, F_y, F_z)$ |
| `nodal_velocity_0`, `nodal_velocity_1`, `nodal_velocity_2` | Float | Nodal velocity components $(v_x, v_y, v_z)$ |

### 5.2 Element Dataset (`element_timeseries.csv`)
* **Total Rows:** 128,316 (2,516 elements $\times$ 51 timesteps)
* **Total Columns:** 27

| Column Name | Type | Description |
| :--- | :--- | :--- |
| `timestep` | Integer | Simulation time index ($0 \dots 50$) |
| `element_id` | Integer | Element identifier ($0 \dots 2515$) |
| `activation` | Float | Calculated muscle activation signal $\alpha(t)$ |
| `stress_0` – `stress_8` | Float | Flattened Cauchy stress tensor components $\sigma_{ij}$ |
| `Lagrange_strain_0` – `Lagrange_strain_8` | Float | Flattened Green-Lagrange strain tensor components $E_{ij}$ |
| `relative_volume` | Float | Ratio of current to reference element volume ($J = \det \mathbf{F}$) |
| `fiber_vector_0`, `fiber_vector_1`, `fiber_vector_2` | Float | Deformed active fiber orientation unit vector |
| `fiber_stretch` | Float | Fiber stretch ratio $\lambda = \|\mathbf{F} \cdot \mathbf{a}_0\|$ |
| `pressure` | Float | Hydrostatic pressure ($p = -\frac{1}{3}\text{tr}(\boldsymbol{\sigma})$) |

---

## 6. Metadata & Topology

* **`simulation_metadata.json`**: Parsed from the `.feb` XML definition to record material parameters, solver settings, and load curves:
  * **Material Model:** Transversely Isotropic Mooney-Rivlin parameters ($c_1, c_2, c_3, c_4, c_5, k, \lambda_{\max}$).
  * **Active Contraction:** Active tension and intracellular calcium dynamics parameters ($T_{\max}, ca_0, \beta, l_0, \text{refl}$). Parameters driven by load curves (e.g., `<ascl lc="1">1</ascl>`) explicitly capture `"driven_by_load_curve": "1"`.
  * **Control Settings:** Time stepping parameters, analysis type (`DYNAMIC`), non-linear solver configurations, and convergence tolerances.
  * **Load Curves (`Load_Curves`):** Excitation controllers parsed from `<LoadData>`. For each curve, extracts:
    * `id`, `name`, and controller `type` (e.g., `loadcurve`).
    * `interpolate` mode (e.g., `LINEAR`, `STEP`) and `extend` rule (`CONSTANT`, `EXTRAPOLATE`, `REPEAT`, `REPEAT OFFSET`).
    * Discrete evaluation `points` (`[[t0, v0], [t1, v1], ...]`).
    * **Driven Parameters (`drives_parameters`):** List of model variables driven by the curve, recording both parameter name and location (e.g., `parameter: "ascl"`, `location: "Material.Material1.active_contraction"`).
* **`node_to_element_map.json`**: Stores a dictionary mapping each `node_id` to an array of adjacent `element_id`s. This topological adjacency representation enables spatial smoothing, element-to-node averaging, and message-passing edge construction in Graph Neural Networks (GNNs).

---

## 7. Workflow & Usage

The pipeline operates in two distinct phases: **Simulation Execution (FEBio)** followed by **Data Extraction (Python/Notebook)**.

### Phase 1: Finite Element Simulation (FEBio)
Before extracting tabular datasets, the biomechanics simulation must be solved by FEBio to generate the sequential timestep mesh files:
1. **Model Configuration:** Ensure the `.feb` input file is configured to output VTK meshes under `<Output>`:
   ```xml
   <Output>
       <plotfile type="vtk">
           <var type="displacement"/>
           <var type="reaction forces"/>
           <var type="stress"/>
           <var type="Lagrange strain"/>
           <var type="relative volume"/>
           <var type="fiber vector"/>
           <var type="fiber stretch"/>
       </plotfile>
   </Output>
   ```
2. **Run Solver:** Execute the simulation via FEBioStudio or the command line:
   ```bash
   febio4 -i ellipsoid-muscle-contraction.feb
   ```
   This generates the individual timestep meshes (`.0.vtk`, `.1.vtk`, ..., `.50.vtk`). Move or point the output files to `vtk_files/`.
   
   > **Note:** A pre-computed baseline simulation run (51 timesteps) is already provided in `vtk_files/` so the extraction pipeline can be tested immediately after cloning without needing to re-run FEBio.

### Phase 2: Data Extraction & ML Preprocessing
Once the simulation timesteps are available:
1. **Install Dependencies:**
   ```bash
   pip install numpy pandas scipy pyvista jupyter
   ```
2. **Run the Extraction Notebook:**
   * Open `data_pipeline_extraction.ipynb` in Jupyter Notebook (or VS Code).
   * Run the cells sequentially from top to bottom.
   * The notebook parses the excitation signal from `<LoadData>`, reads each timestep mesh using PyVista, flattens spatial vectors and stress/strain tensors, and exports `nodal_timeseries.csv`, `element_timeseries.csv`, and `simulation_metadata.json`.
3. **Alternative (Command-Line):**
   You can also run the extraction directly via terminal:
   ```bash
   python scripts/data_extraction.py
   ```

---

## 8. Automated Parametric Batching

If you want to automate **both Phase 1 and Phase 2** together across multiple parameter combinations (e.g., varying $c_1$, $T_{\max}$, and $ca_0$), see the self-contained module in [`sample_ellipsoid_parametric_dataset/`](sample_ellipsoid_parametric_dataset/). It handles parameter sampling, automated XML injection, headless FEBio execution, and dataset extraction in a single automated loop:

```bash
cd sample_ellipsoid_parametric_dataset
python scripts/generate_dataset.py
```
