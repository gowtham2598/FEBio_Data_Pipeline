"""
Batch runner for parametric FEBio simulations and dataset extraction.
Supports automatic index continuation and manifest appending.
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


def inject_parameters(template_path, sampled_params, output_path):
    """Inject sampled parameter values into a template .feb XML file."""
    tree = ET.parse(template_path)
    root = tree.getroot()
    
    plotfile = root.find(".//plotfile")
    if plotfile is not None:
        plotfile.set("type", "vtk")
        
    for param, val in sampled_params.items():
        elem = root.find(f".//{param}")
        if elem is not None:
            elem.text = str(val)
        else:
            print(f"Warning: Element <{param}> not found in template.")
            
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
        
        sampled = sample_parameters(VARIED_PARAMETERS, i, RANDOM_SEED)
        param_summary = ", ".join(f"{k}={v}" for k, v in sampled.items())
        print(f"[{i - start_idx + 1}/{args.num_sims}] {sim_id}: {param_summary}")
        
        feb_name = f"{sim_id}.feb"
        feb_path = os.path.join(sim_dir, feb_name)
        inject_parameters(BASE_TEMPLATE_PATH, sampled, feb_path)
        
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
            
        records.append({
            "sim_id": sim_id,
            "status": "COMPLETED" if ok else "FAILED",
            **sampled,
            "execution_time_sec": solve_time,
            "vtk_count": len(vtk_files),
            "nodal_rows": nodal_count,
            "element_rows": elem_count,
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "folder": os.path.relpath(sim_dir, os.path.dirname(DATASET_DIR))
        })
        
    demo_root = os.path.abspath(os.path.join(DATASET_DIR, ".."))
    
    # -------------------------------------------------------------
    # Update CSV Manifest (Append or Overwrite)
    # -------------------------------------------------------------
    csv_path = os.path.join(demo_root, "dataset_manifest.csv")
    df_new = pd.DataFrame(records)
    
    if not args.overwrite and os.path.exists(csv_path):
        df_old = pd.read_csv(csv_path)
        # Avoid duplicate sim_id entries if re-run
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
        
    # Merge new simulation entries
    for r in records:
        manifest["simulations"][r["sim_id"]] = {
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
    summary_cols = ["sim_id", "status"] + list(VARIED_PARAMETERS.keys()) + ["vtk_count", "execution_time_sec"]
    print(df_new[summary_cols].to_string(index=False))


if __name__ == "__main__":
    main()
