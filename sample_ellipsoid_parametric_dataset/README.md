# Parametric FEBio Dataset Generator

Automated batch runner and feature extraction pipeline for active muscle contraction simulations in FEBio. The pipeline samples material and contractile properties, updates model input files (`.feb`), runs simulations headlessly via the FEBio command-line solver, and extracts nodal and element time-series datasets for machine learning surrogate models.

---

## Directory Structure

```text
sample_ellipsoid_parametric_dataset/
├── ellipsoid-muscle-contraction.feb   # Base simulation template (<plotfile type="vtk">)
├── dataset_manifest.csv               # Summary table of all runs and sampled parameters
├── dataset_manifest.json              # Full dataset provenance and per-run metadata
├── README.md                          # Usage and configuration guide
├── scripts/
│   ├── config.py                      # Parameter bounds, precision, and run settings
│   ├── data_extraction.py             # VTK field extraction and metadata parser
│   └── generate_dataset.py            # Batch execution orchestrator
└── dataset/
    ├── sim_001/                       # Simulation run directory
    │   ├── sim_001.feb                # Injected model input
    │   ├── sim_001.log                # Solver log
    │   ├── sim_001.0.vtk ... .50.vtk  # Timestep VTK meshes
    │   ├── febio_execution.log        # Process execution log
    │   ├── simulation_metadata.json   # Run metadata and load curve linkages
    │   ├── nodal_timeseries.csv       # Nodal coordinates, displacements, forces, velocities
    │   └── element_timeseries.csv     # Stresses, strains, volume ratios, fiber metrics
    ├── sim_002/
    └── ...
```

---

## Parameter Sampling

Parameter variation ranges are configured in `scripts/config.py`. By default, three parameters are varied with 1-decimal-place precision:

| Parameter | XML Element | Default | Sample Range | Precision | Physical Meaning |
| :--- | :--- | :---: | :---: | :---: | :--- |
| `c1` | `<c1>` | `13.85` | `[10.0, 16.0]` | `0.1` | Passive matrix shear modulus |
| `Tmax` | `<Tmax>` | `1.0` | `[0.8, 1.2]` | `0.1` | Peak isometric active tension |
| `ca0` | `<ca0>` | `4.35` | `[3.8, 4.8]` | `0.1` | Calcium sensitivity threshold ($[Ca^{2+}]_{50}$) |

Fixed baseline settings (Mooney-Rivlin coefficients $c_2 \dots c_5$, bulk modulus $k$, fiber orientation, Hill active parameters $\beta, l_0, \text{refl}$, and solver time-stepping) are logged in `dataset_manifest.json` for reproducibility.

---

## Running the Pipeline

### 1. Configuration (Optional)
Edit `scripts/config.py` to change default parameters or batch settings:
```python
NUM_SIMULATIONS = 5         # Default batch size
RANDOM_SEED = 42            # Seed for reproducible parameter sampling
OVERWRITE_EXISTING = False  # False = resume from next index; True = restart at sim_001
```

### 2. Execution
Run the orchestrator from the module root:
```bash
cd sample_ellipsoid_parametric_dataset
python scripts/generate_dataset.py
```

### 3. Batch Continuation and Options
* **Automatic Resume (Default):** The script scans `dataset/`, identifies the highest existing simulation index, and continues from the next number (e.g., starting at `sim_006` if `sim_001`–`sim_005` exist). New runs are appended to `dataset_manifest.csv` and merged into `dataset_manifest.json`.
* **Specify Batch Size:** To run a specific number of new simulations:
  ```bash
  python scripts/generate_dataset.py --num-sims 10
  ```
* **Restart:** To overwrite existing runs and start from `sim_001`:
  ```bash
  python scripts/generate_dataset.py --overwrite
  ```

### 4. Generated Outputs
* **`dataset_manifest.csv`**: Tabular overview of all runs, sampled parameter values, solve times, and file counts.
* **`dataset_manifest.json`**: Machine-readable record containing baseline constants, variation ranges, and per-simulation metrics.
* **`dataset/sim_*/`**: Self-contained run folders with the FEBio model files (`.feb`, `.log`), direct VTK timestep meshes, and extracted datasets (`nodal_timeseries.csv`, `element_timeseries.csv`, `simulation_metadata.json`).
