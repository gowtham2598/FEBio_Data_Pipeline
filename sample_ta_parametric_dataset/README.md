# Parametric FEBio Dataset Generator (Human Tibialis Anterior)

Batch execution and feature extraction pipeline for active muscle contraction simulations on an **anatomical human Tibialis Anterior (TA)** finite element geometry in FEBio. The pipeline samples material properties and dynamic load curves, injects them into model definitions (`.feb`), executes simulations headlessly via the FEBio command-line solver, and extracts nodal and element time-series datasets.

---

## Geometry & Mesh Specifications

This module operates on an anatomical 3D finite element mesh derived from segmented human lower-limb anatomy:

* **Target Geometry:** Human Tibialis Anterior muscle belly (anterior shin dorsiflexor)
* **Mesh Elements:** 196,999 linear tetrahedral elements (`tet4`)
* **Mesh Nodes:** 44,684 unique spatial nodes
* **Boundary Conditions:** Fixed zero-displacement boundary constraint at the distal/proximal insertion surfaces (`ZeroDisplacement1`)
* **Fiber Alignment:** Anisotropic longitudinal fiber alignment along the $z$-axis ($[0, 0, 1]$)
* **Material Model:** Transversely isotropic Mooney-Rivlin matrix coupled with active contraction (`<ascl lc="1">`)

---

## Directory Structure

```text
sample_ta_parametric_dataset/
├── ta-muscle-contraction.feb          # Base TA simulation template (<plotfile type="vtk">)
├── dataset_manifest.csv               # Summary table of all runs, parameters, and load curves
├── dataset_manifest.json              # Full dataset provenance and per-run metadata
├── README.md                          # Usage and configuration guide
├── scripts/
│   ├── config.py                      # Parameter bounds, curve settings, and run options
│   ├── data_extraction.py             # VTK field extraction and metadata parser
│   └── generate_dataset.py            # Batch execution orchestrator
└── dataset/
    ├── sim_001/                       # Simulation run directory
    │   ├── sim_001.feb                # Injected model input
    │   ├── sim_001.log                # Solver log
    │   ├── sim_001.0.vtk ... .50.vtk  # Timestep VTK meshes (51 timesteps)
    │   ├── febio_execution.log        # Process execution log
    │   ├── simulation_metadata.json   # Run metadata and load curve linkages
    │   ├── nodal_timeseries.csv       # 44,684 nodes x 51 steps = ~2.27M rows
    │   └── element_timeseries.csv     # 196,999 elements x 51 steps = ~10.04M rows
    └── ...
```

---

## Parameter Sampling & Dynamic Load Curves

Configuration bounds are set in `scripts/config.py`:

### 1. Constitutive Material Properties
Three material parameters are varied with 1-decimal-place precision:

| Parameter | XML Element | Baseline | Sample Range | Precision | Physical Meaning |
| :--- | :--- | :---: | :---: | :---: | :--- |
| `c1` | `<c1>` | `13.85` | `[10.0, 16.0]` | `0.1` | Passive matrix shear modulus (kPa) |
| `Tmax` | `<Tmax>` | `1.0` | `[0.8, 1.2]` | `0.1` | Peak isometric active tension (kPa) |
| `ca0` | `<ca0>` | `4.35` | `[3.8, 4.8]` | `0.1` | Calcium sensitivity threshold ($[Ca^{2+}]_{50}$) |

### 2. Dynamic Load Curve Profiles
* **Profiles (`allowed_profiles`):**
  * `ramp_and_hold`: Monotonic ramp to peak activation $A_{\max}$, held constant through $t = 5.0\text{ s}$.
  * `twitch`: Contraction and relaxation cycle ($0 \to A_{\max} \to 0$) capturing loading and unloading hysteresis.
  * `cyclic`: Repetitive contractions across the simulation window using FEBio's `<extend>REPEAT</extend>` rule.

* **Curve Settings:**
  * **Interpolation (`<interpolate>`):** Sampled between `LINEAR` (piecewise linear ramps) and `SMOOTH` (natural cubic spline interpolation).
  * **Extension (`<extend>`):** Set to `CONSTANT` for ramp/twitch, or `REPEAT` for cyclic profiles.

* **Sampling Bounds (`LOAD_CURVE_CONFIG`):**
  * Peak Activation ($A_{\max}$): `[0.4, 1.0]`
  * Rise Time ($t_{\text{rise}}$): `[0.5, 1.8]` seconds
  * Hold Duration ($t_{\text{hold}}$): `[0.5, 1.2]` seconds (twitch)
  * Relaxation Duration ($t_{\text{relax}}$): `[0.6, 1.5]` seconds (twitch)
  * Cycle Period ($t_{\text{cycle}}$): `[1.0, 1.5]` seconds (cyclic)

---

## Running the Pipeline

```bash
cd sample_ta_parametric_dataset
python scripts/generate_dataset.py
```

* **Automatic Resume (Default):** Identifies the highest existing simulation index and continues from the next integer. New runs are appended to `dataset_manifest.csv` and merged into `dataset_manifest.json`.
* **Specify Batch Size:** `python scripts/generate_dataset.py --num-sims 1`
* **Restart:** `python scripts/generate_dataset.py --overwrite`

---

## Generated Outputs & Manifests

### 1. Summary Manifest (`dataset_manifest.csv`)
Tabular log of all runs:
* `sim_id`, `status` (`COMPLETED` / `FAILED`)
* Constitutive parameters: `c1`, `Tmax`, `ca0`
* Excitation parameters: `lc_profile`, `lc_interp`, `lc_extend`, `lc_Amax`
* Solver metrics and dimensions: `execution_time_sec`, `vtk_count`, `nodal_rows`, `element_rows`

### 2. Provenance Record (`dataset_manifest.json`)
Machine-readable JSON record containing global parameters, curve settings, file paths, and exact load curve $[t, y]$ control coordinates for each run.

### 3. Simulation Directories (`dataset/sim_*/`)
Each simulation folder contains:
* Model files: `{sim_id}.feb`, `{sim_id}.log`, `febio_execution.log`
* VTK timestep exports: `{sim_id}.0.vtk` through `.50.vtk`
* Extracted datasets: `nodal_timeseries.csv`, `element_timeseries.csv`, and `simulation_metadata.json`
