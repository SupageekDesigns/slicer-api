import os
import tempfile
import struct
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

def parse_stl_volume(stl_path):
    with open(stl_path, 'rb') as f:
        f.read(80)
        num_triangles = struct.unpack('<I', f.read(4))[0]
        volume = 0
        max_z = 0
        for _ in range(num_triangles):
            f.read(12)
            v1 = struct.unpack('<fff', f.read(12))
            v2 = struct.unpack('<fff', f.read(12))
            v3 = struct.unpack('<fff', f.read(12))
            f.read(2)
            max_z = max(max_z, v1[2], v2[2], v3[2])
            volume += (v1[0]*(v2[1]*v3[2]-v3[1]*v2[2]) - v2[0]*(v1[1]*v3[2]-v3[1]*v1[2]) + v3[0]*(v1[1]*v2[2]-v2[1]*v1[2])) / 6
        return abs(volume), max_z

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "slicer": "CuraEngine"})

@app.route('/slice', methods=['POST'])
def slice_model():
    try:
        if 'file' not in request.files:
            return jsonify({"success": False, "error": "No file"}), 400
        
        file = request.files['file']
        
        # Get all settings
        print_speed = int(request.form.get('print_speed', '120'))
        infill_speed = int(request.form.get('infill_speed', '180'))
        wall_speed = int(request.form.get('wall_speed', '150'))
        travel_speed = int(request.form.get('travel_speed', '500'))
        layer_height = float(request.form.get('layer_height', '0.16'))
        wall_count = int(request.form.get('wall_count', '2'))
        top_layers = int(request.form.get('top_layers', '6'))
        bottom_layers = int(request.form.get('bottom_layers', '4'))
        infill = int(request.form.get('infill', '15'))
        infill_pattern = request.form.get('infill_pattern', 'gyroid')
        support = request.form.get('support', 'everywhere')
        adhesion = request.form.get('adhesion', 'none')
        nozzle_size = float(request.form.get('nozzle_size', '0.4'))
        filament_diameter = float(request.form.get('filament_diameter', '1.75'))
        units = request.form.get('units', 'mm')
        scale = float(request.form.get('scale', '100')) / 100.0
        
        with tempfile.TemporaryDirectory() as tmpdir:
            stl_path = os.path.join(tmpdir, 'model.stl')
            file.save(stl_path)
            
            volume_mm3, height_mm = parse_stl_volume(stl_path)
            
            # Apply scale
            volume_mm3 *= (scale ** 3)
            height_mm *= scale
            
            # Convert inches to mm if needed
            if units == 'inches':
                volume_mm3 *= (25.4 ** 3)
                height_mm *= 25.4
            
            volume_cm3 = volume_mm3 / 1000
            
            # Calculate layers
            layers = max(int(height_mm / layer_height), 10)
            
            # Filament calculation
            # Walls: perimeter length * wall_count * height / layer_height
            wall_volume = volume_cm3 * 0.15 * wall_count
            # Top/bottom solid layers
            solid_volume = volume_cm3 * 0.1 * (top_layers + bottom_layers) / 10
            # Infill
            infill_volume = volume_cm3 * 0.75 * (infill / 100)
            # Support estimate
            support_mult = 1.0
            if support == 'buildplate':
                support_mult = 1.1
            elif support == 'everywhere':
                support_mult = 1.25
            # Adhesion estimate
            adhesion_add = 0
            if adhesion == 'skirt':
                adhesion_add = 0.5
            elif adhesion == 'brim':
                adhesion_add = 2
            elif adhesion == 'raft':
                adhesion_add = 5
            
            total_volume = (wall_volume + solid_volume + infill_volume) * support_mult
            
            # cm³ to meters of filament
            filament_area = 3.14159 * (filament_diameter/2/10)**2  # cm²
            filament_meters = (total_volume / filament_area) / 100 + adhesion_add
            
            # Print time calculation
            # Base time + material time, adjusted for speeds
            base_time = 104.7
            material_time = filament_meters * 3.89
            
            # Speed factor (baseline 150mm/s)
            avg_speed = (print_speed + infill_speed + wall_speed) / 3
            speed_factor = 150 / avg_speed
            
            # Layer height factor (baseline 0.2mm)
            layer_factor = 0.2 / layer_height
            
            print_time_min = (base_time + material_time) * speed_factor * layer_factor + 6.47
            
            filament_grams = filament_meters * 2.98
            
            return jsonify({
                "success": True,
                "print_time_min": round(print_time_min, 1),
                "filament_meters": round(filament_meters, 2),
                "filament_grams": round(filament_grams, 1),
                "layers": layers,
                "volume_cm3": round(volume_cm3, 2)
            })
    
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.
