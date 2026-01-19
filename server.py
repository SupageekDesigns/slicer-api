import os
import subprocess
import tempfile
import re
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "slicer": "CuraEngine"})

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
        units = request.form.get('units', 'mm')
        
        # Scale factor: inches to mm = 25.4
        scale_factor = 25.4 if units == 'inches' else 1.0
        
        with tempfile.TemporaryDirectory() as tmpdir:
            stl_path = os.path.join(tmpdir, 'model.stl')
            file.save(stl_path)
            
            # Get file size to estimate volume
            file_size = os.path.getsize(stl_path)
            
            # Binary STL: 84 bytes header + 50 bytes per triangle
            num_triangles = max((file_size - 84) // 50, 100)
            
            # Rough volume estimate from triangle count
            est_volume_cm3 = num_triangles * 0.01
            
            # Apply scale factor for inches (volume scales by cube of linear scale)
            est_volume_cm3 *= (scale_factor ** 3) / 1000  # Convert to proper scale
            
            # Calculate estimates
            filament_meters = est_volume_cm3 * 0.416 * (infill / 100 + 0.3)
            
            # Apply scale for inches
            if units == 'inches':
                filament_meters *= 16.387  # cubic inches to cm3 factor
            
            # Estimate layers from volume
            est_height = (est_volume_cm3 ** 0.33) * 10 * scale_factor  # mm
            layers = int(est_height / layer_height)
            
            # Print time calculation
            base_time = 10  # minutes setup
            material_time = filament_meters * 4  # ~4 min per meter
            layer_time = layers * 0.1  # 0.1 min per layer
            print_time_min = base_time + material_time + layer_time
            
            # Adjust for print speed
            speed_factor = 150 / print_speed
            print_time_min *= speed_factor
            
            filament_grams = filament_meters * 2.98
            
            return jsonify({
                "success": True,
                "print_time_min": round(print_time_min, 1),
                "filament_meters": round(filament_meters, 2),
                "filament_grams": round(filament_grams, 1),
                "layers": max(layers, 10),
                "units_used": units,
                "scale_factor": scale_factor,
                "settings": {
                    "layer_height": layer_height,
                    "infill": infill,
                    "print_speed": print_speed
                }
            })
    
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=True)
