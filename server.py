import os
import tempfile
import struct
import smtplib
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# File to store materials (persists on Railway)
MATERIALS_FILE = "materials.json"

def load_materials():
    if os.path.exists(MATERIALS_FILE):
        with open(MATERIALS_FILE, 'r') as f:
            return json.load(f)
    return {"fdm": [], "sla": []}

def save_materials(data):
    with open(MATERIALS_FILE, 'w') as f:
        json.dump(data, f)

@app.route('/materials', methods=['GET'])
def get_materials():
    return jsonify(load_materials())

@app.route('/materials', methods=['POST'])
def update_materials():
    data = request.get_json()
    save_materials(data)
    return jsonify({"success": True})

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

@app.route('/')
def home():
    return jsonify({"status": "ok", "service": "SupaGEEK Slicer API"})

@app.route('/health')
def health():
    return jsonify({"status": "healthy"})

@app.route('/slice', methods=['POST'])
def slice_stl():
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400
    file = request.files['file']
    if not file.filename.lower().endswith('.stl'):
        return jsonify({"error": "File must be an STL"}), 400
    with tempfile.NamedTemporaryFile(delete=False, suffix='.stl') as tmp:
        file.save(tmp.name)
        try:
            volume, height = parse_stl_volume(tmp.name)
            volume_cm3 = volume / 1000
            filament_meters = volume_cm3 * 0.4
            print_time_min = filament_meters * 12
            return jsonify({
                "success": True,
                "volume_mm3": round(volume, 2),
                "volume_cm3": round(volume_cm3, 2),
                "height_mm": round(height, 2),
                "filament_meters": round(filament_meters, 2),
                "filament_grams": round(filament_meters * 2.98, 1),
                "print_time_min": round(print_time_min, 1),
                "layers": int(height / 0.2)
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:
            os.unlink(tmp.name)

@app.route('/submit-quote', methods=['POST'])
def submit_quote():
    data = request.get_json()
    notify_email = os.environ.get('NOTIFY_EMAIL', 'sales@supageekdesigns.com')
    subject = f"New Quote Request: {data.get('customerName', 'Unknown')} - ${data.get('grandTotal', 0):.2f}"
    body = f"""
NEW 3D PRINT QUOTE REQUEST
{'='*40}

CUSTOMER INFORMATION
Name: {data.get('customerName', 'N/A')}
Email: {data.get('customerEmail', 'N/A')}
Phone: {data.get('customerPhone', 'N/A')}
Company: {data.get('customerCompany', 'N/A')}

QUOTE DETAILS
Grand Total: ${data.get('grandTotal', 0):.2f}
Parts: {data.get('partCount', 0)}

NOTES
{data.get('notes', 'None')}

---
Submitted via SupaGEEK Quote System
"""
    email_sent = send_email(notify_email, subject, body)
    return jsonify({"success": True, "email_sent": email_sent})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
