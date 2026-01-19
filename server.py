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
        "filament_grams": 0,
        "layers": 0
    }
    
    with open(gcode_path, 'r') as f:
        content = f.read()
        
        # Print time
        match = re.search(r'estimated printing time[^=]*=\s*(?:(\d+)d\s*)?(?:(\d+)h\s*)?(?:(\d+)m\s*)?(?:(\d+)s)?', content, re.IGNORECASE)
        if match:
            d = int(match.group(1) or 0)
            h = int(match.group(2) or 0)
            m = int(match.group(3) or 0)
            s = int(match.group(4) or 0)
            stats["print_time_sec"] = d * 86400 + h * 3600 + m * 60 + s
        
        # Filament mm
        match = re.search(r'filament used $$mm$$\s*=\s*([\d.]+)', content, re.IGNORECASE)
        if match:
            stats["filament_mm"] = float(match.group(1))
        
        # Filament grams
        match = re.search(r'filament used $$g$$\s*=\s*([\d.]+)', content, re.IGNORECASE)
        if match:
            stats["filament_grams"] = float(match.group(1))
        
        # Layers
        match = re.search(r'total layers count\s*=\s*(\d+)', content, re.IGNORECASE)
        if match:
            stats["layers"] = int(match.group(1))
    
    return stats

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "slicer": "PrusaSlicer 2.7.1"})

@app.route('/slice', methods=['POST'])
def slice_model():
    try:
        if 'file' not in request.files:
            return jsonify({"success": False, "error": "No file uploaded"}), 400
        
        file = request.files['file']
        if not file.filename.lower().endswith('.stl'):
            return jsonify({"success": False, "error": "File must be STL"}), 400
        
        layer_height = request.form.get('layer_height', '0.2')
        infill = request.form.get('infill', '15')
        print_speed = request.form.get('print_speed', '150')
        
        with tempfile.TemporaryDirectory() as tmpdir:
            stl_path = os.path.join(tmpdir, 'model.stl')
            gcode_path = os.path.join(tmpdir, 'model.gcode')
            
            file.save(stl_path)
            
            cmd = [
                'prusa-slicer',
                '--export-gcode',
                '--layer-height', str(layer_height),
                '--fill-density', f'{infill}%',
                '--perimeter-speed', str(print_speed),
                '--infill-speed', str(print_speed),
                '--travel-speed', '200',
                '--nozzle-diameter', '0.4',
                '--filament-diameter', '1.75',
                '--first-layer-height', '0.2',
                '--perimeters', '3',
                '--top-solid-layers', '4',
                '--bottom-solid-layers', '4',
                '--bed-shape', '0x0,256x0,256x256,0x256',
                '--center', '128,128',
                '--output', gcode_path,
                stl_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            
            if not os.path.exists(gcode_path):
                return jsonify({
                    "success": False,
                    "error": "Slicing failed",
                    "details": result.stderr
                }), 500
            
            stats = parse_gcode_stats(gcode_path)
            
            return jsonify({
                "success": True,
                "print_time_min": round(stats["print_time_sec"] / 60, 1),
                "filament_meters": round(stats["filament_mm"] / 1000, 2),
                "filament_grams": round(stats["filament_grams"], 1),
                "layers": stats["layers"],
                "settings": {
                    "layer_height": float(layer_height),
                    "infill": int(infill),
                    "print_speed": int(print_speed)
                }
            })
    
    except subprocess.TimeoutExpired:
        return jsonify({"success": False, "error": "Slicing timed out"}), 504
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
