// ============================================================
// GLOBAL
// ============================================================
const video = document.getElementById("video");
const canvas = document.getElementById("verifyCanvas");
const ctx = canvas.getContext("2d");
const resultBox = document.getElementById("verifyResult");

let stream = null;
let globalPeople = []; // Lưu trữ DB tạm thời để search
let globalStats = { totalPeople: 0, totalEncodings: 0 };

// ============================================================
// REGISTER
// ============================================================
async function registerPerson() {
    const nameInput = document.getElementById("personName");
    const imagesInput = document.getElementById("registerImages");
    const status = document.getElementById("registerStatus");
    const name = nameInput.value.trim();

    if (!name) return showStatus(status, "Vui lòng nhập tên.", false);
    if (!imagesInput.files.length) return showStatus(status, "Vui lòng chọn ít nhất một ảnh.", false);

    const formData = new FormData();
    formData.append("name", name);
    for (const file of imagesInput.files) formData.append("images", file);

    showStatus(status, "Đang xử lý ảnh...", true);

    try {
        const response = await fetch("/api/register", { method: "POST", body: formData });
        const data = await response.json();

        if (!response.ok) {
            showStatus(status, data.message || "Đăng ký thất bại.", false);
            return;
        }

        let message = data.message;
        if (data.skipped && data.skipped.length) {
            message += "\n\nẢnh bỏ qua:\n";
            data.skipped.forEach(item => message += `- ${item.file}: ${item.reason}\n`);
        }

        showStatus(status, message, true);
        nameInput.value = "";
        imagesInput.value = "";
        loadDatabase();
    } catch (error) {
        console.error(error);
        showStatus(status, "Lỗi kết nối server.", false);
    }
}

function showStatus(element, message, success) {
    element.textContent = message;
    element.className = success ? "success" : "error";
    element.style.color = success ? "green" : "red";
    element.style.whiteSpace = "pre-line";
    element.style.marginTop = "10px";
}

// ============================================================
// DATABASE & SEARCH
// ============================================================
async function loadDatabase() {
    const container = document.getElementById("databaseList");
    const statsContainer = document.getElementById("databaseStats");
    
    try {
        const response = await fetch("/api/database");
        const data = await response.json();
        
        globalPeople = data.people || [];
        globalStats.totalPeople = data.total_people || 0;
        globalStats.totalEncodings = data.total_encodings || 0;
        
        statsContainer.innerHTML = `Tổng người: ${globalStats.totalPeople} | Tổng ảnh (encoding): ${globalStats.totalEncodings}`;
        renderDatabaseList(globalPeople);
    } catch (error) {
        console.error(error);
        container.innerHTML = "Không thể tải database.";
    }
}

function renderDatabaseList(people) {
    const container = document.getElementById("databaseList");
    if (!people.length) {
        container.innerHTML = "<div>Không tìm thấy người nào.</div>";
        return;
    }

    let html = "";
    people.forEach(person => {
        html += `
            <div class="db-item">
                <div class="db-info">
                    <span class="db-name">${escapeHtml(person.name)}</span>
                    <span class="db-count">${person.images} ảnh</span>
                </div>
                <button class="btn-small" onclick="deletePerson('${escapeHtml(person.name)}')">Xóa</button>
            </div>`;
    });
    container.innerHTML = html;
}

function filterDatabase() {
    const query = document.getElementById("searchInput").value.toLowerCase();
    const filtered = globalPeople.filter(p => p.name.toLowerCase().includes(query));
    renderDatabaseList(filtered);
}

async function deletePerson(name) {
    if (!confirm(`Bạn có chắc muốn xóa "${name}" không?\nTất cả ảnh sẽ bị xóa.`)) return;

    try {
        const response = await fetch("/api/delete", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: name })
        });
        const result = await response.json();
        
        if (!response.ok) return alert(result.message || "Không thể xóa.");
        loadDatabase(); // Reload after success
    } catch (error) {
        console.error(error);
        alert("Lỗi kết nối server.");
    }
}

// ============================================================
// VERIFY FROM UPLOADED IMAGE
// ============================================================
async function verifyUploadedImage() {
    const input = document.getElementById("verifyImage");
    if (!input.files.length) return;

    stopCamera(); // Tắt camera nếu đang mở
    resultBox.textContent = "Đang nhận diện...";
    
    const file = input.files[0];
    const formData = new FormData();
    formData.append("image", file);

    try {
        const response = await fetch("/api/verify", { method: "POST", body: formData });
        const data = await response.json();
        
        if (!response.ok) {
            resultBox.textContent = data.message || "Không thể xác minh.";
            return;
        }

        const image = new Image();
        image.onload = function() {
            canvas.style.display = "block";
            canvas.width = image.width;
            canvas.height = image.height;
            ctx.drawImage(image, 0, 0);
            drawResults(ctx, data.results, image.width, image.height);
            displayResultText(data.results);
        };
        image.src = URL.createObjectURL(file);
    } catch (error) {
        console.error(error);
        resultBox.textContent = "Lỗi kết nối server.";
    }
    input.value = ""; // reset input
}

// ============================================================
// CAMERA FUNCTIONS
// ============================================================
async function startCamera() {
    if (stream) return;
    try {
        stream = await navigator.mediaDevices.getUserMedia({ 
            video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: "user" }, 
            audio: false 
        });
        video.srcObject = stream;
        video.style.display = "block";
        canvas.style.display = "none";
        
        document.getElementById("startCameraBtn").style.display = "none";
        document.getElementById("captureBtn").style.display = "inline-block";
        document.getElementById("stopCameraBtn").style.display = "inline-block";
        resultBox.textContent = "Camera đang bật. Hãy căn chỉnh khuôn mặt và bấm Chụp.";
    } catch (error) {
        console.error(error);
        alert("Không thể mở camera. Hãy kiểm tra quyền truy cập webcam.");
    }
}

function stopCamera() {
    if (stream) {
        stream.getTracks().forEach(track => track.stop());
        stream = null;
    }
    video.style.display = "none";
    video.srcObject = null;
    
    document.getElementById("startCameraBtn").style.display = "inline-block";
    document.getElementById("captureBtn").style.display = "none";
    document.getElementById("stopCameraBtn").style.display = "none";

    // Thêm dòng này: Xóa dòng chữ thông báo khi tắt camera
    if (resultBox.textContent === "Camera đang bật. Hãy căn chỉnh khuôn mặt và bấm Chụp.") {
        resultBox.textContent = "";
    }
}

async function captureAndVerify() {
    if (!video.videoWidth) return;
    
    resultBox.textContent = "Đang xử lý ảnh chụp...";
    
    // Draw current video frame to canvas
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    
    // Hide video and show captured canvas frame
    video.style.display = "none";
    canvas.style.display = "block";
    
    const imageData = canvas.toDataURL("image/jpeg", 0.8);
    stopCamera(); // Tắt stream camera sau khi chụp xong
    
    try {
        const response = await fetch("/api/recognize", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ image: imageData })
        });
        
        const data = await response.json();
        
        if (data.success && data.results) {
            drawResults(ctx, data.results, canvas.width, canvas.height);
            displayResultText(data.results);
        } else {
            resultBox.textContent = "Không tìm thấy khuôn mặt hoặc lỗi xử lý.";
        }
    } catch (error) {
        console.error(error);
        resultBox.textContent = "Lỗi kết nối server khi nhận diện.";
    }
}

// ============================================================
// UTILITIES (DRAW & TEXT)
// ============================================================
function displayResultText(results) {
    if (!results || !results.length) {
        resultBox.textContent = "Không tìm thấy khuôn mặt.";
        return;
    }
    let text = "Kết quả nhận diện:\n";
    results.forEach((result, index) => {
        text += `- Khuôn mặt ${index + 1}: ${result.name}`;
        if (result.confidence !== null && result.confidence !== undefined) text += ` (Confidence: ${result.confidence}%)`;
        if (result.distance !== null && result.distance !== undefined) text += ` - Distance: ${result.distance}`;
        text += "\n";
    });
    resultBox.textContent = text;
}

function drawResults(context, results, imageWidth, imageHeight) {
    results.forEach(result => {
        const box = result.box;
        if (!box) return;

        const known = result.name !== "Unknown";
        const color = known ? "#00c853" : "#ff1744"; // Xanh / Đỏ

        context.strokeStyle = color;
        context.lineWidth = 3;
        
        const width = box.right - box.left;
        const height = box.bottom - box.top;
        context.strokeRect(box.left, box.top, width, height);

        let label = result.name;
        if (result.confidence !== null && result.confidence !== undefined) {
            label += ` (${result.confidence}%)`;
        }

        context.font = "bold 16px Arial";
        const textWidth = context.measureText(label).width;
        const labelWidth = textWidth + 14;
        const labelHeight = 28;
        
        let labelX = box.left;
        let labelY = box.top - labelHeight;
        if (labelY < 0) labelY = box.top;
        if (labelX + labelWidth > imageWidth) labelX = imageWidth - labelWidth;

        context.fillStyle = color;
        context.fillRect(labelX, labelY, labelWidth, labelHeight);
        
        context.fillStyle = "white";
        context.fillText(label, labelX + 7, labelY + 19);
    });
}

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

// Init
loadDatabase();