# Parametric FEBio Dataset Generator (Anatomical Tibialis Anterior)

Batch execution and feature extraction pipeline for active muscle contraction simulations on an anatomically reconstructed human Tibialis Anterior (TA) geometry in FEBio. The pipeline supports deterministic grid parameter sweeps, Monte Carlo random sampling, and explicit simulation recipes. It injects parameters and load curves into model definitions (`.feb`), executes simulations headlessly via the FEBio command-line solver, and extracts nodal and element time-series datasets.

---

## Geometry & Mesh Specifications

* **Target Geometry:** Anatomical Human Tibialis Anterior (TA)
* **Mesh Elements:** 196,999 linear tetrahedral elements (`tet4`)
* **Mesh Nodes:** 44,684 unique spatial nodes
* **Boundary Conditions:** Fixed zero-displacement boundary at proximal tendon insertion
* **Fiber Alignment:** Longitudinal and pennate fiber orientations
* **Material Model:** Transversely isotropic Mooney-Rivlin matrix coupled with active contraction (`<ascl lc="1">`)
* **Computational Footprint:** ~105s solver + ~2.5 min feature extraction (~4.5 min total per run; ~5.7 GB raw output per run).

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
NUM_SIMULATIONS = 3
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
* **Strict Safeguard Limit:** `GRID_MAX_SIMS_SAFEGUARD = 10` halts large grid sweeps automatically to avoid long runtimes and heavy disk consumption (~4.5 min and 5.7 GB per run). Bypass with `--force`.

### Dry-Run Inspection (`--dry-run`)
Essential on this computationally heavy geometry (~197k elements) to verify planned simulation counts and parameter combinations before launching:

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
  [Execution Range]      : sim_003 to sim_006 (APPEND/RESUME)
  [Load Curve Mode]      : FIXED (Baseline 1.0 ramp-and-hold excitation)
  [Grid Axes]            : {'c1': [10.0, 14.0], 'Tmax': [0.8, 1.2], 'ca0': [4.35]}
================================================================================

[DRY-RUN] Planned simulation queue preview:
  sim_003: c1=10.0, Tmax=0.8, ca0=4.35 | LC: baseline (1.0 ramp-and-hold)
  sim_004: c1=10.0, Tmax=1.2, ca0=4.35 | LC: baseline (1.0 ramp-and-hold)
  sim_005: c1=14.0, Tmax=0.8, ca0=4.35 | LC: baseline (1.0 ramp-and-hold)
  sim_006: c1=14.0, Tmax=1.2, ca0=4.35 | LC: baseline (1.0 ramp-and-hold)

[DRY-RUN] Completed. Exiting without modifying files.
```

---

## Running the Pipeline

```bash
cd sample_ta_parametric_dataset

# Run active mode defined in config.py (auto-resumes from next index)
python scripts/generate_dataset.py

# Preview execution plan
python scripts/generate_dataset.py --dry-run

# Run deterministic grid sweep
python scripts/generate_dataset.py --mode grid

# Run Monte Carlo random batch
python scripts/generate_dataset.py --mode random --num-sims 2
```

---

## Generated Outputs & Manifests

* `dataset_manifest.csv`: Tabular index with `sim_id`, `sampling_mode`, parameters, excitation metrics, and run times.
* `dataset_manifest.json`: Full JSON record with parameter configurations and exact load curve coordinates.
* `dataset/sim_*/`: Simulation directory containing `.feb`, `.log`, VTKs, and extracted `nodal_timeseries.csv` and `element_timeseries.csv`.
