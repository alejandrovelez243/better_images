/**
 * Better Images — Frontend Application (Batch Processing)
 * Handles multi-file upload, per-image dimension controls, and batch processing.
 */

(function () {
    "use strict";

    // --- DOM References ---
    const dropZone = document.getElementById("drop-zone");
    const fileInput = document.getElementById("file-input");
    const uploadSection = document.getElementById("upload-section");
    const gallerySection = document.getElementById("gallery-section");
    const imageGallery = document.getElementById("image-gallery");
    const imageCount = document.getElementById("image-count");
    const btnClearAll = document.getElementById("btn-clear-all");
    const btnProcessBatch = document.getElementById("btn-process-batch");
    const batchProgress = document.getElementById("batch-progress");
    const batchProgressFill = document.getElementById("batch-progress-fill");
    const batchProgressText = document.getElementById("batch-progress-text");
    const batchDownload = document.getElementById("batch-download");
    const btnDownloadZip = document.getElementById("btn-download-zip");
    const btnNewBatch = document.getElementById("btn-new-batch");
    const toastContainer = document.getElementById("toast-container");

    // --- State ---
    let uploadedImages = []; // Array of { jobId, filename, width, height, aspectRatio, lockAspect }
    let currentBatchId = null;
    let statusPollInterval = null;

    // --- Drag & Drop ---
    dropZone.addEventListener("click", () => fileInput.click());

    fileInput.addEventListener("change", (e) => {
        if (e.target.files.length > 0) uploadFiles(Array.from(e.target.files));
    });

    dropZone.addEventListener("dragover", (e) => {
        e.preventDefault();
        dropZone.classList.add("dragover");
    });

    dropZone.addEventListener("dragleave", () => {
        dropZone.classList.remove("dragover");
    });

    dropZone.addEventListener("drop", (e) => {
        e.preventDefault();
        dropZone.classList.remove("dragover");
        if (e.dataTransfer.files.length > 0) {
            uploadFiles(Array.from(e.dataTransfer.files));
        }
    });

    // --- Upload Multiple Files ---
    async function uploadFiles(files) {
        const formData = new FormData();
        files.forEach(file => formData.append("files", file));

        try {
            const res = await fetch("/api/upload-batch", { method: "POST", body: formData });
            const data = await res.json();

            if (!res.ok) {
                showToast(data.error || "Error uploading files", "error");
                return;
            }

            currentBatchId = data.batch_id;

            // Add uploaded jobs to our state
            data.jobs.forEach(job => {
                uploadedImages.push({
                    jobId: job.id,
                    filename: job.filename,
                    width: job.width,
                    height: job.height,
                    originalWidth: job.width,
                    originalHeight: job.height,
                    aspectRatio: job.width / job.height,
                    lockAspect: true,
                    status: "uploaded"
                });
            });

            // Show gallery
            uploadSection.style.display = "none";
            gallerySection.style.display = "block";

            renderGallery();
            showToast(`${data.count} imagen(es) cargada(s)`, "success");

        } catch (error) {
            showToast("Error uploading files", "error");
            console.error(error);
        }
    }

    // --- Render Gallery ---
    function renderGallery() {
        imageCount.textContent = uploadedImages.length;
        imageGallery.innerHTML = "";

        uploadedImages.forEach((img, index) => {
            const card = createImageCard(img, index);
            imageGallery.appendChild(card);
        });
    }

    // --- Create Image Card ---
    function createImageCard(img, index) {
        const card = document.createElement("div");
        card.className = "image-card";
        card.dataset.index = index;

        card.innerHTML = `
            <div class="image-card__preview">
                <img src="/api/preview/${img.jobId}?type=original" alt="${img.filename}">
                <button class="image-card__remove" data-index="${index}">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <line x1="18" y1="6" x2="6" y2="18"></line>
                        <line x1="6" y1="6" x2="18" y2="18"></line>
                    </svg>
                </button>
            </div>
            <div class="image-card__info">
                <div class="image-card__name" title="${img.filename}">${img.filename}</div>
                <div class="image-card__meta">
                    <span class="meta-tag">Original: ${img.originalWidth}×${img.originalHeight}</span>
                </div>
                <div class="dimension-controls">
                    <div class="dimension-input">
                        <label>Ancho</label>
                        <input type="number" class="width-input" data-index="${index}" value="${img.width}" min="1">
                    </div>
                    <button class="lock-aspect ${img.lockAspect ? 'locked' : ''}" data-index="${index}">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            ${img.lockAspect
                ? '<rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect><path d="M7 11V7a5 5 0 0 1 10 0v4"></path>'
                : '<rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect><path d="M7 11V7a5 5 0 0 1 9.9-1"></path>'
            }
                        </svg>
                    </button>
                    <div class="dimension-input">
                        <label>Alto</label>
                        <input type="number" class="height-input" data-index="${index}" value="${img.height}" min="1">
                    </div>
                </div>
                <div class="image-card__status" style="display:${img.status === 'uploaded' ? 'none' : 'block'}">
                    ${getStatusText(img.status)}
                </div>
            </div>
        `;

        // Event listeners for this card
        const removeBtn = card.querySelector(".image-card__remove");
        const lockBtn = card.querySelector(".lock-aspect");
        const widthInput = card.querySelector(".width-input");
        const heightInput = card.querySelector(".height-input");

        removeBtn.addEventListener("click", () => removeImage(index));
        lockBtn.addEventListener("click", () => toggleLockAspect(index));
        widthInput.addEventListener("input", (e) => onDimensionChange(index, "width", parseInt(e.target.value)));
        heightInput.addEventListener("input", (e) => onDimensionChange(index, "height", parseInt(e.target.value)));

        return card;
    }

    // --- Dimension Controls ---
    function toggleLockAspect(index) {
        uploadedImages[index].lockAspect = !uploadedImages[index].lockAspect;
        renderGallery();
    }

    function onDimensionChange(index, dimension, value) {
        if (isNaN(value) || value < 1) return;

        const img = uploadedImages[index];

        if (dimension === "width") {
            img.width = value;
            if (img.lockAspect) {
                img.height = Math.round(value / img.aspectRatio);
            }
        } else {
            img.height = value;
            if (img.lockAspect) {
                img.width = Math.round(value * img.aspectRatio);
            }
        }

        // Update the inputs without re-rendering entire gallery
        const card = imageGallery.querySelector(`[data-index="${index}"]`);
        if (card) {
            card.querySelector(".width-input").value = img.width;
            card.querySelector(".height-input").value = img.height;
        }
    }

    // --- Remove Image ---
    function removeImage(index) {
        uploadedImages.splice(index, 1);
        if (uploadedImages.length === 0) {
            resetToUpload();
        } else {
            renderGallery();
        }
    }

    // --- Clear All ---
    btnClearAll.addEventListener("click", () => {
        if (confirm("¿Eliminar todas las imágenes?")) {
            resetToUpload();
        }
    });

    function resetToUpload() {
        uploadedImages = [];
        currentBatchId = null;
        gallerySection.style.display = "none";
        uploadSection.style.display = "block";
        fileInput.value = "";
    }

    // --- Batch Processing ---
    btnProcessBatch.addEventListener("click", async () => {
        btnProcessBatch.disabled = true;
        batchProgress.style.display = "block";
        batchDownload.style.display = "none";

        // First, resize images if dimensions changed
        for (const img of uploadedImages) {
            if (img.width !== img.originalWidth || img.height !== img.originalHeight) {
                try {
                    await fetch(`/api/resize/${img.jobId}`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
                            width: img.width,
                            height: img.height,
                            maintain_aspect: img.lockAspect
                        })
                    });
                    img.status = "resizing";
                    updateCardStatus(img.jobId, "Redimensionando...");
                } catch (error) {
                    console.error(`Error resizing ${img.jobId}:`, error);
                }
            }
        }

        // Wait a bit for resizes to complete
        await new Promise(resolve => setTimeout(resolve, 1000));

        // Get batch settings
        const upscale = parseInt(document.querySelector('input[name="batch-upscale"]:checked').value);
        const removeBg = document.getElementById("batch-remove-bg").checked;
        const trimImage = document.getElementById("batch-trim").checked;
        const format = document.querySelector('input[name="batch-format"]:checked').value;

        // Start batch processing
        try {
            const res = await fetch("/api/batch-process", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    job_ids: uploadedImages.map(img => img.jobId),
                    upscale,
                    remove_bg: removeBg,
                    trim: trimImage,
                    format
                })
            });

            const data = await res.json();

            if (!res.ok) {
                showToast(data.error || "Error processing batch", "error");
                btnProcessBatch.disabled = false;
                return;
            }

            // Start polling for status
            startStatusPolling();

        } catch (error) {
            showToast("Error al procesar", "error");
            btnProcessBatch.disabled = false;
            batchProgress.style.display = "none";
        }
    });

    // --- Status Polling ---
    function startStatusPolling() {
        if (statusPollInterval) clearInterval(statusPollInterval);

        statusPollInterval = setInterval(async () => {
            try {
                const res = await fetch(`/api/batch-status/${currentBatchId}`);
                const data = await res.json();

                // Update each image status
                data.jobs.forEach(job => {
                    const img = uploadedImages.find(i => i.jobId === job.id);
                    if (img) {
                        img.status = job.status;
                        img.progress = job.progress;
                        updateCardStatus(job.id, job.progress || job.status);
                    }
                });

                // Update overall progress
                const doneCount = data.jobs.filter(j => j.status === "done").length;
                const progress = (doneCount / data.jobs.length) * 100;
                batchProgressFill.style.width = `${progress}%`;
                batchProgressText.textContent = `${doneCount} de ${data.jobs.length} completadas`;

                // Check if all done
                if (data.all_done) {
                    clearInterval(statusPollInterval);
                    batchProgress.style.display = "none";
                    batchDownload.style.display = "block";
                    btnProcessBatch.disabled = false;
                    showToast("¡Todas las imágenes procesadas!", "success");
                }

                // Check for errors
                if (data.any_error) {
                    showToast("Algunas imágenes tuvieron errores", "error");
                }

            } catch (error) {
                console.error("Error polling status:", error);
            }
        }, 1000);
    }

    function updateCardStatus(jobId, statusText) {
        const img = uploadedImages.find(i => i.jobId === jobId);
        if (!img) return;

        const index = uploadedImages.indexOf(img);
        const card = imageGallery.querySelector(`[data-index="${index}"]`);
        if (card) {
            const statusEl = card.querySelector(".image-card__status");
            statusEl.style.display = "block";
            statusEl.textContent = statusText;
            statusEl.className = `image-card__status image-card__status--${img.status}`;
        }
    }

    function getStatusText(status) {
        const map = {
            "uploaded": "",
            "processing": "Procesando...",
            "done": "✓ Completado",
            "error": "✗ Error"
        };
        return map[status] || status;
    }

    // --- Download ZIP ---
    btnDownloadZip.addEventListener("click", () => {
        window.location.href = `/api/download-batch/${currentBatchId}`;
    });

    // --- New Batch ---
    btnNewBatch.addEventListener("click", () => {
        if (statusPollInterval) clearInterval(statusPollInterval);
        resetToUpload();
    });

    // --- Toast Notifications ---
    function showToast(message, type = "info") {
        const toast = document.createElement("div");
        toast.className = `toast toast--${type}`;
        toast.textContent = message;
        toastContainer.appendChild(toast);

        setTimeout(() => {
            toast.remove();
        }, 4000);
    }

})();
