"""
Configuration settings for parametric FEBio simulations on Anatomical Human Tibialis Anterior (TA).
"""

import os

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
MODULE_ROOT = os.path.abspath(os.path.join(SCRIPTS_DIR, ".."))

BASE_TEMPLATE_PATH = os.path.join(MODULE_ROOT, "ta-muscle-contraction.feb")
DATASET_DIR = os.path.join(MODULE_ROOT, "dataset")
FEBIO_SOLVER_PATH = "/home/gv2598/FEBioStudio/bin/febio4"

# Number of simulations to run in this batch
NUM_SIMULATIONS = 3
RANDOM_SEED = 42

# Execution mode:
# False (default): Auto-resumes from the next available index (e.g., sim_002) and appends to manifests.
# True: Resets and starts from sim_001.
OVERWRITE_EXISTING = False

# Constitutive & active muscle parameters to vary
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

# -------------------------------------------------------------
# Dynamic Load Curve Configuration
# -------------------------------------------------------------
ENABLE_VARYING_LOAD_CURVES = True

LOAD_CURVE_CONFIG = {
    # Profiles to randomly sample from:
    # - "ramp_and_hold": monotonic ramp up to peak activation followed by sustained hold
    # - "twitch": full contraction & relaxation cycle (loading + unloading hysteresis)
    # - "cyclic": periodic repetitive contractions across the simulation duration
    "allowed_profiles": ["ramp_and_hold", "twitch", "cyclic"],
    
    # FEBio curve interpolation modes:
    # - "LINEAR": piecewise linear
    # - "SMOOTH": natural cubic spline for smooth biological acceleration/deceleration
    "allowed_interpolations": ["LINEAR", "SMOOTH"],
    
    # Timing and amplitude sampling bounds
    "amplitude_range": (0.4, 1.0),      # Peak activation factor (40% to 100% recruitment)
    "rise_time_range": (0.5, 1.8),      # Time to reach peak activation (seconds)
    "hold_duration_range": (0.5, 1.2),  # Plateau duration for twitch (seconds)
    "relax_duration_range": (0.6, 1.5), # Relaxation duration for twitch (seconds)
    "cycle_period_range": (1.0, 1.5),   # Period for cyclic repetition (seconds)
}

# Fixed baseline parameters logged for provenance
CONSTANT_PARAMETERS = {
    "Material": {
        "name": "Muscle_Trans iso MR",
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
    },
    "Geometry": {
        "type": "Anatomical Human Tibialis Anterior (TA)",
        "nodes": 44684,
        "elements": 196999,
        "element_type": "tet4"
    }
}
