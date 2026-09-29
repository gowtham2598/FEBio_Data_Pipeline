"""
Batch runner for parametric FEBio simulations and dataset extraction.
Supports:
  1. Deterministic grid parameter sweeps (Cartesian product)
  2. Monte Carlo random sampling
  3. Predefined explicit simulation recipe lists
Includes automatic index continuation, load curve toggling, and failsafe pre-flight checks.
"""

import os
import sys
import time
import glob
import random
import itertools
import subprocess
import json
import re
import datetime
import argparse
import numpy as np
import pandas as pd
import xml.etree.ElementTree as ET

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from config import (
    BASE_TEMPLATE_PATH,
    DATASET_DIR,
    FEBIO_SOLVER_PATH,
    VALID_MODES,
    SAMPLING_MODE,
    OVERWRITE_EXISTING,
    GRID_PARAMETERS,
    GRID_INCLUDE_LOAD_CURVE,
    GRID_LOAD_CURVE,
    GRID_MAX_SIMS_SAFEGUARD,
    NUM_SIMULATIONS,
    RANDOM_SEED,
    VARIED_PARAMETERS,
    ENABLE_VARYING_LOAD_CURVES,
    LOAD_CURVE_CONFIG,
    EXPLICIT_RUNS,
    CONSTANT_PARAMETERS
)
from data_extraction import build_timeseries_dataset, extract_input_parameters


def get_next_sim_index(dataset_dir):
    """
    Finds the highest existing sim_XXX index in dataset_dir and returns the next integer.
    Returns 1 if no existing simulation directories are found.
    """
    if not os.path.exists(dataset_dir):
        return 1
    existing_dirs = glob.glob(os.path.join(dataset_dir, "sim_*"))
    indices = []
    for d in existing_dirs:
        base = os.path.basename(d)
        match = re.match(r"^sim_(\d+)$", base)
        if match:
            indices.append(int(match.group(1)))
    return max(indices) + 1 if indices else 1


def expand_parameter_axis(param_name, spec):
    """
    Expands a grid parameter specification into a concrete list of numeric values.
    Supports either:
      - A discrete list: [10.0, 14.0]
      - A range dict: {"min": 10.0, "max": 16.0, "step": 3.0}
    """
    if isinstance(spec, list):
        return [float(v) for v in spec]
    if isinstance(spec, dict):
        min_val = float(spec["min"])
        max_val = float(spec["max"])
        step = float(spec["step"])
        if step <= 0:
            raise ValueError(f"Step size for '{param_name}' must be positive, got {step}")
        if min_val > max_val:
            raise ValueError(f"min must be <= max for '{param_name}', got min={min_val}, max={max_val}")
        vals = np.arange(min_val, max_val + step * 0.5, step)
        return [round(float(v), 4) for v in vals]
    raise TypeError(f"Invalid parameter spec for '{param_name}'. Must be a list or dict with min/max/step.")


def build_deterministic_load_curve(profile, amplitude, interpolate):
    """
    Generates a deterministic load curve definition for grid sweeps.
    """
    a_max = round(float(amplitude), 2)
    interp = str(interpolate).upper()
    
    if profile == "ramp_and_hold":
        t_rise = 1.0
        extend = "CONSTANT"
        if interp == "SMOOTH":
            points = [
                (0.0, 0.0),
                (round(t_rise * 0.4, 2), round(a_max * 0.35, 2)),
                (round(t_rise * 0.8, 2), round(a_max * 0.90, 2)),
                (t_rise, a_max),
                (5.0, a_max)
            ]
        else:
            points = [
                (0.0, 0.0),
                (t_rise, a_max),
                (5.0, a_max)
            ]
        params = {"A_max": a_max, "t_rise": t_rise}
        
    elif profile == "twitch":
        t1, t2, t3 = 1.0, 1.8, 2.8
        extend = "CONSTANT"
        if interp == "SMOOTH":
            points = [
                (0.0, 0.0),
                (round(t1 * 0.5, 2), round(a_max * 0.45, 2)),
                (t1, a_max),
                (t2, a_max),
                (round(t2 + (t3 - t2) * 0.5, 2), round(a_max * 0.45, 2)),
                (t3, 0.0),
                (5.0, 0.0)
            ]
        else:
            points = [
                (0.0, 0.0),
                (t1, a_max),
                (t2, a_max),
                (t3, 0.0),
                (5.0, 0.0)
            ]
        params = {"A_max": a_max, "t_rise": t1, "t_hold": round(t2 - t1, 2), "t_relax": round(t3 - t2, 2)}
        
    elif profile == "cyclic":
        t_cycle = 1.2
        t_peak = 0.48
        extend = "REPEAT"
        if interp == "SMOOTH":
            points = [
                (0.0, 0.0),
                (round(t_peak * 0.5, 2), round(a_max * 0.5, 2)),
                (t_peak, a_max),
                (round(t_peak + (t_cycle - t_peak) * 0.5, 2), round(a_max * 0.5, 2)),
                (t_cycle, 0.0)
            ]
        else:
            points = [
                (0.0, 0.0),
                (t_peak, a_max),
                (t_cycle, 0.0)
            ]
        params = {"A_max": a_max, "t_cycle": t_cycle, "t_peak": t_peak}
    else:
        raise ValueError(f"Unsupported load curve profile: {profile}")
        
    return {
        "profile": profile,
        "interpolate": interp,
        "extend": extend,
        "points": points,
        "parameters": params
    }


def sample_parameters(varied_config, sim_index, base_seed):
    """
    Sample values uniformly within defined ranges for Monte Carlo mode.
    Uses base_seed + sim_index to ensure deterministic reproducibility.
    """
    rng = random.Random(base_seed + sim_index if base_seed is not None else None)
    sampled = {}
    for param, cfg in varied_config.items():
        low, high = cfg["range"]
        precision = cfg.get("precision", 1)
        sampled[param] = round(rng.uniform(low, high), precision)
    return sampled


def sample_load_curve(sim_index, base_seed, config):
    """
    Generates a randomized load curve profile based on LOAD_CURVE_CONFIG.
    """
    rng = random.Random((base_seed + 1000 + sim_index) if base_seed is not None else None)
    
    allowed_profiles = config.get("allowed_profiles", ["ramp_and_hold", "twitch", "cyclic"])
    allowed_interp = config.get("allowed_interpolations", ["LINEAR", "SMOOTH"])
    
    profile = rng.choice(allowed_profiles)
    interp = rng.choice(allowed_interp)
    
    amp_min, amp_max = config.get("amplitude_range", (0.4, 1.0))
    a_max = round(rng.uniform(amp_min, amp_max), 2)
    
    if profile == "ramp_and_hold":
        rise_min, rise_max = config.get("rise_time_range", (0.5, 2.0))
        t_rise = round(rng.uniform(rise_min, rise_max), 2)
        extend = "CONSTANT"
        if interp == "SMOOTH":
            points = [
                (0.0, 0.0),
                (round(t_rise * 0.4, 2), round(a_max * 0.35, 2)),
                (round(t_rise * 0.8, 2), round(a_max * 0.90, 2)),
                (t_rise, a_max),
                (5.0, a_max)
            ]
        else:
            points = [
                (0.0, 0.0),
                (t_rise, a_max),
                (5.0, a_max)
            ]
        params = {"A_max": a_max, "t_rise": t_rise}
        
    elif profile == "twitch":
        rise_min, rise_max = config.get("rise_time_range", (0.5, 1.5))
        t_rise = round(rng.uniform(rise_min, rise_max), 2)
        hold_min, hold_max = config.get("hold_duration_range", (0.5, 1.2))
        t_hold = round(rng.uniform(hold_min, hold_max), 2)
        relax_min, relax_max = config.get("relax_duration_range", (0.6, 1.5))
        t_relax = round(rng.uniform(relax_min, relax_max), 2)
        
        t1 = t_rise
        t2 = round(t1 + t_hold, 2)
        t3 = round(t2 + t_relax, 2)
        if t3 > 4.8:
            t3 = 4.8
            t2 = min(t2, 3.5)
            
        extend = "CONSTANT"
        if interp == "SMOOTH":
            points = [
                (0.0, 0.0),
                (round(t1 * 0.5, 2), round(a_max * 0.45, 2)),
                (t1, a_max),
                (t2, a_max),
                (round(t2 + (t3 - t2) * 0.5, 2), round(a_max * 0.45, 2)),
                (t3, 0.0),
                (5.0, 0.0)
            ]
        else:
            points = [
                (0.0, 0.0),
                (t1, a_max),
                (t2, a_max),
                (t3, 0.0),
                (5.0, 0.0)
            ]
        params = {"A_max": a_max, "t_rise": t_rise, "t_hold": t_hold, "t_relax": t_relax}
        
    elif profile == "cyclic":
        cycle_min, cycle_max = config.get("cycle_period_range", (1.0, 1.5))
        t_cycle = round(rng.uniform(cycle_min, cycle_max), 2)
        t_peak = round(t_cycle * 0.4, 2)
        extend = "REPEAT"
        if interp == "SMOOTH":
            points = [
                (0.0, 0.0),
                (round(t_peak * 0.5, 2), round(a_max * 0.5, 2)),
                (t_peak, a_max),
                (round(t_peak + (t_cycle - t_peak) * 0.5, 2), round(a_max * 0.5, 2)),
                (t_cycle, 0.0)
            ]
        else:
            points = [
                (0.0, 0.0),
                (t_peak, a_max),
                (t_cycle, 0.0)
            ]
        params = {"A_max": a_max, "t_cycle": t_cycle, "t_peak": t_peak}
        
    return {
        "profile": profile,
        "interpolate": interp,
        "extend": extend,
        "points": points,
        "parameters": params
    }


def build_simulation_queue(mode, num_sims=None, seed=None):
    """
    Constructs the exact list of simulation specifications based on the selected mode.
    Returns:
      queue: list of dicts: {"params": dict, "load_curve_data": dict or None, "mode": str}
      details: summary dict for pre-flight logging
    """
    queue = []
    
    if mode == "grid":
        param_names = list(GRID_PARAMETERS.keys())
        param_axes = [expand_parameter_axis(k, GRID_PARAMETERS[k]) for k in param_names]
        mat_combos = list(itertools.product(*param_axes))
        
        if GRID_INCLUDE_LOAD_CURVE:
            lc_profiles = GRID_LOAD_CURVE.get("profiles", ["ramp_and_hold"])
            lc_amps = GRID_LOAD_CURVE.get("amplitudes", [1.0])
            lc_interps = GRID_LOAD_CURVE.get("interpolations", ["LINEAR"])
            lc_combos = list(itertools.product(lc_profiles, lc_amps, lc_interps))
            
            for m_combo in mat_combos:
                m_dict = dict(zip(param_names, m_combo))
                for prof, amp, interp in lc_combos:
                    lc_data = build_deterministic_load_curve(prof, amp, interp)
                    queue.append({"params": m_dict, "load_curve_data": lc_data, "mode": "grid"})
        else:
            for m_combo in mat_combos:
                m_dict = dict(zip(param_names, m_combo))
                queue.append({"params": m_dict, "load_curve_data": None, "mode": "grid"})
                
        details = {
            "mode": "grid",
            "parameters": GRID_PARAMETERS,
            "load_curve_included": GRID_INCLUDE_LOAD_CURVE,
            "total_runs": len(queue)
        }
        return queue, details
        
    elif mode == "random":
        count = num_sims if num_sims is not None else NUM_SIMULATIONS
        s_seed = seed if seed is not None else RANDOM_SEED
        for i in range(count):
            sampled = sample_parameters(VARIED_PARAMETERS, i + 1, s_seed)
            lc_data = sample_load_curve(i + 1, s_seed, LOAD_CURVE_CONFIG) if ENABLE_VARYING_LOAD_CURVES else None
            queue.append({"params": sampled, "load_curve_data": lc_data, "mode": "random"})
            
        details = {
            "mode": "random",
            "parameters": VARIED_PARAMETERS,
            "load_curve_included": ENABLE_VARYING_LOAD_CURVES,
            "total_runs": len(queue)
        }
        return queue, details
        
    elif mode == "explicit_list":
        for entry in EXPLICIT_RUNS:
            params = {k: v for k, v in entry.items() if k != "load_curve"}
            lc_spec = entry.get("load_curve")
            lc_data = None
            if lc_spec is not None:
                prof = lc_spec.get("profile", "ramp_and_hold")
                amp = lc_spec.get("amplitude", 1.0)
                interp = lc_spec.get("interpolate", "LINEAR")
                lc_data = build_deterministic_load_curve(prof, amp, interp)
            queue.append({"params": params, "load_curve_data": lc_data, "mode": "explicit_list"})
            
        details = {
            "mode": "explicit_list",
            "explicit_count": len(EXPLICIT_RUNS),
            "load_curve_included": any(e.get("load_curve") is not None for e in EXPLICIT_RUNS),
            "total_runs": len(queue)
        }
        return queue, details
        
    else:
        raise ValueError(f"Unrecognized mode: {mode}")


def inject_parameters(template_path, sampled_params, output_path, load_curve_data=None):
    """Inject sampled constitutive parameters and dynamic load curve into template .feb XML."""
    tree = ET.parse(template_path)
    root = tree.getroot()
    
    # Ensure VTK output is configured
    plotfile = root.find(".//plotfile")
    if plotfile is not None:
        plotfile.set("type", "vtk")
        
    # Inject material constitutive parameters
    for param, val in sampled_params.items():
        elem = root.find(f".//{param}")
        if elem is not None:
            elem.text = str(val)
        else:
            print(f"Warning: Element <{param}> not found in template.")
            
    # Inject load curve if specified
    if load_curve_data is not None:
        lc = root.find(".//LoadData/load_controller")
        if lc is not None:
            interp_elem = lc.find("interpolate")
            if interp_elem is not None:
                interp_elem.text = load_curve_data["interpolate"]
            extend_elem = lc.find("extend")
            if extend_elem is not None:
                extend_elem.text = load_curve_data["extend"]
            pts_elem = lc.find("points")
            if pts_elem is not None:
                pts_elem.clear()
                for t, v in load_curve_data["points"]:
                    pt = ET.SubElement(pts_elem, "pt")
                    pt.text = f"{t},{v}"
            
    tree.write(output_path, xml_declaration=True, encoding="ISO-8859-1")


def run_solver(solver_path, feb_file, work_dir):
    """Execute FEBio solver in the target directory and check exit status."""
    cmd = [solver_path, "-i", feb_file]
    t0 = time.time()
    
    try:
        proc = subprocess.run(
            cmd,
            cwd=work_dir,
            capture_output=True,
            text=True
        )
        elapsed = round(time.time() - t0, 2)
        
        log_file = os.path.join(work_dir, "febio_execution.log")
        with open(log_file, "w", encoding="utf-8") as f:
            f.write("Command: " + " ".join(cmd) + "\n")
            f.write(f"Elapsed: {elapsed}s\n")
            f.write(f"Exit code: {proc.returncode}\n\n")
            f.write(proc.stdout)
            if proc.stderr:
                f.write("\nSTDERR:\n" + proc.stderr)
                
        normal_term = (
            "NORMAL TERMINATION" in proc.stdout or
            "N O R M A L   T E R M I N A T I O N" in proc.stdout
        )
        
        if proc.returncode == 0 and normal_term:
            return True, elapsed, "Normal Termination"
        return False, elapsed, f"Exit code {proc.returncode}"
        
    except Exception as exc:
        return False, round(time.time() - t0, 2), str(exc)


def main():
    parser = argparse.ArgumentParser(
        description="Parametric FEBio dataset generator supporting grid sweeps, random sampling, and explicit recipes."
    )
    parser.add_argument(
        "--mode",
        choices=["grid", "random", "explicit_list"],
        default=None,
        help="Sampling mode (overrides config.SAMPLING_MODE)."
    )
    parser.add_argument(
        "--num-sims",
        type=int,
        default=None,
        help="Number of simulations to generate in random mode."
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        default=OVERWRITE_EXISTING,
        help="Start from sim_001 instead of resuming from the next index."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Bypass safeguard threshold if planned simulations exceed limit."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print planned simulations and queue without running solver."
    )
    args = parser.parse_args()
    
    # -------------------------------------------------------------
    # 1. Mode Validation and Single-Mode Enforcement
    # -------------------------------------------------------------
    active_mode = args.mode if args.mode is not None else SAMPLING_MODE
    if active_mode not in VALID_MODES:
        sys.exit(
            f"Error: Invalid mode '{active_mode}'. Allowed choices: {sorted(list(VALID_MODES))}"
        )
        
    if not os.path.exists(BASE_TEMPLATE_PATH):
        sys.exit(f"Error: Base template not found at {BASE_TEMPLATE_PATH}")
        
    os.makedirs(DATASET_DIR, exist_ok=True)
    
    # -------------------------------------------------------------
    # 2. Build Simulation Queue & Apply Failsafes
    # -------------------------------------------------------------
    queue, details = build_simulation_queue(active_mode, num_sims=args.num_sims)
    total_planned = len(queue)
    
    if total_planned == 0:
        sys.exit("Error: Simulation queue is empty. Check parameter ranges or recipe lists in config.py.")
        
    # Prevent grid sweep from exceeding planned run threshold
    if active_mode == "grid" and total_planned > GRID_MAX_SIMS_SAFEGUARD and not args.force:
        sys.exit(
            f"Failsafe Triggered: Planned grid size ({total_planned} runs) exceeds safeguard threshold "
            f"({GRID_MAX_SIMS_SAFEGUARD}).\nTo proceed intentionally, re-run with --force or adjust step sizes."
        )
        
    # Determine start and end indices
    if args.overwrite:
        start_idx = 1
    else:
        start_idx = get_next_sim_index(DATASET_DIR)
        
    end_idx = start_idx + total_planned - 1
    
    # -------------------------------------------------------------
    # 3. Print Pre-Flight Verification Banner
    # -------------------------------------------------------------
    lc_status = (
        "ACTIVE (Discrete profiles/amplitudes)" if (active_mode == "grid" and GRID_INCLUDE_LOAD_CURVE)
        else ("ACTIVE (Randomized dynamic profiles)" if (active_mode == "random" and ENABLE_VARYING_LOAD_CURVES)
        else "FIXED (Baseline 1.0 ramp-and-hold excitation)")
    )
    
    print("=" * 80)
    print("  FEBio Parametric Generation - Pre-Flight Check")
    print("=" * 80)
    print(f"  [Active Sampling Mode] : {active_mode.upper()}")
    print(f"  [Total Runs Planned]   : {total_planned} simulations")
    print(f"  [Execution Range]      : sim_{start_idx:03d} to sim_{end_idx:03d} "
          f"({'OVERWRITE sim_001' if args.overwrite else 'APPEND/RESUME'})")
    print(f"  [Load Curve Mode]      : {lc_status}")
    if active_mode == "grid":
        print(f"  [Grid Axes]            : {GRID_PARAMETERS}")
    elif active_mode == "random":
        print(f"  [Sampled Intervals]    : {list(VARIED_PARAMETERS.keys())}")
    print("=" * 80 + "\n")
    
    if args.dry_run:
        print("[DRY-RUN] Planned simulation queue preview:")
        for idx_offset, item in enumerate(queue):
            curr_sim_id = f"sim_{start_idx + idx_offset:03d}"
            p_str = ", ".join(f"{k}={v}" for k, v in item["params"].items())
            lc_str = (
                f"{item['load_curve_data']['profile']} (Amax={item['load_curve_data']['parameters']['A_max']})"
                if item["load_curve_data"] else "baseline (1.0 ramp-and-hold)"
            )
            print(f"  {curr_sim_id}: {p_str} | LC: {lc_str}")
        print("\n[DRY-RUN] Completed. Exiting without modifying files.")
        return
        
    # -------------------------------------------------------------
    # 4. Simulation Execution Loop
    # -------------------------------------------------------------
    records = []
    
    for idx_offset, item in enumerate(queue):
        i = start_idx + idx_offset
        sim_id = f"sim_{i:03d}"
        sim_dir = os.path.join(DATASET_DIR, sim_id)
        os.makedirs(sim_dir, exist_ok=True)
        
        sampled = item["params"]
        load_curve_data = item["load_curve_data"]
        
        param_desc = ", ".join(f"{k}={v}" for k, v in sampled.items())
        lc_desc = (
            f"LC: {load_curve_data['profile']} ({load_curve_data['interpolate']}, "
            f"Amax={load_curve_data['parameters']['A_max']})"
            if load_curve_data else "LC: default (baseline)"
        )
        print(f"[{idx_offset + 1}/{total_planned}] {sim_id} ({active_mode}): {param_desc} | {lc_desc}")
        
        feb_name = f"{sim_id}.feb"
        feb_path = os.path.join(sim_dir, feb_name)
        inject_parameters(BASE_TEMPLATE_PATH, sampled, feb_path, load_curve_data=load_curve_data)
        
        ok, solve_time, status_msg = run_solver(FEBIO_SOLVER_PATH, feb_name, sim_dir)
        print(f"       Solver: {status_msg} ({solve_time}s)")
        
        vtk_files = glob.glob(os.path.join(sim_dir, "*.vtk"))
        nodal_count, elem_count = 0, 0
        
        if ok and vtk_files:
            extract_input_parameters(feb_path, sim_dir)
            build_timeseries_dataset(sim_dir, sim_dir, feb_path)
            
            nodal_csv = os.path.join(sim_dir, "nodal_timeseries.csv")
            if os.path.exists(nodal_csv):
                nodal_count = sum(1 for _ in open(nodal_csv)) - 1
            elem_csv = os.path.join(sim_dir, "element_timeseries.csv")
            if os.path.exists(elem_csv):
                elem_count = sum(1 for _ in open(elem_csv)) - 1
                
            print(f"       Extracted: {nodal_count} nodes, {elem_count} elements across {len(vtk_files)} timesteps.")
        else:
            print("       Extraction skipped (solver did not complete normally or missing VTKs).")
            
        rec = {
            "sim_id": sim_id,
            "sampling_mode": active_mode,
            "status": "COMPLETED" if ok else "FAILED",
            **sampled
        }
        if load_curve_data:
            rec["lc_profile"] = load_curve_data["profile"]
            rec["lc_interp"] = load_curve_data["interpolate"]
            rec["lc_extend"] = load_curve_data["extend"]
            rec["lc_Amax"] = load_curve_data["parameters"].get("A_max", 1.0)
        else:
            rec["lc_profile"] = "ramp_and_hold (baseline)"
            rec["lc_interp"] = "LINEAR"
            rec["lc_extend"] = "CONSTANT"
            rec["lc_Amax"] = 1.0
            
        rec.update({
            "execution_time_sec": solve_time,
            "vtk_count": len(vtk_files),
            "nodal_rows": nodal_count,
            "element_rows": elem_count,
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "folder": os.path.relpath(sim_dir, os.path.dirname(DATASET_DIR)),
            "_load_curve_data": load_curve_data
        })
        records.append(rec)
        
    demo_root = os.path.abspath(os.path.join(DATASET_DIR, ".."))
    
    # -------------------------------------------------------------
    # 5. Update CSV Manifest (Append or Overwrite)
    # -------------------------------------------------------------
    csv_path = os.path.join(demo_root, "dataset_manifest.csv")
    csv_records = [{k: v for k, v in r.items() if k != "_load_curve_data"} for r in records]
    df_new = pd.DataFrame(csv_records)
    
    if not args.overwrite and os.path.exists(csv_path):
        df_old = pd.read_csv(csv_path)
        if "sampling_mode" not in df_old.columns:
            df_old["sampling_mode"] = "random (legacy)"
        if "lc_profile" not in df_old.columns:
            df_old["lc_profile"] = "ramp_and_hold (baseline)"
            df_old["lc_interp"] = "LINEAR"
            df_old["lc_extend"] = "CONSTANT"
            df_old["lc_Amax"] = 1.0
        else:
            df_old["lc_profile"] = df_old["lc_profile"].fillna("ramp_and_hold (baseline)")
            df_old["lc_interp"] = df_old["lc_interp"].fillna("LINEAR")
            df_old["lc_extend"] = df_old["lc_extend"].fillna("CONSTANT")
            df_old["lc_Amax"] = df_old["lc_Amax"].fillna(1.0)
            
        df_old = df_old[~df_old["sim_id"].isin(df_new["sim_id"])]
        df_manifest = pd.concat([df_old, df_new], ignore_index=True)
    else:
        df_manifest = df_new
        
    df_manifest.to_csv(csv_path, index=False)
    
    # -------------------------------------------------------------
    # 6. Update JSON Manifest (Merge or Overwrite)
    # -------------------------------------------------------------
    json_path = os.path.join(demo_root, "dataset_manifest.json")
    
    if not args.overwrite and os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    else:
        manifest = {
            "dataset_info": {
                "created_at": datetime.datetime.now().isoformat(),
                "base_template": os.path.basename(BASE_TEMPLATE_PATH),
                "constant_parameters": CONSTANT_PARAMETERS
            },
            "simulations": {}
        }
        
    manifest["dataset_info"]["sampling_mode"] = active_mode
    manifest["dataset_info"]["grid_parameters"] = GRID_PARAMETERS
    manifest["dataset_info"]["random_parameters"] = VARIED_PARAMETERS
    manifest["dataset_info"]["last_updated"] = datetime.datetime.now().isoformat()
    
    for r in records:
        entry = {
            "status": r["status"],
            "sampling_mode": r["sampling_mode"],
            "parameters": {k: r[k] for k in ["c1", "Tmax", "ca0"] if k in r},
            "folder": r["folder"],
            "files": {
                "feb_file": f"{r['sim_id']}.feb",
                "log_file": f"{r['sim_id']}.log",
                "solver_log": "febio_execution.log",
                "nodal_csv": "nodal_timeseries.csv",
                "element_csv": "element_timeseries.csv",
                "metadata_json": "simulation_metadata.json",
                "vtk_count": r["vtk_count"]
            },
            "solve_time_sec": r["execution_time_sec"]
        }
        lc = r.get("_load_curve_data")
        if lc:
            entry["load_curve"] = {
                "profile": lc["profile"],
                "interpolate": lc["interpolate"],
                "extend": lc["extend"],
                "parameters": lc["parameters"],
                "points": lc["points"]
            }
        manifest["simulations"][r["sim_id"]] = entry
        
    manifest["dataset_info"]["total_simulations"] = len(manifest["simulations"])
    manifest["dataset_info"]["successful_simulations"] = sum(
        1 for s in manifest["simulations"].values() if s["status"] == "COMPLETED"
    )
    
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=4)
        
    print(f"\nManifests updated:")
    print(f" - {csv_path} ({len(df_manifest)} total runs recorded)")
    print(f" - {json_path}")
    print("\nBatch Summary:")
    summary_cols = ["sim_id", "sampling_mode", "status"] + [
        k for k in ["c1", "Tmax", "ca0"] if k in df_new.columns
    ] + ["lc_profile", "lc_interp", "lc_Amax", "vtk_count", "execution_time_sec"]
    print(df_new[summary_cols].to_string(index=False))


if __name__ == "__main__":
    main()
