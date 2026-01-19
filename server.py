import os
import subprocess
import tempfile
import re
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

def parse_gcode_stats(gcode_path):
    stats = {
        "print_time_sec": 0,
        "filament_mm": 0,
        "layers": 0
    }
    
    max_e = 0
    layer_count = 0
    total_time = 0
    
    with open(gcode_path, 'r') as f:
        for line in f:
            if 'E' in line and line.startswith('G1'):
                match = re.search(r'E([\d.]+)', line)
                if match:
                    e_val = float(match.group(1))
                    if e_val > max_e:
                        max_e = e_val
            
            if line.startswith(';LAYER:') or line.startswith(';LAYER_COUNT:'):
                layer_count += 1
            
            if ';TIME:' in line:
                match = re.search(r';TIME:(\d+)', line)
                if match:
                    total_time = int(match.group(1))
            
            if ';Filament used:' in line:
                match = re.search(r';Filament used:\s*([\d.]+)m', line)
                if match:
                    stats["filament_mm"] = float(match.group(1)) * 1000
    
    if stats["filament_mm"] == 0:
        stats["filament_mm"] = max_e
    
    stats["layers"] = max(layer_count, 1)
    stats["print_time_sec"] = total_time
    
    return stats

def estimate_from_volume(stl_path, layer_height, infill, print_speed):
    """Fallback estimation when CuraEngine fails"""
    try:
        file_size = os.path.getsize(stl_path)
        estimated_volume = file_size / 50
        
        filament_mm = estimated_volume * 0.4 * (infill / 100)
        layers = int(estimated_volume ** 0.33 / layer_height)
        print_time = (filament_mm / print_speed) * 0.1
        
        return {
            "print_time_sec": int(print_time * 60),
            "filament_mm": filament_mm,
            "layers": max(layers, 10)
        }
    except:
        return None

@app.route('/health', methods=['GET'])
def health():
    try:
        result = subprocess.run(['CuraEngine', '--help'], capture_output=True, timeout=5)
        return jsonify({"status": "ok", "slicer": "CuraEngine"})
    except:
        return jsonify({"status": "ok", "slicer": "Fallback"})

@app.route('/slice', methods=['POST'])
def slice_model():
    try:
        if 'file' not in request.files:
            return jsonify({"success": False, "error": "No file uploaded"}), 400
        
        file = request.files['file']
        if not file.filename.lower().endswith('.stl'):
            return jsonify({"success": False, "error": "File must be STL"}), 400
        
        layer_height = float(request.form.get('layer_height', '0.2'))
        infill = int(request.form.get('infill', '15'))
        print_speed = int(request.form.get('print_speed', '150'))
        
        with tempfile.TemporaryDirectory() as tmpdir:
            stl_path = os.path.join(tmpdir, 'model.stl')
            gcode_path = os.path.join(tmpdir, 'model.gcode')
            
            file.save(stl_path)
            
            cmd = [
                'CuraEngine', 'slice',
                '-v',
                '-o', gcode_path,
                '-s', f'layer_height={layer_height}',
                '-s', f'infill_sparse_density={infill}',
                '-s', f'speed_print={print_speed}',
                '-s', 'wall_thickness=1.2',
                '-s', 'wall_line_count=3',
                '-s', 'top_layers=4',
                '-s', 'bottom_layers=4',
                '-s', 'infill_pattern=grid',
                '-s', 'machine_width=256',
                '-s', 'machine_depth=256',
                '-s', 'machine_height=256',
                '-s', 'machine_nozzle_size=0.4',
                '-s', 'material_diameter=1.75',
                '-s', 'machine_heated_bed=true',
                '-s', 'machine_center_is_zero=false',
                '-s', 'machine_gcode_flavor=RepRap',
                '-s', 'retraction_enable=true',
                '-s', 'retraction_amount=5',
                '-s', 'retraction_speed=45',
                '-s', 'adhesion_type=skirt',
                '-l', stl_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            
            stats = None
            
            if os.path.exists(gcode_path) and os.path.getsize(gcode_path) > 100:
                stats = parse_gcode_stats(gcode_path)
            
            if not stats or stats["filament_mm"] == 0:
                stats = estimate_from_volume(stl_path, layer_height, infill, print_speed)
            
            if not stats:
                return jsonify({
                    "success": False,
                    "error": "Could not process model",
                    "stderr": result.stderr[:500] if result.stderr else ""
                }), 500
            
            filament_meters = stats["filament_mm"] / 1000
            filament_grams = filament_meters * 2.98
            
            return jsonify({
                "success": True,
                "print_time_min": round(stats["print_time_sec"] / 60, 1),
                "filament_meters": round(filament_meters, 2),
                "filament_grams": round(filament_grams, 1),
                "layers": stats["layers"],
                "settings": {
                    "layer_height": layer_height,
                    "infill": infill,
                    "print_speed": print_speed
                }
            })
    
    except subprocess.TimeoutExpired:
        return jsonify({"success": False, "error": "Slicing timed out"}), 504
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
