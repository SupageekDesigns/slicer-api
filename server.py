import os
import tempfile
import struct
import smtplib
import json
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, request, jsonify
from flask_cors import CORS
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2 import service_account

app = Flask(__name__)
CORS(app)

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

def get_drive_service():
    creds_json = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON')
    if not creds_json:
        return None
    creds_info = json.loads(creds_json)
    scopes = ['https://www.googleapis.com/auth/drive']
    creds = service_account.Credentials.from_service_account_info(creds_info, scopes=scopes)
    return build('drive', 'v3', credentials=creds)

def get_or_create_folder(service, folder_name, parent_id=None):
    query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent_id:
        query += f" and '{parent_id}' in parents"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get('files', [])
    if files:
        return files[0]['id']
    meta = {'name': folder_name, 'mimeType': 'application/vnd.google-apps.folder'}
    if parent_id:
        meta['parents'] = [parent_id]
    folder = service.files().create(body=meta, fields='id').execute()
    return folder['id']

def upload_file_to_drive(service, file_bytes, file_name, folder_id=None):
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    try:
        file_meta = {'name': file_name}
        if folder_id:
            file_meta['parents'] = [folder_id]
        resumable = len(file_bytes) > 5 * 1024 * 1024
        media = MediaFileUpload(tmp_path, mimetype='application/octet-stream', resumable=resumable)
        result = service.files().create(body=file_meta, media_body=media, fields='id, webViewLink').execute()
        return result.get('id', ''), result.get('webViewLink', '')
    finally:
        os.unlink(tmp_path)

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

@app.route('/upload-batch', methods=['POST'])
def upload_batch():
    data = request.get_json()
    if not data or 'files' not in data:
        return jsonify({"error": "No files provided"}), 400

    files = data['files']
    customer_name = data.get('customerName', 'Unknown')
    customer_email = data.get('customerEmail', '')

    drive = get_drive_service()
    root_folder_id = os.environ.get('GOOGLE_DRIVE_FOLDER_ID')

    uploaded = []
    folder_id = None
    folder_link = None

    if drive:
        subfolder_name = f"{customer_name} - {customer_email}" if customer_email else customer_name
        folder_id = get_or_create_folder(drive, subfolder_name, root_folder_id)
        folder_link = f"https://drive.google.com/drive/folders/{folder_id}"

    for f in files:
        file_name = f.get('fileName', 'upload.stl')
        file_data_b64 = f.get('fileData', '')
        try:
            file_bytes = base64.b64decode(file_data_b64)
        except Exception:
            uploaded.append({"fileName": file_name, "fileId": "", "viewLink": ""})
            continue
        if drive:
            try:
                file_id, view_link = upload_file_to_drive(drive, file_bytes, file_name, folder_id)
                uploaded.append({"fileName": file_name, "fileId": file_id, "viewLink": view_link})
            except Exception as e:
                print(f"Drive upload error for {file_name}: {e}")
                uploaded.append({"fileName": file_name, "fileId": "", "viewLink": ""})
        else:
            uploaded.append({"fileName": file_name, "fileId": "", "viewLink": ""})

    return jsonify({
        "success": True,
        "files": uploaded,
        "folderId": folder_id or "",
        "folderLink": folder_link or "",
    })

@app.route('/upload-customer-files', methods=['POST'])
def upload_customer_files():
    data = request.get_json()
    if not data or 'files' not in data:
        return jsonify({"error": "No files provided"}), 400

    files = data['files']
    customer_name = data.get('customerName', 'Unknown')
    customer_email = data.get('customerEmail', '')
    customer_phone = data.get('customerPhone', '')
    notes = data.get('notes', '')

    drive = get_drive_service()
    root_folder_id = os.environ.get('GOOGLE_DRIVE_CUSTOMER_UPLOADS_FOLDER_ID')

    uploaded = []
    folder_id = None
    folder_link = None

    if drive:
        subfolder_name = f"{customer_name} - {customer_email}" if customer_email else customer_name
        folder_id = get_or_create_folder(drive, subfolder_name, root_folder_id)
        folder_link = f"https://drive.google.com/drive/folders/{folder_id}"

        if notes or customer_phone:
            notes_content = f"Customer: {customer_name}\nEmail: {customer_email}\nPhone: {customer_phone}\n\nNotes:\n{notes}"
            with tempfile.NamedTemporaryFile(delete=False, suffix='.txt', mode='w') as tmp:
                tmp.write(notes_content)
                tmp_path = tmp.name
            try:
                file_meta = {'name': 'notes.txt', 'parents': [folder_id]}
                media = MediaFileUpload(tmp_path, mimetype='text/plain')
                drive.files().create(body=file_meta, media_body=media).execute()
            except Exception as e:
                print(f"Notes upload error: {e}")
            finally:
                os.unlink(tmp_path)

    for f in files:
        file_name = f.get('fileName', 'upload')
        file_data_b64 = f.get('fileData', '')
        try:
            file_bytes = base64.b64decode(file_data_b64)
        except Exception:
            uploaded.append({"fileName": file_name, "fileId": "", "viewLink": ""})
            continue
        if drive:
            try:
                file_id, view_link = upload_file_to_drive(drive, file_bytes, file_name, folder_id)
                uploaded.append({"fileName": file_name, "fileId": file_id, "viewLink": view_link})
            except Exception as e:
                print(f"Drive upload error for {file_name}: {e}")
                uploaded.append({"fileName": file_name, "fileId": "", "viewLink": ""})
        else:
            uploaded.append({"fileName": file_name, "fileId": "", "viewLink": ""})

    return jsonify({
        "success": True,
        "files": uploaded,
        "folderId": folder_id or "",
        "folderLink": folder_link or "",
    })

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
