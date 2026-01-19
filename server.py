import os
import tempfile
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
        scale = float(request.form.get('scale', '100')) / 100.0
        
        # Scale factors
        unit_scale = 25.4 if units == 'inches' else 1.0
        total_scale = unit_scale * scale
        
        with tempfile.TemporaryDirectory() as tmpdir:
            stl_path = os.path.join(tmpdir, 'model.stl')
            file.save(stl_path)
            
            file_size = os.path.getsize(stl_path)
            num_triangles = max((file_size - 84) // 50, 100)
            
            # Base volume estimate
            est_volume_cm3 = num_triangles * 0.01
            
            # Apply scale (volume scales by cube of linear scale)
            est_volume_cm3 *= (total_scale ** 3)
            
            # Filament calculation
            filament_meters = est_volume_cm3 * 0.416 * (infill / 100 + 0.3)
            
            # Height and layers
            est_height = (est_volume_cm3 ** 0.33) * 10 * total_scale
            layers = max(int(est_height / layer_height), 10)
            
            # Print time
            base_time = 10
            material_time = filament_meters * 4
            layer_time = layers * 0.1
            print_time_min = (base_time + material_time + layer_time) * (150 / print_speed)
            
            filament_grams = filament_meters * 2.98
            
            return jsonify({
                "success": True,
                "print_time_min": round(print_time_min, 1),
                "filament_meters": round(filament_meters, 2),
                "filament_grams": round(filament_grams, 1),
                "layers": layers,
                "scale_applied": total_scale
            })
    
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
