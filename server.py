import os
import tempfile
import struct
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
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

def send_email(to_email, subject, body):
    smtp_user = os.environ.get('SMTP_USER')
    smtp_pass = os.environ.get('SMTP_PASS')
    if not smtp_user or not smtp_pass:
        print("SMTP not configured")
        return False
    msg = MIMEMultipart()
    msg['From'] = smtp_user
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))
    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, to_email, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        print(f"Email error: {e}")
        return False

@app.route('/', methods=['GET'])
def home():
    return jsonify({"status": "running", "service": "SupaGEEK Slicer API"})

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"})

@app.route('/submit-quote', methods=['POST'])
def submit_quote():
    try:
        data = request.json
        customer = data.get('customer', {})
        name = customer.get('name', 'Unknown')
        email = customer.get('email', 'No email')
        phone = customer.get('phone', '')
        company = customer.get('company', '')
        notes = data.get('notes', '')
        quote = data.get('quote', {})
        parts = quote.get('parts', [])
        grand_total = quote.get('grandTotal', 0)
        
        parts_text = ""
        for i, p in enumerate(parts, 1):
            parts_text += f"""
Part {i}: {p.get('fileName', 'Unknown')}
  Dimensions: {p.get('width', 0):.1f} x {p.get('depth', 0):.1f} x {p.get('height', 0):.1f} mm
  Material: {p.get('materialId', 'N/A').upper()} | Color: {p.get('colorId', 'N/A')}
  Quantity: {p.get('quantity', 1)} | Infill: {p.get('infillPercent', '15')}% ({p.get('infillPattern', 'grid')})
  Lead Time: {p.get('leadTimeId', 'standard')}
  Supports: {'Yes' if p.get('addSupports') else 'No'} | Removal: {'Yes' if p.get('removeSupports') else 'No'}
  Finishing: Sanding={'Yes' if p.get('sanding') else 'No'}, Primer={'Yes' if p.get('primer') else 'No'}, Clearcoat={'Yes' if p.get('clearcoat') else 'No'}, Paint={'Yes' if p.get('painting') else 'No'}
  Subtotal: ${p.get('quoteTotal', 0):.2f}
"""
        
        body = f"""NEW 3D PRINT QUOTE REQUEST
{'='*40}

CUSTOMER
Name: {name}
Email: {email}
Phone: {phone}
Company: {company}

PARTS
{parts_text}
GRAND TOTAL: ${grand_total:.2f}

NOTES: {notes if notes else 'None'}
"""
        
        notify = os.environ.get('NOTIFY_EMAIL', 'sales@supageekdesigns.com')
        send_email(notify, f"Quote Request: {name} - ${grand_total:.2f}", body)
        return jsonify({"success": True})
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/slice', methods=['POST'])
def slice_model():
    try:
        if 'file' not in request.files:
            return jsonify({"success": False, "error": "No file"}), 400
        file = request.files['file']
        print_speed = int(request.form.get('print_speed', '120'))
        infill_speed = int(request.form.get('infill_speed', '180'))
        wall_speed = int(request.form.get('wall_speed', '150'))
        layer_height = float(request.form.get('layer_height', '0.16'))
        wall_count = int(request.form.get('wall_count', '2'))
        top_layers = int(request.form.get('top_layers', '6'))
        bottom_layers = int(request.form.get('bottom_layers', '4'))
        infill = int(request.form.get('infill', '15'))
        support = request.form.get('support', 'everywhere')
        adhesion = request.form.get('adhesion', 'none')
        filament_diameter = float(request.form.get('filament_diameter', '1.75'))
        units = request.form.get('units', 'mm')
        scale = float(request.form.get('scale', '100')) / 100.0
        
        with tempfile.TemporaryDirectory() as tmpdir:
            stl_path = os.path.join(tmpdir, 'model.stl')
            file.save(stl_path)
            volume_mm3, height_mm = parse_stl_volume(stl_path)
            volume_mm3 *= (scale ** 3)
            height_mm *= scale
            if units == 'inches':
                volume_mm3 *= (25.4 ** 3)
                height_mm *= 25.4
            volume_cm3 = volume_mm3 / 1000
            layers = max(int(height_mm / layer_height), 10)
            wall_volume = volume_cm3 * 0.15 * wall_count
            solid_volume = volume_cm3 * 0.1 * (top_layers + bottom_layers) / 10
            infill_volume = volume_cm3 * 0.75 * (infill / 100)
            support_mult = 1.25 if support == 'everywhere' else 1.1 if support == 'buildplate' else 1.0
            adhesion_add = 5 if adhesion == 'raft' else 2 if adhesion == 'brim' else 0.5 if adhesion == 'skirt' else 0
            total_volume = (wall_volume + solid_volume + infill_volume) * support_mult
            filament_area = 3.14159 * (filament_diameter/2/10)**2
            filament_meters = (total_volume / filament_area) / 100 + adhesion_add
            avg_speed = (print_speed + infill_speed + wall_speed) / 3
            speed_factor = 150 / avg_speed
            layer_factor = 0.2 / layer_height
            print_time_min = (104.7 + filament_meters * 3.89) * speed_factor * layer_factor + 6.47
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
