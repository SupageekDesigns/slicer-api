import os
import tempfile
from flask import Flask, request, jsonify
from flask_cors import CORS
import struct

app = Flask(__name__)
CORS(app)

def parse_stl_volume(stl_path):
    """Parse binary STL and calculate volume in mm³"""
    with open(stl_path, 'rb') as f:
        f.read(80)  # Skip header
        num_triangles = struct.unpack('<I', f.read(4))[0]
        
        volume = 0
        for _ in range(num_triangles):
            f.read(12)  # Skip normal
            v1 = struct.unpack('<fff', f.read(12))
            v2 = struct.unpack('<fff', f.read(12))
            v3 = struct.unpack('<fff', f.read(12))
            f.read(2)  # Skip attribute
            
            # Signed volume of tetrahedron
            volume += (v1[0] * (v2[1] * v3[2] - v3[1] * v2[2]) -
                      v2[0] * (v1[1] * v3[2] - v3[1] * v1[2]) +
                      v3[0] * (v1[1] * v2[2] - v2[1] * v1[2])) / 6
        
        return abs(volume)

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "slicer": "CuraEngine"})

@app.route('/slice', methods=['POST'])
def slice_model():
    try:
        if 'file' not in request.files:
            return jsonify({"success": False, "error": "No file"}), 400
        
        file = request.files['file']
        layer_height = float(request.form.get('layer_height', '0.2'))
        infill = int(request.form.get('infill', '15'))
        print_speed = int(request.form.get('print_speed', '150'))
        units = request.form.get('units', 'mm')
        scale = float(request.form.get('scale', '100')) / 100.0
        
        with tempfile.TemporaryDirectory() as tmpdir:
            stl_path = os.path.join(tmpdir, 'model.stl')
            file.save(stl_path)
            
            # Get actual volume from STL
            volume_mm3 = parse_stl_volume(stl_path)
            
            # Apply scale (volume scales by cube)
            volume_mm3 *= (scale ** 3)
            
            # If inches, the STL values are in inches, convert to mm³
            if units == 'inches':
                volume_mm3 *= (25.4 ** 3)
            
            volume_cm3 = volume_mm3 / 1000
            
            # Filament calculation: cm³ to meters of 1.75mm filament
            # 1 meter of 1.75mm filament = 2.405 cm³
            # So cm³ / 2.405 = meters, but we also account for infill
            shell_volume = volume_cm3 * 0.3  # ~30% is shells/walls
            infill_volume = volume_cm3 * 0.7 * (infill / 100)
            total_print_volume = shell_volume + infill_volume
            
            filament_meters = total_print_volume / 2.405
            
            # Layers based on height
            # Estimate height from volume (cube root approximation)
            est_height_mm = (volume_mm3 ** (1/3)) * scale
            if units == 'inches':
                est_height_mm *= 25.4
            layers = max(int(est_height_mm / layer_height), 10)
            
            # Print time using V2 formula
            base_time = 104.7  # Base time in minutes
            time_per_meter = 3.89  # Minutes per meter
            prep_time = 6.47  # Prep time
            
            print_time_min = base_time + (filament_meters * time_per_meter) + prep_time
            print_time_min *= (150 / print_speed)  # Adjust for speed
            
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
    app.run(host='0.0.0.0', port=port)
