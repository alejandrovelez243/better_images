"""
Better Images — Flask Web App
Local image processing: upscale, remove background, convert to SVG/ICO.
"""

import os
import uuid
import logging
import threading
from pathlib import Path

# Set model cache dirs BEFORE importing rembg (via processor)
os.environ.setdefault("U2NET_HOME", str(Path(__file__).parent / "models"))

from flask import Flask, request, jsonify, send_file, send_from_directory

from processor import ImageProcessor

# --- Config ---
UPLOAD_DIR = Path("uploads")
OUTPUT_DIR = Path("outputs")
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "bmp", "tiff"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# --- App ---
app = Flask(__name__, static_folder="static", static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50MB max upload
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0  # Disable static file caching


@app.after_request
def add_no_cache(response):
    """Prevent browser from caching HTML/JS/CSS."""
    if response.content_type and any(
        t in response.content_type
        for t in ["text/html", "javascript", "text/css"]
    ):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

processor = ImageProcessor(models_dir="models")

# Job tracking
jobs: dict[str, dict] = {}

def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# --- Routes ---

@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/upload", methods=["POST"])
def upload():
    """Upload an image and return a job ID."""
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if not file.filename or not allowed_file(file.filename):
        return jsonify({"error": "Invalid file type. Allowed: PNG, JPG, WEBP, BMP, TIFF"}), 400

    job_id = str(uuid.uuid4())
    ext = Path(file.filename).suffix.lower()
    filename = f"{job_id}{ext}"
    filepath = UPLOAD_DIR / filename
    file.save(filepath)

    # Get image dimensions
    from PIL import Image
    with Image.open(filepath) as img:
        width, height = img.size

    jobs[job_id] = {
        "id": job_id,
        "status": "uploaded",
        "original": str(filepath),
        "original_name": file.filename,
        "width": width,
        "height": height,
        "results": {},
        "error": None,
    }

    logger.info(f"Uploaded {file.filename} as {job_id} ({width}x{height})")
    return jsonify({
        "id": job_id,
        "filename": file.filename,
        "width": width,
        "height": height,
    })


@app.route("/api/process", methods=["POST"])
def process():
    """Process an uploaded image with the given options."""
    data = request.get_json()
    if not data or "id" not in data:
        return jsonify({"error": "Missing job ID"}), 400

    job_id = data["id"]
    if job_id not in jobs:
        return jsonify({"error": "Job not found"}), 404

    job = jobs[job_id]
    if job["status"] == "processing":
        return jsonify({"error": "Already processing"}), 409

    # Parse options
    upscale_factor = data.get("upscale")  # None, 2, or 4
    remove_bg = data.get("remove_bg", False)
    output_format = data.get("format", "png")  # "png", "svg", "ico"

    if upscale_factor is not None:
        upscale_factor = int(upscale_factor)

    job["status"] = "processing"
    job["progress"] = "Starting..."

    def run_processing():
        try:
            input_path = job["original"]
            # Copy to output dir for processing
            import shutil
            work_path = str(OUTPUT_DIR / f"{job_id}_work{Path(input_path).suffix}")
            shutil.copy2(input_path, work_path)

            current_path = work_path

            # Progress callback — sends real-time updates to UI
            def on_progress(msg):
                job["progress"] = msg

            # Step 1: Upscale
            if upscale_factor:
                on_progress(f"Preparando escalado {upscale_factor}x...")
                current_path = processor.upscale(current_path, upscale_factor, progress_cb=on_progress)
                job["results"]["upscaled"] = current_path

            # Step 2: Remove background
            if remove_bg:
                on_progress("Preparando remoción de fondo...")
                current_path = processor.remove_background(current_path, progress_cb=on_progress)
                job["results"]["no_background"] = current_path

            # Step 3: Convert format
            if output_format == "svg":
                on_progress("Preparando conversión a SVG...")
                final_path = processor.to_svg(current_path, progress_cb=on_progress)
                job["results"]["svg"] = final_path
            elif output_format == "ico":
                on_progress("Preparando conversión a ICO...")
                final_path = processor.to_ico(current_path, progress_cb=on_progress)
                job["results"]["ico"] = final_path
            else:
                final_path = current_path

            job["results"]["final"] = final_path
            job["status"] = "done"
            job["progress"] = "¡Completado!"

            # Get final image dimensions if it's an image
            if final_path.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                from PIL import Image
                with Image.open(final_path) as img:
                    job["results"]["final_width"] = img.size[0]
                    job["results"]["final_height"] = img.size[1]

            logger.info(f"Job {job_id} complete: {final_path}")

        except Exception as e:
            job["status"] = "error"
            job["error"] = str(e)
            job["progress"] = f"Error: {e}"
            logger.error(f"Job {job_id} failed: {e}", exc_info=True)

    thread = threading.Thread(target=run_processing, daemon=True)
    thread.start()

    return jsonify({"id": job_id, "status": "processing"})


@app.route("/api/status/<job_id>")
def status(job_id):
    """Get job status."""
    if job_id not in jobs:
        return jsonify({"error": "Job not found"}), 404

    job = jobs[job_id]
    return jsonify({
        "id": job["id"],
        "status": job["status"],
        "progress": job.get("progress", ""),
        "error": job.get("error"),
        "results": {k: True for k in job["results"]} if job["results"] else {},
    })


@app.route("/api/download/<job_id>/<filename>")
def download_with_name(job_id, filename):
    """Download the processed file (filename in URL for browser compatibility)."""
    if job_id not in jobs:
        return jsonify({"error": "Job not found"}), 404

    job = jobs[job_id]
    if job["status"] != "done":
        return jsonify({"error": "Processing not complete"}), 400

    result_type = request.args.get("type", "final")
    filepath = job["results"].get(result_type)

    if not filepath or not os.path.exists(filepath):
        return jsonify({"error": "File not found"}), 404

    return send_file(
        filepath,
        as_attachment=True,
        download_name=filename,
    )


@app.route("/api/download/<job_id>")
def download(job_id):
    """Redirect to download URL with filename included."""
    if job_id not in jobs:
        return jsonify({"error": "Job not found"}), 404

    job = jobs[job_id]
    result_type = request.args.get("type", "final")
    filename = _make_download_name(job, result_type)

    from flask import redirect, url_for
    return redirect(f"/api/download/{job_id}/{filename}?type={result_type}")


@app.route("/api/preview/<job_id>")
def preview(job_id):
    """Get preview image for display."""
    if job_id not in jobs:
        return jsonify({"error": "Job not found"}), 404

    job = jobs[job_id]
    result_type = request.args.get("type", "final")

    if result_type == "original":
        filepath = job["original"]
    else:
        filepath = job["results"].get(result_type)

    if not filepath or not os.path.exists(filepath):
        return jsonify({"error": "File not found"}), 404

    # For SVG send as-is, for images send file
    if filepath.endswith(".svg"):
        return send_file(filepath, mimetype="image/svg+xml")
    elif filepath.endswith(".ico"):
        return send_file(filepath, mimetype="image/x-icon")
    else:
        return send_file(filepath)


def _make_download_name(job: dict, result_type: str) -> str:
    """Generate a nice download filename."""
    original = Path(job["original_name"])
    name = original.stem

    suffix_map = {
        "upscaled": "_upscaled",
        "no_background": "_nobg",
        "svg": "",
        "ico": "",
        "final": "_processed",
    }
    suffix = suffix_map.get(result_type, "")

    # Detect extension from the actual output file
    filepath = job["results"].get(result_type, "")
    if filepath:
        ext = Path(filepath).suffix  # .svg, .ico, .png, etc.
    else:
        ext_map = {
            "svg": ".svg",
            "ico": ".ico",
        }
        ext = ext_map.get(result_type, ".png")

    return f"{name}{suffix}{ext}"


def main():
    print("\n  🖼️  Better Images — Local Image Processor")
    print("  ─────────────────────────────────────────")
    print("  Open http://localhost:5001 in your browser\n")
    app.run(host="0.0.0.0", port=5001, debug=False)


if __name__ == "__main__":
    main()
