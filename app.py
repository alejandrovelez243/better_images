"""
Better Images — Flask Web App
Local image processing: upscale, remove background, convert to SVG/ICO.
"""

import patch_torchvision  # MUST BE FIRST
import os
import uuid
import logging
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

# Limit concurrency to avoid OOM / SegFaults on MPS
# 2 workers is a safe balance for most local machines
executor = ThreadPoolExecutor(max_workers=2)

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


@app.route("/api/upload-batch", methods=["POST"])
def upload_batch():
    """Upload multiple images and return a batch ID with job IDs."""
    if "files" not in request.files:
        return jsonify({"error": "No files provided"}), 400

    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "No files selected"}), 400

    batch_id = str(uuid.uuid4())
    uploaded_jobs = []

    for file in files:
        if not file.filename or not allowed_file(file.filename):
            logger.warning(f"Skipping invalid file: {file.filename}")
            continue

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
            "batch_id": batch_id,
            "status": "uploaded",
            "original": str(filepath),
            "original_name": file.filename,
            "width": width,
            "height": height,
            "results": {},
            "error": None,
        }

        uploaded_jobs.append({
            "id": job_id,
            "filename": file.filename,
            "width": width,
            "height": height,
        })

        logger.info(f"Batch {batch_id}: Uploaded {file.filename} as {job_id} ({width}x{height})")

    if not uploaded_jobs:
        return jsonify({"error": "No valid files uploaded"}), 400

    return jsonify({
        "batch_id": batch_id,
        "jobs": uploaded_jobs,
        "count": len(uploaded_jobs),
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


@app.route("/api/resize/<job_id>", methods=["POST"])
def resize_image(job_id):
    """Resize an uploaded image to custom dimensions."""
    if job_id not in jobs:
        return jsonify({"error": "Job not found"}), 404

    data = request.get_json() or {}
    width = data.get("width")
    height = data.get("height")
    maintain_aspect = data.get("maintain_aspect", True)

    if not width and not height:
        return jsonify({"error": "Must specify width or height"}), 400

    job = jobs[job_id]
    if job["status"] == "processing":
        return jsonify({"error": "Job is already processing"}), 400

    def run_resize():
        try:
            job["status"] = "processing"
            job["progress"] = "Resizing..."
            
            current_path = job["original"]
            resized_path = processor.resize(
                current_path,
                width=width,
                height=height,
                maintain_aspect=maintain_aspect,
                progress_cb=lambda msg: job.update({"progress": msg})
            )
            
            # Update job with new path and dimensions
            from PIL import Image
            with Image.open(resized_path) as img:
                new_width, new_height = img.size
            
            job["original"] = resized_path
            job["width"] = new_width
            job["height"] = new_height
            job["status"] = "uploaded"
            job["progress"] = "Resized"
            logger.info(f"Resized {job_id} to {new_width}x{new_height}")

        except Exception as e:
            job["status"] = "error"
            job["error"] = str(e)
            logger.error(f"Resize failed for {job_id}: {e}", exc_info=True)

    thread = threading.Thread(target=run_resize, daemon=True)
    thread.start()

    return jsonify({"id": job_id, "status": "processing"})


@app.route("/api/batch-process", methods=["POST"])
def batch_process():
    """Process multiple images with the same settings."""
    data = request.get_json()
    if not data or "job_ids" not in data:
        return jsonify({"error": "Missing job_ids"}), 400

    job_ids = data["job_ids"]
    if not isinstance(job_ids, list) or not job_ids:
        return jsonify({"error": "job_ids must be a non-empty list"}), 400

    # Validate all jobs exist
    for job_id in job_ids:
        if job_id not in jobs:
            return jsonify({"error": f"Job {job_id} not found"}), 404

    # Extract settings
    upscale = data.get("upscale", 0)
    remove_bg = data.get("remove_bg", False)
    fmt = data.get("format", "png")

    # Start processing each job
    for job_id in job_ids:
        job = jobs[job_id]
        job["upscale"] = upscale
        job["remove_bg"] = remove_bg
        job["output_format"] = fmt

        # Trigger the same processing logic as single process
        def run_batch_item(jid):
            the_job = jobs[jid]
            if the_job["status"] != "uploaded":
                return

            the_job["status"] = "processing"
            the_job["progress"] = "Starting..."
            
            def on_progress(msg):
                the_job["progress"] = msg

            try:
                current_path = the_job["original"]

                # Upscale
                if the_job["upscale"] > 0:
                    scale_factor = the_job["upscale"]
                    the_job["progress"] = "📐 Checking image size..."
                    logger.info("📐 Checking image size...")
                    current_path = processor.upscale(current_path, scale_factor, progress_cb=on_progress)
                    the_job["results"]["upscaled"] = current_path

                # Remove background
                if the_job["remove_bg"]:
                    current_path = processor.remove_background(current_path, progress_cb=on_progress)
                    the_job["results"]["background_removed"] = current_path

                # Convert format
                output_fmt = the_job["output_format"]
                if output_fmt == "svg":
                    current_path = processor.to_svg(current_path, progress_cb=on_progress)
                    the_job["results"]["svg"] = current_path
                elif output_fmt == "ico":
                    current_path = processor.to_ico(current_path, progress_cb=on_progress)
                    the_job["results"]["ico"] = current_path

                final_path = current_path
                the_job["results"]["final"] = final_path
                the_job["status"] = "done"
                the_job["progress"] = "¡Completado!"
                logger.info(f"Job {jid} complete: {final_path}")

            except Exception as e:
                the_job["status"] = "error"
                the_job["error"] = str(e)
                the_job["progress"] = f"Error: {e}"
                logger.error(f"Job {jid} failed: {e}", exc_info=True)

        # Use global executor to limit concurrency
        executor.submit(run_batch_item, job_id)

    return jsonify({
        "message": f"Batch processing started for {len(job_ids)} images",
        "job_ids": job_ids
    })


@app.route("/api/batch-status/<batch_id>")
def batch_status(batch_id):
    """Get status of all jobs in a batch."""
    batch_jobs = {jid: job for jid, job in jobs.items() if job.get("batch_id") == batch_id}
    
    if not batch_jobs:
        return jsonify({"error": "Batch not found"}), 404

    statuses = []
    for job_id, job in batch_jobs.items():
        statuses.append({
            "id": job_id,
            "filename": job.get("original_name", ""),
            "status": job["status"],
            "progress": job.get("progress", ""),
            "error": job.get("error"),
            "has_results": bool(job.get("results")),
        })

    # Overall batch status
    all_done = all(s["status"] == "done" for s in statuses)
    any_error = any(s["status"] == "error" for s in statuses)
    any_processing = any(s["status"] == "processing" for s in statuses)

    return jsonify({
        "batch_id": batch_id,
        "jobs": statuses,
        "count": len(statuses),
        "all_done": all_done,
        "any_error": any_error,
        "any_processing": any_processing,
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


@app.route("/api/download-batch/<batch_id>")
def download_batch(batch_id):
    """Download all processed images in a batch as a ZIP file."""
    import zipfile
    import io

    batch_jobs = {jid: job for jid, job in jobs.items() if job.get("batch_id") == batch_id}
    
    if not batch_jobs:
        return jsonify({"error": "Batch not found"}), 404

    # Check if all jobs are done
    all_done = all(job["status"] == "done" for job in batch_jobs.values())
    if not all_done:
        return jsonify({"error": "Not all jobs are complete"}), 400

    # Create ZIP in memory
    zip_buffer = io.BytesIO()
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for job_id, job in batch_jobs.items():
            final_path = job["results"].get("final")
            if final_path and os.path.exists(final_path):
                # Generate nice filename
                original_name = Path(job["original_name"]).stem
                final_ext = Path(final_path).suffix
                filename = f"{original_name}_processed{final_ext}"
                
                # Add to ZIP
                zip_file.write(final_path, filename)
                logger.info(f"Added {filename} to batch ZIP")

    zip_buffer.seek(0)
    
    return send_file(
        zip_buffer,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f'batch_{batch_id}.zip'
    )


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
