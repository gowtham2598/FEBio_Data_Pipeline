# Parametric FEBio Dataset Generator (Anatomical Human Biceps)

Batch execution and feature extraction pipeline for active muscle contraction simulations on an anatomically reconstructed human Biceps Brachii geometry in FEBio. The pipeline supports deterministic grid parameter sweeps, Monte Carlo random sampling, and explicit simulation recipes. It injects parameters and load curves into model definitions (`.feb`), executes simulations headlessly via the FEBio command-line solver, and extracts nodal and element time-series datasets.

---

## Geometry & Mesh Specifications

* **Target Geometry:** Anatomical Human Biceps Brachii
* **Mesh Elements:** 15,857 linear tetrahedral elements (`tet4`)
* **Mesh Nodes:** 4,749 unique spatial nodes
* **Boundary Conditions:** Fixed zero-displacement boundary at tendon attachment surfaces
* **Fiber Alignment:** Curvilinear anatomical fiber vector field
* **Material Model:** Transversely isotropic Mooney-Rivlin matrix coupled with active contraction (`<ascl lc="1">`)
---

## Directory Structure

```text
sample_biceps_parametric_dataset/
├── biceps-muscle-contraction.feb      # Base simulation template (<plotfile type="vtk">)
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
```python
GRID_PARAMETERS = {
    "c1": [10.0, 14.0],                  # Matrix shear modulus (kPa)
    "Tmax": [0.8, 1.2],                  # Peak isometric active tension (kPa)
    "ca0": [4.35]                        # Baseline calcium sensitivity (umol/l)
}

# Excitation toggle:
GRID_INCLUDE_LOAD_CURVE = False          # False = fixed baseline; True = sweep profiles
```

### 2. Monte Carlo Random Sampling (`SAMPLING_MODE = "random"`)
```python
NUM_SIMULATIONS = 5
RANDOM_SEED = 42
ENABLE_VARYING_LOAD_CURVES = True
```

### 3. Explicit Recipe List (`SAMPLING_MODE = "explicit_list"`)
```python
EXPLICIT_RUNS = [
    {"c1": 10.0, "Tmax": 0.8, "ca0": 4.0},
    {"c1": 13.85, "Tmax": 1.0, "ca0": 4.35},
    {"c1": 16.0, "Tmax": 1.2, "ca0": 4.8}
]
```

---

## Pre-Flight Verification & Safeguards

* **Pre-Flight Banner:** Confirms sampling mode, planned run count, ID range, and parameter axes before solving.
* **Safeguard Limit:** `GRID_MAX_SIMS_SAFEGUARD = 30` prevents unintentional large batches on this geometry (~8s solver time per run). Bypass with `--force`.

### Dry-Run Inspection (`--dry-run`)
Allows you to verify the exact planned run queue, auto-resumed simulation index, and excitation settings without running the FEBio solver or modifying files:

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
  [Execution Range]      : sim_006 to sim_009 (APPEND/RESUME)
  [Load Curve Mode]      : FIXED (Baseline 1.0 ramp-and-hold excitation)
  [Grid Axes]            : {'c1': [10.0, 14.0], 'Tmax': [0.8, 1.2], 'ca0': [4.35]}
================================================================================

[DRY-RUN] Planned simulation queue preview:
  sim_006: c1=10.0, Tmax=0.8, ca0=4.35 | LC: baseline (1.0 ramp-and-hold)
  sim_007: c1=10.0, Tmax=1.2, ca0=4.35 | LC: baseline (1.0 ramp-and-hold)
  sim_008: c1=14.0, Tmax=0.8, ca0=4.35 | LC: baseline (1.0 ramp-and-hold)
  sim_009: c1=14.0, Tmax=1.2, ca0=4.35 | LC: baseline (1.0 ramp-and-hold)

[DRY-RUN] Completed. Exiting without modifying files.
```

---

## Running the Pipeline

```bash
cd sample_biceps_parametric_dataset

# Run active mode defined in config.py (auto-resumes from next index)
python scripts/generate_dataset.py

# Preview execution plan
python scripts/generate_dataset.py --dry-run

# Run deterministic grid sweep
python scripts/generate_dataset.py --mode grid

# Run Monte Carlo random batch
python scripts/generate_dataset.py --mode random --num-sims 5
```

---

## Generated Outputs & Manifests

* `dataset_manifest.csv`: Tabular index with `sim_id`, `sampling_mode`, parameters, excitation metrics, and run times.
* `dataset_manifest.json`: Full JSON record with parameter configurations and exact load curve coordinates.
* `dataset/sim_*/`: Simulation directory containing `.feb`, `.log`, VTKs, and extracted `nodal_timeseries.csv` and `element_timeseries.csv`.
