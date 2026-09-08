"""
Configuration settings for parametric FEBio simulations.
"""

import os

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
MODULE_ROOT = os.path.abspath(os.path.join(SCRIPTS_DIR, ".."))

BASE_TEMPLATE_PATH = os.path.join(MODULE_ROOT, "ellipsoid-muscle-contraction.feb")
DATASET_DIR = os.path.join(MODULE_ROOT, "dataset")
FEBIO_SOLVER_PATH = "/home/gv2598/FEBioStudio/bin/febio4"

# Number of simulations to run in this batch
NUM_SIMULATIONS = 5
RANDOM_SEED = 42

# Execution mode:
# False (default): Auto-resumes from the next available index (e.g., sim_006) and appends to manifests.
# True: Resets and starts from sim_001.
OVERWRITE_EXISTING = False

# Parameters to vary: (min, max) range and rounding precision
VARIED_PARAMETERS = {
    "c1": {
        "range": (10.0, 16.0),
        "precision": 1,
        "description": "Matrix shear modulus"
    },
    "Tmax": {
        "range": (0.8, 1.2),
        "precision": 1,
        "description": "Peak isometric active tension"
    },
    "ca0": {
        "range": (3.8, 4.8),
        "precision": 1,
        "description": "Half-activation calcium concentration"
    }
}

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
