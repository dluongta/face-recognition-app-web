import os, shutil, base64, threading, cv2, traceback, sys, webbrowser
from threading import Timer
import numpy as np
import face_recognition
from flask import Flask, render_template, request, jsonify

# ============================================================
# CONFIG & INITIALIZATION (Tương thích PyInstaller)
# ============================================================
if getattr(sys, 'frozen', False):
    # Khi đóng gói thành file .exe
    base_dir = sys._MEIPASS
    exe_dir = os.path.dirname(sys.executable)
    app = Flask(__name__, 
                template_folder=os.path.join(base_dir, 'templates'),
                static_folder=os.path.join(base_dir, 'static'))
else:
    # Khi chạy trực tiếp qua file .py
    base_dir = os.path.abspath(".")
    exe_dir = base_dir
    app = Flask(__name__)

# Thư mục faces lưu cùng cấp với file .exe để không bị mất dữ liệu khi đóng app
FACES_DIR = os.path.join(exe_dir, "faces")
FACE_DISTANCE_THRESHOLD = 0.5
DISTANCE_DECIMALS = 3
PROCESS_SCALE = 0.25
MAX_IMAGE_SIZE = 15 * 1024 * 1024
VALID_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")

app.config["MAX_CONTENT_LENGTH"] = MAX_IMAGE_SIZE
os.makedirs(FACES_DIR, exist_ok=True)

# ============================================================
# GLOBAL DATABASE
# ============================================================
person_encodings = {}
known_face_encodings = []
known_face_names = []
database_lock = threading.RLock()

# ============================================================
# HELPER FUNCTIONS
# ============================================================
def load_known_faces():
    global person_encodings, known_face_encodings, known_face_names
    with database_lock:
        person_encodings.clear()
        known_face_encodings.clear()
        known_face_names.clear()
        print("\n========== LOAD DATABASE ==========")
        os.makedirs(FACES_DIR, exist_ok=True)
        
        for person_name in sorted(os.listdir(FACES_DIR)):
            person_folder = os.path.join(FACES_DIR, person_name)
            if not os.path.isdir(person_folder): continue
            
            encodings_for_person = []
            for filename in sorted(os.listdir(person_folder)):
                if not filename.lower().endswith(VALID_EXTENSIONS): continue
                file_path = os.path.join(person_folder, filename)
                
                try:
                    image = face_recognition.load_image_file(file_path)
                    face_locations = face_recognition.face_locations(image, model="hog")
                    
                    if len(face_locations) != 1:
                        print(f"[WARNING] Bỏ qua {person_name}/{filename} (Số khuôn mặt: {len(face_locations)})")
                        continue
                        
                    encodings = face_recognition.face_encodings(image, known_face_locations=face_locations, num_jitters=1, model="small")
                    if encodings:
                        encodings_for_person.append(encodings[0])
                        known_face_encodings.append(encodings[0])
                        known_face_names.append(person_name)
                        print(f"[OK] Đã load: {person_name}/{filename}")
                except Exception as e:
                    print(f"[ERROR] {file_path}: {e}")
                    
            if encodings_for_person:
                person_encodings[person_name] = encodings_for_person

        print(f"\nLoad xong {len(known_face_encodings)} encoding từ {len(person_encodings)} người.\n==================================\n")

def sanitize_name(name):
    if not name: return ""
    name = str(name).strip()
    for char in '<>:"/\\|?*': name = name.replace(char, "_")
    return name.strip()

def get_next_number(person_folder):
    if not os.path.exists(person_folder): return 1
    max_num = 0
    for filename in os.listdir(person_folder):
        name_part = os.path.splitext(filename)[0]
        if name_part.isdigit(): max_num = max(max_num, int(name_part))
    return max_num + 1

def decode_uploaded_image(file):
    if file is None: return None
    data = file.read()
    if not data or len(data) > MAX_IMAGE_SIZE: raise ValueError("Ảnh quá lớn hoặc không hợp lệ.")
    np_array = np.frombuffer(data, dtype=np.uint8)
    return cv2.imdecode(np_array, cv2.IMREAD_COLOR)

def calculate_confidence(distance):
    if distance is None or distance == float("inf"): return 0.0
    return max(0.0, min(100.0, (1.0 - distance) * 100.0))

def recognize_image(image):
    if image is None or image.size == 0: return []
    orig_h, orig_w = image.shape[:2]
    
    small_image = cv2.resize(image, None, fx=PROCESS_SCALE, fy=PROCESS_SCALE, interpolation=cv2.INTER_LINEAR)
    rgb_small_image = cv2.cvtColor(small_image, cv2.COLOR_BGR2RGB)
    
    face_locations = face_recognition.face_locations(rgb_small_image, model="hog")
    if not face_locations: return []
    
    face_encodings = face_recognition.face_encodings(rgb_small_image, known_face_locations=face_locations, num_jitters=1, model="small")
    results = []

    with database_lock:
        database = {name: list(encs) for name, encs in person_encodings.items()}

    for face_encoding, face_loc in zip(face_encodings, face_locations):
        best_distance = float("inf")
        best_person = None

        for person_name, encodings in database.items():
            if not encodings: continue
            distances = face_recognition.face_distance(encodings, face_encoding)
            if len(distances) == 0: continue
            min_dist = float(np.min(distances))
            if min_dist < best_distance:
                best_distance = min_dist
                best_person = person_name

        confidence = calculate_confidence(best_distance)
        name = best_person if (best_person and best_distance <= FACE_DISTANCE_THRESHOLD) else "Unknown"

        top, right, bottom, left = [max(0, int(round(coord / PROCESS_SCALE))) for coord in face_loc]
        results.append({
            "name": name,
            "confidence": round(confidence, 1),
            "distance": round(best_distance, DISTANCE_DECIMALS) if best_distance != float("inf") else None,
            "box": {
                "top": min(top, orig_h - 1), 
                "right": min(right, orig_w - 1),
                "bottom": min(bottom, orig_h - 1), 
                "left": min(left, orig_w - 1)
            }
        })
    return results

def draw_results_on_image(image, results):
    if image is None: return None
    output = image.copy()
    h, w = output.shape[:2]
    
    for res in results:
        box = res.get("box", {})
        top, right, bottom, left = box.get("top", 0), box.get("right", 0), box.get("bottom", 0), box.get("left", 0)
        name = res.get("name", "Unknown")
        confidence = res.get("confidence", 0)
        
        color = (0, 0, 255) if name == "Unknown" else (0, 180, 0)
        cv2.rectangle(output, (left, top), (right, bottom), color, 4, cv2.LINE_AA)
        
        label = f"{name} ({confidence:.1f}%)"
        font = cv2.FONT_HERSHEY_SIMPLEX
        (t_w, t_h), baseline = cv2.getTextSize(label, font, 0.8, 2)
        
        l_left = max(0, min(left, w - t_w - 20))
        l_top = max(0, top - t_h - 16) if (top - t_h - 20) >= 0 else bottom + 4
        
        cv2.rectangle(output, (l_left, l_top), (l_left + t_w + 20, l_top + t_h + 16), color, -1)
        cv2.putText(output, label, (l_left + 10, l_top + t_h + 8), font, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
        
    return output

def image_to_data_url(image, image_format=".jpg", quality=92):
    if image is None: return None
    ext = ".jpg" if image_format.lower() in (".jpg", ".jpeg") else ".png"
    mime = "image/jpeg" if ext == ".jpg" else "image/png"
    
    params = [cv2.IMWRITE_JPEG_QUALITY, quality] if ext == ".jpg" else []
    success, encoded = cv2.imencode(ext, image, params)
    
    if not success: return None
    return f"data:{mime};base64,{base64.b64encode(encoded.tobytes()).decode('utf-8')}"

# ============================================================
# ROUTES
# ============================================================
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/database", methods=["GET"])
def database():
    people = []
    if os.path.exists(FACES_DIR):
        for name in sorted(os.listdir(FACES_DIR)):
            folder = os.path.join(FACES_DIR, name)
            if os.path.isdir(folder):
                images = [f for f in os.listdir(folder) if f.lower().endswith(VALID_EXTENSIONS)]
                people.append({"name": name, "images": len(images)})
                
    with database_lock: total_encodings = len(known_face_encodings)
    return jsonify({"success": True, "people": people, "total_people": len(people), "total_encodings": total_encodings})

@app.route("/api/register", methods=["POST"])
def register_person():
    name = sanitize_name(request.form.get("name", ""))
    if not name: return jsonify({"success": False, "message": "Tên không hợp lệ."}), 400
    
    files = request.files.getlist("images")
    if not files: return jsonify({"success": False, "message": "Chưa chọn ảnh."}), 400

    person_folder = os.path.join(FACES_DIR, name)
    os.makedirs(person_folder, exist_ok=True)
    next_num = get_next_number(person_folder)
    
    success_count, skipped = 0, []
    
    for file in files:
        if not file.filename: continue
        try:
            image = decode_uploaded_image(file)
            if image is None: raise ValueError("Không đọc được ảnh.")
            
            rgb_img = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            faces = face_recognition.face_locations(rgb_img, model="hog")
            
            if len(faces) != 1:
                skipped.append({"file": file.filename, "reason": f"Có {len(faces)} khuôn mặt."})
                continue
                
            ext = os.path.splitext(file.filename)[1].lower()
            ext = ext if ext in (".jpg", ".jpeg", ".png") else ".jpg"
            dest = os.path.join(person_folder, f"{next_num:03d}{ext}")
            
            params = [cv2.IMWRITE_JPEG_QUALITY, 95] if ext in (".jpg", ".jpeg") else []
            success, encoded = cv2.imencode(ext, image, params)
            
            if success:
                with open(dest, "wb") as f: f.write(encoded.tobytes())
                success_count += 1
                next_num += 1
            else:
                skipped.append({"file": file.filename, "reason": "Lỗi encode."})
        except Exception as e:
            skipped.append({"file": file.filename, "reason": str(e)})

    if success_count > 0: load_known_faces()
    
    if success_count == 0:
        return jsonify({"success": False, "message": "Không có ảnh hợp lệ chứa đúng 1 khuôn mặt.", "skipped": skipped}), 400
        
    return jsonify({"success": True, "message": f"Đã đăng ký {name} với {success_count} ảnh.", "success_count": success_count, "skipped": skipped})

@app.route("/api/delete", methods=["POST"])
def delete_person():
    name = sanitize_name(request.get_json(silent=True).get("name", ""))
    if not name: return jsonify({"success": False, "message": "Tên không hợp lệ."}), 400
    
    person_folder = os.path.join(FACES_DIR, name)
    if not os.path.isdir(person_folder): return jsonify({"success": False, "message": "Không tìm thấy người này."}), 404
    
    try:
        shutil.rmtree(person_folder)
        load_known_faces()
        return jsonify({"success": True, "message": f"Đã xóa {name}."})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route("/api/verify", methods=["POST"])
def verify_image():
    file = request.files.get("image")
    if not file or not file.filename: return jsonify({"success": False, "message": "File ảnh không hợp lệ."}), 400
    
    try:
        image = decode_uploaded_image(file)
        if image is None: return jsonify({"success": False, "message": "Không thể đọc ảnh."}), 400
        
        orig_img_url = image_to_data_url(image.copy())
        results = recognize_image(image)
        result_img_url = image_to_data_url(draw_results_on_image(image, results))
        
        if result_img_url is None: return jsonify({"success": False, "message": "Lỗi tạo ảnh kết quả."}), 500
        
        recognized = sum(1 for r in results if r.get("name") != "Unknown")
        unknown = len(results) - recognized
        msg = f"Phát hiện {len(results)} khuôn mặt. Nhận diện {recognized}. Unknown: {unknown}." if results else "Không tìm thấy khuôn mặt."
        
        return jsonify({
            "success": True, "message": msg,
            "image": result_img_url, "original_image": orig_img_url,
            "results": results, "width": int(image.shape[1]), "height": int(image.shape[0])
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "message": f"Lỗi xác minh: {e}"}), 500

@app.route("/api/recognize", methods=["POST"])
def recognize_frame():
    data = request.get_json(silent=True)
    if not data or "image" not in data: return jsonify({"success": False, "message": "Không có frame."}), 400
    
    try:
        img_data = data["image"].split(",", 1)[1] if "," in data["image"] else data["image"]
        img_bytes = base64.b64decode(img_data, validate=True)
        frame = cv2.imdecode(np.frombuffer(img_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        
        if frame is None: return jsonify({"success": False, "message": "Không decode được frame."}), 400
        
        results = recognize_image(frame)
        return jsonify({"success": True, "results": results, "width": int(frame.shape[1]), "height": int(frame.shape[0])})
    except Exception as e:
        return jsonify({"success": False, "message": f"Lỗi nhận diện: {e}"}), 500

@app.errorhandler(413)
def request_entity_too_large(error): return jsonify({"success": False, "message": "Ảnh quá lớn. Tối đa 15MB."}), 413

@app.errorhandler(500)
def internal_server_error(error): return jsonify({"success": False, "message": "Lỗi máy chủ."}), 500

# ============================================================
# MAIN ENTRY POINT
# ============================================================
def open_browser():
    webbrowser.open("http://127.0.0.1:5000/")

if __name__ == "__main__":
    load_known_faces()
    print("\n======================================")
    print(" FACE RECOGNITION WEB SERVER")
    print("======================================")
    print(f"Faces directory: {FACES_DIR} | Threshold: {FACE_DISTANCE_THRESHOLD} | Process scale: {PROCESS_SCALE}")
    print("Server: http://127.0.0.1:5000\n======================================\n")
    
    # Tự động mở trình duyệt web sau 1.5 giây khi khởi chạy file .exe
    Timer(1.5, open_browser).start()
    
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)