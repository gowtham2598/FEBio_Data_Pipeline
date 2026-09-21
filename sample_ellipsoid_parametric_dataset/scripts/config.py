"""
Configuration settings for parametric FEBio simulations.
Supports deterministic grid sweeps, Monte Carlo random sampling, and explicit run lists.
"""

import os

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
MODULE_ROOT = os.path.abspath(os.path.join(SCRIPTS_DIR, ".."))

BASE_TEMPLATE_PATH = os.path.join(MODULE_ROOT, "ellipsoid-muscle-contraction.feb")
DATASET_DIR = os.path.join(MODULE_ROOT, "dataset")
FEBIO_SOLVER_PATH = "/home/gv2598/FEBioStudio/bin/febio4"

# -------------------------------------------------------------
# Sampling Mode Selection
# Options:
#   "grid"          - Systematic parameter sweep (Cartesian product of ranges/lists)
#   "random"        - Monte Carlo uniform random sampling within intervals
#   "explicit_list" - Predefined list of specific simulation recipes
# -------------------------------------------------------------
VALID_MODES = {"grid", "random", "explicit_list"}
SAMPLING_MODE = "grid"

# Execution mode:
# False (default): Auto-resumes from next available index (e.g. sim_016) and appends to manifests.
# True: Resets and starts from sim_001.
OVERWRITE_EXISTING = False

# -------------------------------------------------------------
# Mode 1: Deterministic Grid Sweep Settings (SAMPLING_MODE = "grid")
# Parameters can be defined as:
#   - A discrete list: [10.0, 14.0]
#   - A range with step: {"min": 10.0, "max": 16.0, "step": 3.0}
# -------------------------------------------------------------
GRID_PARAMETERS = {
    "c1": [10.0, 14.0],                  # Matrix shear modulus (kPa)
    "Tmax": [0.8, 1.2],                  # Peak isometric active tension (kPa)
    "ca0": [4.35]                        # Baseline calcium sensitivity (umol/l)
}

# Grid Load Curve Options:
# False: Hold excitation fixed at baseline (1.0 ramp-and-hold) to isolate material effects.
# True:  Include discrete load curve settings below in the Cartesian sweep.
GRID_INCLUDE_LOAD_CURVE = False

GRID_LOAD_CURVE = {
    "profiles": ["ramp_and_hold", "twitch"],
    "amplitudes": [0.6, 1.0],
    "interpolations": ["LINEAR", "SMOOTH"]
}

# Safeguard threshold: Abort if grid generates more than this count unless --force is passed
GRID_MAX_SIMS_SAFEGUARD = 50

# -------------------------------------------------------------
# Mode 2: Random Monte Carlo Settings (SAMPLING_MODE = "random")
# -------------------------------------------------------------
NUM_SIMULATIONS = 5
RANDOM_SEED = 42

VARIED_PARAMETERS = {
    "c1": {
        "range": (10.0, 16.0),
        "precision": 1,
        "description": "Matrix shear modulus (kPa)"
    },
    "Tmax": {
        "range": (0.8, 1.2),
        "precision": 1,
        "description": "Peak isometric active tension (kPa)"
    },
    "ca0": {
        "range": (3.8, 4.8),
        "precision": 1,
        "description": "Half-activation calcium concentration (umol/l)"
    }
}

ENABLE_VARYING_LOAD_CURVES = True

LOAD_CURVE_CONFIG = {
    "allowed_profiles": ["ramp_and_hold", "twitch", "cyclic"],
    "allowed_interpolations": ["LINEAR", "SMOOTH"],
    "amplitude_range": (0.4, 1.0),
    "rise_time_range": (0.5, 1.8),
    "hold_duration_range": (0.5, 1.2),
    "relax_duration_range": (0.6, 1.5),
    "cycle_period_range": (1.0, 1.5),
}

# -------------------------------------------------------------
# Mode 3: Explicit Custom Recipes (SAMPLING_MODE = "explicit_list")
# -------------------------------------------------------------
EXPLICIT_RUNS = [
    {"c1": 10.0, "Tmax": 0.8, "ca0": 4.0},
    {"c1": 13.85, "Tmax": 1.0, "ca0": 4.35},
    {"c1": 16.0, "Tmax": 1.2, "ca0": 4.8}
]

# Fixed baseline parameters logged for provenance
CONSTANT_PARAMETERS = {
    "Material": {
        "name": "Material1",
        "type": "trans iso Mooney-Rivlin",
        "density": "1",
        "k": "100",
        "c2": "0",
        "c3": "2.07",
        "c4": "61.44",
        "c5": "640.7",
        "lam_max": "1.03",
        "fiber_vector": "0,0,1"
    },
    "Active_Contraction": {
        "ascl": "1",
        "camax": "0",
        "beta": "4.75",
        "l0": "1.58",
        "refl": "2.04"
    },
    "Control_Settings": {
        "analysis": "DYNAMIC",
        "time_steps": "50",
        "step_size": "0.1"
    }
}

# Failsafe validation
if SAMPLING_MODE not in VALID_MODES:
    raise ValueError(
        f"Invalid SAMPLING_MODE '{SAMPLING_MODE}'. Must be one of: {sorted(list(VALID_MODES))}"
    )
