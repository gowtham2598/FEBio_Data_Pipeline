# Adding a New Muscle Geometry to the Pipeline

This guide provides step-by-step instructions for integrating a new anatomical muscle geometry (e.g., *Gastrocnemius*, *Soleus*, *Rectus Femoris*, or *Deltoid*) into the parametric dataset generation workflow.

---

## 1. Architectural Overview

The data generation pipeline is strictly **modular and geometry-agnostic**:
- **Zero hardcoded element or node counts**: The pipeline dynamically inspects mesh size, element topology, and timestep counts at runtime.
- **Self-contained modules**: Each muscle geometry lives in its own folder (`sample_<muscle>_parametric_dataset/`) with its own configuration, manifests, and generated simulation folders.
- **Separation of concerns**: Physical modeling (boundary conditions, fiber orientations, contact) is defined and verified once in **FEBio Studio**. The Python pipeline then orchestrates high-throughput sweeps, parameter sampling, solver execution, and ML feature extraction.

```text
data_pipeline/
├── sample_ellipsoid_parametric_dataset/         # Reference: Idealized fusiform geometry
├── sample_biceps_parametric_dataset/            # Reference: Upper-limb anatomical geometry
├── sample_ta_parametric_dataset/                # Reference: Lower-limb high-resolution geometry
└── sample_<new_muscle>_parametric_dataset/      # Your New Muscle Module
    ├── <new_muscle>-muscle-contraction.feb      # Baseline FEBio simulation template
    ├── <new_muscle>-muscle-prestretch.feb       # (Optional) In-situ prestretch template
    ├── dataset/                                 # Individual simulation runs (sim_001, ...)
    ├── dataset_manifest.csv                     # Tabular summary of all runs & parameters
    ├── dataset_manifest.json                    # Full metadata provenance registry
    ├── README.md                                # Muscle-specific documentation
    └── scripts/
        ├── config.py                            # Physiological parameter ranges & options
        ├── generate_dataset.py                  # Batch generator & solver interface
        └── data_extraction.py                   # VTK field extraction to time-series CSVs
```

---

## 2. Step 1: Prepare the Base FEBio Template (`.feb`)

Before running parametric sweeps, create and verify a single baseline model in **FEBio Studio**:

### A. Material Definition (Active Contraction)
The pipeline searches for `<c1>`, `<Tmax>`, and `<ca0>` inside the `<Material>` block:
- **Material Type**: `trans iso Mooney-Rivlin`
- **Active Contraction**: Ensure the activation scale `<ascl>` or calcium concentration is linked to Load Curve 1:
  ```xml
  <active_contraction type="fiber active contraction">
      <ascl lc="1">1</ascl>
      <ca0>4.35</ca0>
      <Tmax>1.0</Tmax>
      <beta>4.75</beta>
      <l0>1.58</l0>
      <refl>2.04</refl>
  </active_contraction>
  ```

### B. Simulation Control
Standardized dynamic contraction settings:
```xml
<Control>
    <analysis>DYNAMIC</analysis>
    <time_steps>50</time_steps>
    <step_size>0.1</step_size>
    <solver>
        <max_refs>15</max_refs>
        <max_ups>10</max_ups>
        <diverge_reform>1</diverge_reform>
        <reform_each_time_step>1</reform_each_time_step>
        <dtol>0.001</dtol>
        <etol>0.01</etol>
        <rtol>0</rtol>
        <lstol>0.9</lstol>
    </solver>
</Control>
```

### C. Output Configuration (VTK Plotfile)
Ensure FEBio Studio exports binary/ASCII VTK files with all required ML field variables:
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

> **Important**: In the FEBio XML structure, the `<LoadData>` section must appear **before** the `<Output>` section.

### D. Single-Run Convergence Test
Run the model once inside FEBio Studio or via CLI:
```bash
febio4 -i <new_muscle>-muscle-contraction.feb
```
Confirm that it converges with `NORMAL TERMINATION`. Save this verified file as `<new_muscle>-muscle-contraction.feb`.

---

## 3. Step 2 (Optional): Prepare the In-Situ Prestretch Template

If your study investigates resting muscle pre-tension (**Approach 1: Uniform In-Situ Prestretch**):

1. Wrap the active material in `uncoupled prestrain elastic`:
   ```xml
   <material id="1" name="MuscleMaterial" type="uncoupled prestrain elastic">
       <density>1</density>
       <k>100</k>
       <prestrain type="in-situ stretch">
           <pre_stretch type="map">pre_stretch</pre_stretch>
       </prestrain>
       <elastic type="trans iso Mooney-Rivlin">
           <c1>13.85</c1>
           ...
       </elastic>
   </material>
   ```
2. Under `<Mesh>`, add a `<PartList name="pre_stretch">` specifying the muscle belly part (e.g. `Part1`).
3. Under `<MeshData>`, include `<ElementData name="pre_stretch" elem_set="Part1">` containing `<e lid="N">1.05</e>` for each element in the muscle mesh.
4. Save this verified file as `<new_muscle>-muscle-prestretch.feb`.

---

## 4. Step 3: Create the New Pipeline Module Directory (Copy & Paste)

> **Workflow note:** Adding a new muscle does not require writing new Python code. Simply duplicate an existing module directory, rename it, and place the new `.feb` template inside.

### Why do we do this?
All batch execution, solver orchestration, VTK field extraction, and manifest logging scripts are pre-configured in the `scripts/` directory. Duplicating an existing module provides these tools immediately.

### Concrete Example: Adding a Calf Muscle (*"Soleus"*)

1. **Copy & Paste the folder**:
   In your file explorer (or terminal), duplicate `sample_biceps_parametric_dataset` and rename the new folder to:
   ```bash
   sample_soleus_parametric_dataset
   ```
   *(Via terminal)*:
   ```bash
   cd data_pipeline
   cp -r sample_biceps_parametric_dataset sample_soleus_parametric_dataset
   cd sample_soleus_parametric_dataset
   ```

2. **Add your new FEBio model**:
   Place your verified FEBio file (e.g. `soleus-muscle-contraction.feb`) inside this new directory.

3. **Clean up previous simulation runs**:
   Delete any old simulation runs inside `dataset/` (or remove `dataset_manifest.csv` and `dataset_manifest.json`) so your new muscle starts with a clean slate.

---

## 5. Step 4: Configure `scripts/config.py`

Edit `sample_<new_muscle>_parametric_dataset/scripts/config.py`:

```python
# 1. Update Template Paths
BASE_TEMPLATE_PATH = os.path.join(MODULE_ROOT, "<new_muscle>-muscle-contraction.feb")
PRESTRETCH_TEMPLATE_PATH = os.path.join(MODULE_ROOT, "<new_muscle>-muscle-prestretch.feb")

# 2. Configure In-Situ Prestretch
ENABLE_PRESTRETCH = False                # Default OFF for baseline; toggle with --prestretch
GRID_PRESTRETCH_VALUES = [1.02, 1.05]    # Discrete stretch levels for grid sweeps
RANDOM_PRESTRETCH_RANGE = (1.01, 1.08)   # Sampling bounds for Monte Carlo random

# 3. Define Muscle-Specific Physiological Parameter Bounds
GRID_PARAMETERS = {
    "c1": [10.0, 14.0],                  # Passive matrix shear modulus (kPa)
    "Tmax": [0.8, 1.2],                  # Maximum isometric active tension (kPa)
    "ca0": [4.35]                        # Half-activation calcium concentration
}

VARIED_PARAMETERS = {
    "c1": {"range": (10.0, 16.0), "precision": 1, "description": "Shear modulus (kPa)"},
    "Tmax": {"range": (0.8, 1.2), "precision": 1, "description": "Active tension (kPa)"},
    "ca0": {"range": (3.8, 4.8), "precision": 1, "description": "Calcium sensitivity"}
}
```

---

## 6. Step 5: Execute Dataset Generation

All pipeline commands work out of the box with zero script modifications:

```bash
# 1. Preview planned queue without running the solver (dry-run)
python scripts/generate_dataset.py --dry-run

# 2. Preview with in-situ prestretch enabled
python scripts/generate_dataset.py --dry-run --prestretch

# 3. Run systematic Cartesian grid sweep
python scripts/generate_dataset.py --mode grid

# 4. Run Monte Carlo random batch (e.g. 20 simulations with prestretch)
python scripts/generate_dataset.py --mode random --num-sims 20 --prestretch

# 5. Auto-resume: Running additional simulations appends to manifests
python scripts/generate_dataset.py --mode random --num-sims 10
```

---

## 7. Automated Verification & Safeguards

The pipeline includes built-in safeguards to protect your simulations:
- **Pre-Flight Inspection**: Confirms active template, sampling mode, planned run count, execution index range, and mapped element count before executing.
- **Prestretch Validation**: If `--prestretch` is used with a template that lacks the prestrain material wrapper or `<ElementData>`, the pipeline stops immediately with an informative message rather than failing mid-run.
- **Grid Size Limit Safeguard**: `GRID_MAX_SIMS_SAFEGUARD` protects against excessively large multi-dimensional grid batches (override with `--force`).
- **Resilience**: If an individual simulation fails to converge, the pipeline logs the failure, records the exit status in `dataset_manifest.csv`, and continues to the next run without crashing the batch.
