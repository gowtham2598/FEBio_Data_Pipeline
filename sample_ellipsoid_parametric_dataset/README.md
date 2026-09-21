# Parametric FEBio Dataset Generator (Idealized Ellipsoid)

Batch execution and feature extraction pipeline for active muscle contraction simulations on an idealized fusiform ellipsoid geometry in FEBio. The pipeline supports deterministic grid parameter sweeps, Monte Carlo random sampling, and explicit simulation recipes. It injects parameters and load curves into model definitions (`.feb`), executes simulations headlessly via the FEBio command-line solver, and extracts nodal and element time-series datasets.

---

## Geometry & Mesh Specifications

* **Target Geometry:** Idealized fusiform muscle belly (ellipsoid)
* **Mesh Elements:** 2,516 linear tetrahedral elements (`tet4`)
* **Mesh Nodes:** 634 unique spatial nodes
* **Boundary Conditions:** Fixed zero-displacement boundary at the proximal pole surface (`ZeroDisplacement1`)
* **Fiber Alignment:** Longitudinal fiber orientation along the $z$-axis ($[0, 0, 1]$)
* **Material Model:** Transversely isotropic Mooney-Rivlin matrix coupled with active contraction (`<ascl lc="1">`)

---

## Directory Structure

```text
sample_ellipsoid_parametric_dataset/
├── ellipsoid-muscle-contraction.feb   # Base simulation template (<plotfile type="vtk">)
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
    │   ├── nodal_timeseries.csv       # Coordinates, displacements, reaction forces
    │   └── element_timeseries.csv     # Stresses, strains, relative volume, fiber stretch
    └── ...
```

---

## Sampling Modes

Configure `SAMPLING_MODE` in `scripts/config.py` or override via CLI (`--mode`):

![FEBio Dynamic Load Curve Archetypes](../docs/images/load_curve_archetypes.png)

### 1. Deterministic Grid Sweep (`SAMPLING_MODE = "grid"`)
Systematic Cartesian product across parameter axes. Parameters can be defined as discrete value lists or ranges with fixed step sizes:
```python
GRID_PARAMETERS = {
    "c1": [10.0, 14.0],                  # Matrix shear modulus (kPa)
    "Tmax": [0.8, 1.2],                  # Peak isometric active tension (kPa)
    "ca0": [4.35]                        # Baseline calcium sensitivity (umol/l)
}

# Load curve toggle for grid sweep:
# False: Hold excitation fixed at baseline (1.0 ramp-and-hold) to isolate material effects
# True:  Include discrete load curve settings in the Cartesian product
GRID_INCLUDE_LOAD_CURVE = False

GRID_LOAD_CURVE = {
    "profiles": ["ramp_and_hold", "twitch"],
    "amplitudes": [0.6, 1.0],
    "interpolations": ["LINEAR", "SMOOTH"]
}
```

### 2. Monte Carlo Random Sampling (`SAMPLING_MODE = "random"`)
Uniform random sampling within continuous intervals with customizable precision and seeds:
```python
NUM_SIMULATIONS = 5
RANDOM_SEED = 42

VARIED_PARAMETERS = {
    "c1":   {"range": (10.0, 16.0), "precision": 1},
    "Tmax": {"range": (0.8, 1.2),  "precision": 1},
    "ca0":  {"range": (3.8, 4.8),  "precision": 1}
}

ENABLE_VARYING_LOAD_CURVES = True  # Randomize excitation waveforms and timing
```

### 3. Explicit Recipe List (`SAMPLING_MODE = "explicit_list"`)
Executes an exact sequence of predefined simulation parameter sets:
```python
EXPLICIT_RUNS = [
    {"c1": 10.0, "Tmax": 0.8, "ca0": 4.0},
    {"c1": 13.85, "Tmax": 1.0, "ca0": 4.35},
    {"c1": 16.0, "Tmax": 1.2, "ca0": 4.8}
]
```

---

## Pre-Flight Verification & Safeguards

To prevent configuration errors and unintended long runs, the pipeline includes built-in failsafes:
* **Pre-Flight Banner:** Displays active sampling mode, total planned runs, ID range, and parameter axes before starting.
* **Combinatorial Explosion Safeguard:** If a grid sweep produces more simulations than `GRID_MAX_SIMS_SAFEGUARD` (default: 50 for ellipsoid), the script halts immediately with an informative message unless `--force` is provided.
* **Single Mode Enforcement:** Raises a clear error if an invalid or misspelled mode name is supplied.

### Dry-Run Inspection (`--dry-run`)
Before committing compute time or creating new directories, `--dry-run` computes the exact parameter combinations, target simulation IDs, and excitation modes without invoking the FEBio solver or writing any files to disk.

```bash
python scripts/generate_dataset.py --dry-run
```

**Example Terminal Output:**
```text
================================================================================
  FEBio Parametric Generation - Pre-Flight Check
================================================================================
  [Active Sampling Mode] : GRID
  [Total Runs Planned]   : 4 simulations
  [Execution Range]      : sim_016 to sim_019 (APPEND/RESUME)
  [Load Curve Mode]      : FIXED (Baseline 1.0 ramp-and-hold excitation)
  [Grid Axes]            : {'c1': [10.0, 14.0], 'Tmax': [0.8, 1.2], 'ca0': [4.35]}
================================================================================

[DRY-RUN] Planned simulation queue preview:
  sim_016: c1=10.0, Tmax=0.8, ca0=4.35 | LC: baseline (1.0 ramp-and-hold)
  sim_017: c1=10.0, Tmax=1.2, ca0=4.35 | LC: baseline (1.0 ramp-and-hold)
  sim_018: c1=14.0, Tmax=0.8, ca0=4.35 | LC: baseline (1.0 ramp-and-hold)
  sim_019: c1=14.0, Tmax=1.2, ca0=4.35 | LC: baseline (1.0 ramp-and-hold)

[DRY-RUN] Completed. Exiting without modifying files.
```

---

## Running the Pipeline

```bash
cd sample_ellipsoid_parametric_dataset

# Run active mode defined in config.py (auto-resumes from next index)
python scripts/generate_dataset.py

# Preview execution plan without running
python scripts/generate_dataset.py --dry-run

# Run deterministic grid sweep
python scripts/generate_dataset.py --mode grid

# Run Monte Carlo random batch of 5 runs
python scripts/generate_dataset.py --mode random --num-sims 5

# Run explicit predefined recipes
python scripts/generate_dataset.py --mode explicit_list

# Restart dataset from sim_001
python scripts/generate_dataset.py --overwrite
```

---

## Generated Outputs & Manifests

### 1. Summary Manifest (`dataset_manifest.csv`)
Tabular record of all runs:
* `sim_id`, `sampling_mode`, `status` (`COMPLETED` / `FAILED`)
* Constitutive parameters: `c1`, `Tmax`, `ca0`
* Excitation parameters: `lc_profile`, `lc_interp`, `lc_extend`, `lc_Amax`
* Solver metrics: `execution_time_sec`, `vtk_count`, `nodal_rows`, `element_rows`

### 2. Provenance Record (`dataset_manifest.json`)
Full JSON provenance tracking active sampling mode, grid/random parameter configurations, and exact $[t, y]$ load curve control points.
