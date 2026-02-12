/**
 * Better Images — Frontend Application
 * Handles file upload, processing options, preview, and downloads.
 */

(function () {
    "use strict";

    // --- DOM References ---
    const dropZone = document.getElementById("drop-zone");
    const fileInput = document.getElementById("file-input");
    const uploadSection = document.getElementById("upload-section");
    const workspace = document.getElementById("workspace");
    const previewImage = document.getElementById("preview-image");
    const previewPlaceholder = document.getElementById("preview-placeholder");
    const tabResult = document.getElementById("tab-result");
    const btnProcess = document.getElementById("btn-process");
    const btnDownload = document.getElementById("btn-download");
    const btnNew = document.getElementById("btn-new");
    const progressArea = document.getElementById("progress-area");
    const progressFill = document.getElementById("progress-fill");
    const progressText = document.getElementById("progress-text");
    const downloadArea = document.getElementById("download-area");
    const infoName = document.getElementById("info-name");
    const infoDimensions = document.getElementById("info-dimensions");
    const toastContainer = document.getElementById("toast-container");

    // --- State ---
    let currentJob = null;
    let pollInterval = null;
    let showingResult = false;

    // --- Drag & Drop ---
    dropZone.addEventListener("click", () => fileInput.click());
    fileInput.addEventListener("change", (e) => {
        if (e.target.files.length > 0) uploadFile(e.target.files[0]);
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
            uploadFile(e.dataTransfer.files[0]);
        }
    });

    // --- Upload ---
    async function uploadFile(file) {
        const formData = new FormData();
        formData.append("file", file);

        try {
            const res = await fetch("/api/upload", { method: "POST", body: formData });
            const data = await res.json();

            if (!res.ok) {
                showToast(data.error || "Error uploading file", "error");
                return;
            }

            currentJob = data;

            // Show workspace
            uploadSection.style.display = "none";
            workspace.style.display = "block";

            // Show preview
            previewImage.src = `/api/preview/${data.id}?type=original`;
            previewPlaceholder.style.display = "none";

            // Update info
            infoName.textContent = data.filename;
            infoDimensions.textContent = `${data.width} × ${data.height}`;

            // Reset state
            tabResult.style.display = "none";
            downloadArea.style.display = "none";
            progressArea.style.display = "none";
            btnProcess.disabled = false;
            btnProcess.classList.remove("processing");
            showingResult = false;

            // Reset tabs
            document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
            document.querySelector('.tab[data-preview="original"]').classList.add("active");

            showToast(`${data.filename} cargado correctamente`, "success");
        } catch (err) {
            showToast("Error de conexión", "error");
            console.error(err);
        }
    }

    // --- Process ---
    btnProcess.addEventListener("click", async () => {
        if (!currentJob) return;

        const upscale = document.querySelector('input[name="upscale"]:checked').value;
        const removeBg = document.getElementById("remove-bg").checked;
        const format = document.querySelector('input[name="format"]:checked').value;

        // At least one operation must be selected
        if (upscale === "0" && !removeBg && format === "png") {
            showToast("Selecciona al menos una operación", "error");
            return;
        }

        btnProcess.disabled = true;
        btnProcess.classList.add("processing");
        btnProcess.innerHTML = `
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/></svg>
            Procesando...
        `;
        progressArea.style.display = "block";
        downloadArea.style.display = "none";

        try {
            const res = await fetch("/api/process", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    id: currentJob.id,
                    upscale: upscale === "0" ? null : parseInt(upscale),
                    remove_bg: removeBg,
                    format: format,
                }),
            });

            const data = await res.json();
            if (!res.ok) {
                showToast(data.error || "Error al procesar", "error");
                resetProcessButton();
                return;
            }

            // Start polling
            startPolling();
        } catch (err) {
            showToast("Error de conexión", "error");
            resetProcessButton();
            console.error(err);
        }
    });

    function startPolling() {
        if (pollInterval) clearInterval(pollInterval);

        // Animate progress bar
        let progressValue = 0;
        progressFill.style.width = "5%";

        pollInterval = setInterval(async () => {
            try {
                const res = await fetch(`/api/status/${currentJob.id}`);

                // Handle stale job (server restarted)
                if (!res.ok) {
                    clearInterval(pollInterval);
                    pollInterval = null;
                    progressArea.style.display = "none";
                    resetProcessButton();
                    showToast("Sesión expirada. Sube la imagen de nuevo.", "error");
                    return;
                }

                const data = await res.json();

                progressText.textContent = data.progress || "Procesando...";

                // Animate progress bar (indeterminate style)
                if (data.status === "processing") {
                    progressValue = Math.min(progressValue + 2, 90);
                    progressFill.style.width = progressValue + "%";
                }

                if (data.status === "done") {
                    clearInterval(pollInterval);
                    pollInterval = null;

                    progressFill.style.width = "100%";

                    // Small delay so user sees 100%
                    setTimeout(() => {
                        // Show result
                        progressArea.style.display = "none";
                        downloadArea.style.display = "flex";

                        // Update preview to result
                        const format = document.querySelector('input[name="format"]:checked').value;
                        if (format === "svg") {
                            previewImage.src = `/api/preview/${currentJob.id}?type=svg`;
                        } else if (format === "ico") {
                            previewImage.src = `/api/preview/${currentJob.id}?type=ico`;
                        } else if (data.results.no_background) {
                            previewImage.src = `/api/preview/${currentJob.id}?type=no_background`;
                        } else if (data.results.upscaled) {
                            previewImage.src = `/api/preview/${currentJob.id}?type=upscaled`;
                        } else {
                            previewImage.src = `/api/preview/${currentJob.id}?type=final`;
                        }

                        // Show result tab
                        tabResult.style.display = "inline-block";
                        document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
                        tabResult.classList.add("active");
                        showingResult = true;

                        resetProcessButton();
                        showToast("¡Imagen procesada exitosamente!", "success");
                    }, 400);

                } else if (data.status === "error") {
                    clearInterval(pollInterval);
                    pollInterval = null;
                    progressArea.style.display = "none";
                    resetProcessButton();
                    showToast(data.error || "Error durante el procesamiento", "error");
                }
            } catch (err) {
                console.error("Polling error:", err);
            }
        }, 1000);
    }

    function resetProcessButton() {
        btnProcess.disabled = false;
        btnProcess.classList.remove("processing");
        btnProcess.innerHTML = `
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polygon points="5 3 19 12 5 21 5 3"/>
            </svg>
            Procesar Imagen
        `;
    }

    // --- Preview Tabs ---
    document.querySelectorAll(".tab").forEach((tab) => {
        tab.addEventListener("click", () => {
            if (!currentJob) return;

            document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
            tab.classList.add("active");

            const type = tab.dataset.preview;
            if (type === "original") {
                previewImage.src = `/api/preview/${currentJob.id}?type=original`;
                showingResult = false;
            } else {
                // Show the best result
                const format = document.querySelector('input[name="format"]:checked').value;
                if (format === "svg") {
                    previewImage.src = `/api/preview/${currentJob.id}?type=svg`;
                } else {
                    previewImage.src = `/api/preview/${currentJob.id}?type=final`;
                }
                showingResult = true;
            }
        });
    });

    // --- Download ---
    btnDownload.addEventListener("click", () => {
        if (!currentJob) return;
        // Server redirects to /api/download/UUID/filename.ext
        window.location.href = `/api/download/${currentJob.id}?type=final`;
    });

    // --- New Image ---
    btnNew.addEventListener("click", () => {
        currentJob = null;
        if (pollInterval) clearInterval(pollInterval);

        workspace.style.display = "none";
        uploadSection.style.display = "flex";
        fileInput.value = "";

        // Reset options
        document.querySelector('input[name="upscale"][value="0"]').checked = true;
        document.getElementById("remove-bg").checked = false;
        document.querySelector('input[name="format"][value="png"]').checked = true;
    });

    // --- Toast ---
    function showToast(message, type = "info") {
        const toast = document.createElement("div");
        toast.className = `toast toast--${type}`;
        toast.textContent = message;
        toastContainer.appendChild(toast);

        setTimeout(() => {
            toast.style.opacity = "0";
            toast.style.transform = "translateX(40px)";
            toast.style.transition = "all 0.3s ease";
            setTimeout(() => toast.remove(), 300);
        }, 4000);
    }
})();
