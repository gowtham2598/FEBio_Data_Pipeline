"""
Batch runner for parametric FEBio simulations and dataset extraction.
Supports automatic index continuation, varying load curves, and manifest appending.
"""

import os
import sys
import time
import glob
import random
import subprocess
import json
import re
import datetime
import argparse
import pandas as pd
import xml.etree.ElementTree as ET

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from config import (
    BASE_TEMPLATE_PATH,
    DATASET_DIR,
    FEBIO_SOLVER_PATH,
    NUM_SIMULATIONS,
    RANDOM_SEED,
    OVERWRITE_EXISTING,
    VARIED_PARAMETERS,
    CONSTANT_PARAMETERS,
    ENABLE_VARYING_LOAD_CURVES,
    LOAD_CURVE_CONFIG
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


def sample_parameters(varied_config, sim_index, base_seed):
    """
    Sample values uniformly within defined ranges.
    Uses base_seed + sim_index to ensure deterministic reproducibility per simulation.
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
    Produces valid points, FEBio interpolation mode, and extension rule.
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
            
    # Inject load curve if enabled
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
            f.write(f"Command: {' '.join(cmd)}\n")
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
    parser = argparse.ArgumentParser(description="Parametric FEBio dataset generator.")
    parser.add_argument("--num-sims", type=int, default=NUM_SIMULATIONS,
                        help="Number of simulations to generate in this batch.")
    parser.add_argument("--overwrite", action="store_true", default=OVERWRITE_EXISTING,
                        help="Start from sim_001 instead of resuming from the next index.")
    args = parser.parse_args()
    
    if not os.path.exists(BASE_TEMPLATE_PATH):
        sys.exit(f"Error: Base template not found at {BASE_TEMPLATE_PATH}")
        
    os.makedirs(DATASET_DIR, exist_ok=True)
    
    # Determine start index
    if args.overwrite:
        start_idx = 1
        print("Mode: Resetting dataset (starting from sim_001).")
    else:
        start_idx = get_next_sim_index(DATASET_DIR)
        if start_idx > 1:
            print(f"Mode: Resuming dataset. Detected existing runs, starting at sim_{start_idx:03d}.")
        else:
            print("Mode: Fresh run (starting at sim_001).")
            
    end_idx = start_idx + args.num_sims - 1
    print(f"Target: Generating {args.num_sims} simulations (sim_{start_idx:03d} to sim_{end_idx:03d}).\n")
    
    records = []
    
    for i in range(start_idx, end_idx + 1):
        sim_id = f"sim_{i:03d}"
        sim_dir = os.path.join(DATASET_DIR, sim_id)
        os.makedirs(sim_dir, exist_ok=True)
        
        # Sample material parameters
        sampled = sample_parameters(VARIED_PARAMETERS, i, RANDOM_SEED)
        
        # Sample load curve if enabled
        load_curve_data = None
        if ENABLE_VARYING_LOAD_CURVES:
            load_curve_data = sample_load_curve(i, RANDOM_SEED, LOAD_CURVE_CONFIG)
            
        param_desc = ", ".join(f"{k}={v}" for k, v in sampled.items())
        lc_desc = (
            f"LC: {load_curve_data['profile']} ({load_curve_data['interpolate']}, "
            f"Amax={load_curve_data['parameters']['A_max']})"
            if load_curve_data else "LC: default"
        )
        print(f"[{i - start_idx + 1}/{args.num_sims}] {sim_id}: {param_desc} | {lc_desc}")
        
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
    # Update CSV Manifest (Append or Overwrite)
    # -------------------------------------------------------------
    csv_path = os.path.join(demo_root, "dataset_manifest.csv")
    csv_records = [{k: v for k, v in r.items() if k != "_load_curve_data"} for r in records]
    df_new = pd.DataFrame(csv_records)
    
    if not args.overwrite and os.path.exists(csv_path):
        df_old = pd.read_csv(csv_path)
        # Populate missing load curve columns in existing baseline runs
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
    # Update JSON Manifest (Merge or Overwrite)
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
                "random_seed": RANDOM_SEED,
                "varied_parameters": VARIED_PARAMETERS,
                "constant_parameters": CONSTANT_PARAMETERS
            },
            "simulations": {}
        }
        
    manifest["dataset_info"]["load_curve_variation_enabled"] = ENABLE_VARYING_LOAD_CURVES
    if ENABLE_VARYING_LOAD_CURVES:
        manifest["dataset_info"]["load_curve_config"] = LOAD_CURVE_CONFIG
        
    # Merge new simulation entries
    for r in records:
        entry = {
            "status": r["status"],
            "parameters": {k: r[k] for k in VARIED_PARAMETERS.keys()},
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
    manifest["dataset_info"]["last_updated"] = datetime.datetime.now().isoformat()
    
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=4)
        
    print(f"\nManifests updated:")
    print(f" - {csv_path} ({len(df_manifest)} total runs recorded)")
    print(f" - {json_path}")
    print("\nBatch Summary:")
    summary_cols = ["sim_id", "status"] + list(VARIED_PARAMETERS.keys()) + [
        "lc_profile", "lc_interp", "lc_Amax", "vtk_count", "execution_time_sec"
    ]
    print(df_new[summary_cols].to_string(index=False))


if __name__ == "__main__":
    main()
