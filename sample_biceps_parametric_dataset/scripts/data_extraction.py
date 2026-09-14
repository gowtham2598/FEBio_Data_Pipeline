import re
import json
"""
Data Extraction Script for FEBio Biomechanics Simulations.

Extracts nodal and element state variables across sequential VTK mesh timesteps
and exports tabular CSV datasets and JSON metadata for downstream Machine Learning models.
"""

import os
import glob
import pyvista as pv
import pandas as pd
import numpy as np
import xml.etree.ElementTree as ET
from scipy.interpolate import interp1d


def extract_activation_curve(feb_file_path, total_steps):
    """
    Parses the FEBio input (.feb) XML file to extract the simulation step size,
    load curve points, and boundary extension rule.
    """
    tree = ET.parse(feb_file_path)
    root = tree.getroot()
    
    # Extract simulation step size (defaults to 0.1 s if unspecified)
    step_size_elem = root.find('.//step_size')
    step_size = float(step_size_elem.text) if step_size_elem is not None else 0.1
    
    times = []
    values = []
    extend_type = "CONSTANT"
    
    load_data = root.find('LoadData')
    if load_data is not None:
        controller = load_data.find('load_controller')
        if controller is not None:
            # Validate controller configuration and interpolation type
            ctrl_type = controller.get('type')
            if ctrl_type == "math":
                print("\nWARNING: 'math' load controllers are currently unsupported. Returning zero array.")
                return np.zeros(total_steps)
                
            interp_elem = controller.find('interpolate')
            if interp_elem is not None and interp_elem.text:
                interp_type = interp_elem.text.strip().upper()
                if interp_type not in ["LINEAR", "STEP", "SMOOTH"]:
                    print(f"\nWARNING: Interpolation type '{interp_elem.text}' is not explicitly supported (expected LINEAR, STEP, or SMOOTH).")
                    print("Extracted activation values may diverge from FEBio internal interpolation.")
            
            # Parse load curve boundary extension rule
            extend_elem = controller.find('extend')
            if extend_elem is not None and extend_elem.text:
                extend_type = extend_elem.text.strip().upper()
                
            points = controller.find('points')
            if points is not None:
                for pt in points.findall('pt'):
                    t, v = map(float, pt.text.split(','))
                    times.append(t)
                    values.append(v)
                
    if not times:
        return np.zeros(total_steps)
        
    times = np.array(times)
    values = np.array(values)
    actual_times = np.arange(total_steps) * step_size
    
    # Compute period and value bounds for cyclic extension rules
    t_min, t_max = times[0], times[-1]
    v_min, v_max = values[0], values[-1]
    cycle_duration = t_max - t_min if t_max > t_min else 1.0
    
    # Determine 1D interpolation scheme matching FEBio
    if interp_type == "SMOOTH" and len(times) >= 4:
        spline_kind = 'cubic'
    elif interp_type == "SMOOTH" and len(times) == 3:
        spline_kind = 'quadratic'
    elif interp_type == "STEP":
        spline_kind = 'previous'
    else:
        spline_kind = 'linear'
        
    base_func = interp1d(times, values, kind=spline_kind, bounds_error=False, fill_value="extrapolate")
    
    # Apply boundary extension rules and ensure non-negative activation
    if extend_type == "CONSTANT":
        activation_func = interp1d(times, values, kind=spline_kind, bounds_error=False, fill_value=(v_min, v_max))
        return np.clip(activation_func(actual_times), 0.0, None)
        
    elif extend_type == "EXTRAPOLATE":
        return np.clip(base_func(actual_times), 0.0, None)
        
    elif extend_type == "REPEAT":
        t_eval = np.where(actual_times > t_max, t_min + (actual_times - t_min) % cycle_duration, actual_times)
        t_eval = np.where(actual_times < t_min, t_min, t_eval)
        return np.clip(base_func(t_eval), 0.0, None)
        
    elif extend_type in ["REPEAT OFFSET", "REPEAT_OFFSET"]:
        cycles = np.where(actual_times > t_max, np.floor((actual_times - t_min) / cycle_duration), 0)
        t_eval = np.where(actual_times > t_max, t_min + (actual_times - t_min) % cycle_duration, actual_times)
        t_eval = np.where(actual_times < t_min, t_min, t_eval)
        return np.clip(base_func(t_eval) + cycles * (v_max - v_min), 0.0, None)
        
    else:
        activation_func = interp1d(times, values, kind=spline_kind, bounds_error=False, fill_value=(v_min, v_max))
        return np.clip(activation_func(actual_times), 0.0, None)


def build_timeseries_dataset(vtk_folder, output_folder, feb_file_path=None):
    """
    Extracts nodal and element state variables across VTK timesteps and exports
    formatted CSV datasets for downstream model training.
    """
    search_pattern = os.path.join(vtk_folder, "*.vtk")
    vtk_files = glob.glob(search_pattern)
    vtk_files.sort(key=lambda x: int(re.search(r'(\d+)\.vtk$', x).group(1)))
    
    if not vtk_files:
        print(f"Error: No VTK files found matching pattern '{search_pattern}'.")
        return

    total_steps = len(vtk_files)
    print(f"Located {total_steps} simulation timesteps. Extracting field data...")
    
    # Evaluate activation time-series across all timesteps if .feb is provided
    if feb_file_path and os.path.exists(feb_file_path):
        activation_signal = extract_activation_curve(feb_file_path, total_steps)
    else:
        activation_signal = np.zeros(total_steps)

    all_nodes_dfs = []
    all_elements_dfs = []

    for step_idx, vtk_file in enumerate(vtk_files):
        mesh = pv.read(vtk_file)
        
        # --- 1. Process Nodal Field Data ---
        node_dict = {
            'timestep': np.full(mesh.n_points, step_idx), 
            'node_id': np.arange(mesh.n_points),
            'activation': np.full(mesh.n_points, activation_signal[step_idx]),
            'coord_x': mesh.points[:, 0],
            'coord_y': mesh.points[:, 1],
            'coord_z': mesh.points[:, 2]
        }
        
        for field in mesh.point_data.keys():
            data = np.array(mesh.point_data[field])
            if data.ndim > 1:
                for c in range(data.shape[1]):
                    node_dict[f"{field}_{c}"] = data[:, c]
            else:
                node_dict[field] = data
        all_nodes_dfs.append(pd.DataFrame(node_dict))

        # --- 2. Process Element Field Data ---
        elem_dict = {
            'timestep': np.full(mesh.n_cells, step_idx), 
            'element_id': np.arange(mesh.n_cells),
            'activation': np.full(mesh.n_cells, activation_signal[step_idx])
        }
        for field in mesh.cell_data.keys():
            data = np.array(mesh.cell_data[field])
            if data.ndim > 1:
                for c in range(data.shape[1]):
                    elem_dict[f"{field}_{c}"] = data[:, c]
            else:
                elem_dict[field] = data
        all_elements_dfs.append(pd.DataFrame(elem_dict))

        if step_idx % 10 == 0 or step_idx == total_steps - 1:
            print(f"  [Progress] Processed timestep {step_idx}/{total_steps - 1}...")

    print("\nAggregating timeseries data and writing to CSV...")
    final_nodes_df = pd.concat(all_nodes_dfs, ignore_index=True)
    final_elements_df = pd.concat(all_elements_dfs, ignore_index=True)

    nodes_csv_path = os.path.join(output_folder, "nodal_timeseries.csv")
    elements_csv_path = os.path.join(output_folder, "element_timeseries.csv")

    final_nodes_df.to_csv(nodes_csv_path, index=False)
    final_elements_df.to_csv(elements_csv_path, index=False)

    print(f"\nDataset generation complete:")
    print(f" - Nodal timeseries:   {nodes_csv_path} ({len(final_nodes_df)} rows)")
    print(f" - Element timeseries: {elements_csv_path} ({len(final_elements_df)} rows)")


def extract_input_parameters(feb_file_path, output_folder):
    """
    Parses material constitutive properties, simulation control parameters,
    and load curve definitions from the .feb XML file with bidirectional load curve mapping,
    exporting structured metadata to simulation_metadata.json.
    """
    print(f"Extracting simulation metadata from: {feb_file_path}")
    tree = ET.parse(feb_file_path)
    root = tree.getroot()
    
    metadata = {}
    
    # Dictionary to track which parameters are driven by each load curve ID
    # Map structure: { "lc_id": [ {"parameter": ..., "location": ...}, ... ] }
    lc_usage_map = {}

    def record_lc_usage(lc_id, param_name, location):
        lc_id_str = str(lc_id)
        if lc_id_str not in lc_usage_map:
            lc_usage_map[lc_id_str] = []
        entry = {"parameter": param_name, "location": location}
        if entry not in lc_usage_map[lc_id_str]:
            lc_usage_map[lc_id_str].append(entry)

    # Parse material parameters and check for load curve links
    materials_dict = {}
    materials = root.find('Material')
    if materials is not None:
        for mat in materials.findall('material'):
            mat_id = mat.get('id')
            mat_name = mat.get('name', f'material_{mat_id}')
            mat_type = mat.get('type')
            mat_props = {"type": mat_type, "name": mat_name}
            
            for prop in mat:
                if len(prop) > 0:
                    nested_props = {}
                    for child in prop:
                        lc_attr = child.get('lc')
                        loc = f"Material.{mat_name}.{prop.tag}"
                        if lc_attr:
                            nested_props[child.tag] = {
                                "value": child.text.strip() if child.text else "",
                                "driven_by_load_curve": lc_attr
                            }
                            record_lc_usage(lc_attr, child.tag, loc)
                        elif child.text and child.text.strip():
                            nested_props[child.tag] = child.text.strip()
                    
                    if prop.get('lc'):
                        nested_props["driven_by_load_curve"] = prop.get('lc')
                        record_lc_usage(prop.get('lc'), prop.tag, f"Material.{mat_name}")
                        
                    mat_props[prop.tag] = nested_props
                else:
                    lc_attr = prop.get('lc')
                    loc = f"Material.{mat_name}"
                    if lc_attr:
                        mat_props[prop.tag] = {
                            "value": prop.text.strip() if prop.text else "",
                            "driven_by_load_curve": lc_attr
                        }
                        record_lc_usage(lc_attr, prop.tag, loc)
                    elif prop.text and prop.text.strip():
                        mat_props[prop.tag] = prop.text.strip()
                        
            materials_dict[f"material_{mat_id}"] = mat_props
            
    metadata["Materials"] = materials_dict

    # Parse simulation control settings
    control_dict = {}
    control = root.find('Control')
    if control is not None:
        for prop in control:
            if len(prop) > 0:
                nested_ctrl = {}
                for child in prop:
                    lc_attr = child.get('lc')
                    loc = f"Control.{prop.tag}"
                    if lc_attr:
                        nested_ctrl[child.tag] = {
                            "value": child.text.strip() if child.text else "",
                            "driven_by_load_curve": lc_attr
                        }
                        record_lc_usage(lc_attr, child.tag, loc)
                    elif child.text and child.text.strip():
                        nested_ctrl[child.tag] = child.text.strip()
                
                if prop.get('lc'):
                    nested_ctrl["driven_by_load_curve"] = prop.get('lc')
                    record_lc_usage(prop.get('lc'), prop.tag, "Control")
                    
                control_dict[prop.tag] = nested_ctrl
            else:
                lc_attr = prop.get('lc')
                loc = "Control"
                if lc_attr:
                    control_dict[prop.tag] = {
                        "value": prop.text.strip() if prop.text else "",
                        "driven_by_load_curve": lc_attr
                    }
                    record_lc_usage(lc_attr, prop.tag, loc)
                elif prop.text and prop.text.strip():
                    control_dict[prop.tag] = prop.text.strip()
                    
    metadata["Control_Settings"] = control_dict

    # Parse load curves from LoadData
    load_curves_dict = {}
    load_data = root.find('LoadData')
    if load_data is not None:
        for controller in load_data:
            lc_id = controller.get('id', '')
            lc_name = controller.get('name', '')
            lc_type = controller.get('type', '')
            
            interp_elem = controller.find('interpolate')
            interpolate = interp_elem.text.strip() if interp_elem is not None and interp_elem.text else 'LINEAR'
            
            extend_elem = controller.find('extend')
            extend = extend_elem.text.strip() if extend_elem is not None and extend_elem.text else 'CONSTANT'
            
            points = []
            points_elem = controller.find('points')
            if points_elem is not None:
                for pt in points_elem.findall('pt'):
                    if pt.text and pt.text.strip():
                        t_val, v_val = map(float, pt.text.strip().split(','))
                        points.append([t_val, v_val])
                        
            lc_entry = {
                'id': lc_id,
                'name': lc_name,
                'type': lc_type,
                'interpolate': interpolate,
                'extend': extend,
                'points': points,
                'drives_parameters': lc_usage_map.get(str(lc_id), [])
            }
            key = f'load_curve_{lc_id}' if lc_id else controller.tag
            load_curves_dict[key] = lc_entry

    metadata["Load_Curves"] = load_curves_dict

    # Export structured metadata
    json_path = os.path.join(output_folder, "simulation_metadata.json")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=4)
        
    print(f"Metadata successfully exported to: {json_path}")
    return metadata


if __name__ == "__main__":
    # Base path resolution relative to script location
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(script_dir, ".."))
    vtk_dir = os.path.join(project_root, "vtk_files")
    feb_input_file = os.path.join(project_root, "ellipsoid-muscle-contraction.feb")
    
    # 1. Extract timeseries field data from VTK files
    build_timeseries_dataset(vtk_dir, project_root, feb_input_file)
    
    # 2. Extract simulation metadata and load curves
    extract_input_parameters(feb_input_file, project_root)
