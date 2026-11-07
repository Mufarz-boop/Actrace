
"use strict";

document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("add-journal-form");

    // Jika halaman bukan Add Journal, hentikan eksekusi.
    if (!form) return;

    const dateInput = document.getElementById("activity_date");
    const titleInput = document.getElementById("title");
    const titleCounter = document.getElementById("title-counter");

    const photoInput = document.getElementById("photos");
    const uploadArea = document.getElementById("journal-upload-area");
    const browseButton = document.getElementById("journal-browse-button");
    const previewContainer = document.getElementById("journal-photo-preview");

    const submitButton = form.querySelector(
        'button[type="submit"]'
    );

    const submitLabel = submitButton?.querySelector(".btn__label");

    const MAX_PHOTOS = 5;
    const MAX_FILE_SIZE = 5 * 1024 * 1024;

    const ALLOWED_TYPES = [
        "image/jpeg",
        "image/png",
        "image/webp"
    ];

    let selectedFiles = [];
    let objectUrls = [];
    let isSubmitting = false;

    // ==================================================
    // TITLE CHARACTER COUNTER
    // ==================================================

    function updateTitleCounter() {
        if (!titleInput || !titleCounter) return;

        const length = titleInput.value.length;

        titleCounter.textContent = `${length}/150`;

        titleCounter.classList.toggle(
            "is-limit",
            length >= 150
        );
    }

    titleInput?.addEventListener(
        "input",
        updateTitleCounter
    );

    updateTitleCounter();


    // ==================================================
    // DATE VALIDATION
    // ==================================================

    function validateDate() {
        if (!dateInput) return true;

        const selectedDate = dateInput.value;
        const today = dateInput.max;

        if (!selectedDate) {
            dateInput.setCustomValidity(
                "Tanggal aktivitas wajib diisi."
            );

            return false;
        }

        if (selectedDate > today) {
            dateInput.setCustomValidity(
                "Tanggal aktivitas tidak boleh di masa depan."
            );

            return false;
        }

        dateInput.setCustomValidity("");

        return true;
    }

    dateInput?.addEventListener("change", validateDate);


    // ==================================================
    // FILE VALIDATION
    // ==================================================

    function validateFile(file) {
        if (!ALLOWED_TYPES.includes(file.type)) {
            return "Format foto harus JPG, PNG, atau WebP.";
        }

        if (file.size <= 0) {
            return "File foto tidak boleh kosong.";
        }

        if (file.size > MAX_FILE_SIZE) {
            return `${file.name} melebihi batas 5 MB.`;
        }

        return null;
    }


    // ==================================================
    // PHOTO PREVIEW
    // ==================================================

    function revokeObjectUrls() {
        objectUrls.forEach((url) => {
            URL.revokeObjectURL(url);
        });

        objectUrls = [];
    }

    function renderPhotoPreview() {
        if (!previewContainer) return;

        revokeObjectUrls();

        previewContainer.replaceChildren();

        selectedFiles.forEach((file, index) => {
            const wrapper = document.createElement("div");

            wrapper.className = "journal-photo-item";

            const image = document.createElement("img");

            const objectUrl = URL.createObjectURL(file);

            objectUrls.push(objectUrl);

            image.src = objectUrl;
            image.alt = `Photo documentation ${index + 1}`;
            image.loading = "lazy";

            const removeButton = document.createElement("button");

            removeButton.type = "button";
            removeButton.className =
                "journal-photo-item__remove";

            removeButton.setAttribute(
                "aria-label",
                `Remove photo ${index + 1}`
            );

            removeButton.innerHTML = `
                <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="m6 6 12 12M18 6 6 18"/>
                </svg>
            `;

            removeButton.addEventListener("click", () => {
                removePhoto(index);
            });

            wrapper.append(image, removeButton);

            previewContainer.appendChild(wrapper);
        });
    }


    // ==================================================
    // UPDATE FILE INPUT
    // ==================================================

    function synchronizeFileInput() {
        const dataTransfer = new DataTransfer();

        selectedFiles.forEach((file) => {
            dataTransfer.items.add(file);
        });

        photoInput.files = dataTransfer.files;
    }


    // ==================================================
    // REMOVE PHOTO
    // ==================================================

    function removePhoto(index) {
        if (isSubmitting) return;

        selectedFiles.splice(index, 1);

        synchronizeFileInput();
        renderPhotoPreview();
    }


    // ==================================================
    // ADD PHOTOS
    // ==================================================

    function addPhotos(files) {
        if (isSubmitting) return;

        const incomingFiles = Array.from(files);

        if (!incomingFiles.length) return;

        const remainingSlots = MAX_PHOTOS - selectedFiles.length;

        if (remainingSlots <= 0) {
            alert("Maksimal 5 foto untuk setiap jurnal.");
            return;
        }

        let addedCount = 0;

        for (const file of incomingFiles) {
            if (selectedFiles.length >= MAX_PHOTOS) {
                alert("Maksimal 5 foto untuk setiap jurnal.");
                break;
            }

            const validationError = validateFile(file);

            if (validationError) {
                alert(validationError);
                continue;
            }

            // Mencegah pemilihan file yang sama berulang kali.
            const alreadySelected = selectedFiles.some(
                (selected) =>
                    selected.name === file.name &&
                    selected.size === file.size &&
                    selected.lastModified === file.lastModified
            );

            if (alreadySelected) {
                continue;
            }

            selectedFiles.push(file);
            addedCount++;
        }

        if (addedCount > 0) {
            synchronizeFileInput();
            renderPhotoPreview();
        }
    }


    // ==================================================
    // FILE INPUT EVENTS
    // ==================================================

    photoInput?.addEventListener("change", (event) => {
        addPhotos(event.target.files);
    });

    browseButton?.addEventListener("click", () => {
        if (!isSubmitting) {
            photoInput?.click();
        }
    });


    // ==================================================
    // DRAG AND DROP
    // ==================================================

    uploadArea?.addEventListener("dragover", (event) => {
        event.preventDefault();

        if (isSubmitting) return;

        uploadArea.classList.add("is-dragging");
    });

    uploadArea?.addEventListener("dragleave", (event) => {
        if (!uploadArea.contains(event.relatedTarget)) {
            uploadArea.classList.remove("is-dragging");
        }
    });

    uploadArea?.addEventListener("drop", (event) => {
        event.preventDefault();

        uploadArea.classList.remove("is-dragging");

        if (isSubmitting) return;

        addPhotos(event.dataTransfer.files);
    });

    // Mencegah browser membuka file ketika dilepas di luar area upload.
    document.addEventListener("dragover", (event) => {
        if (event.dataTransfer?.types.includes("Files")) {
            event.preventDefault();
        }
    });

    document.addEventListener("drop", (event) => {
        if (event.dataTransfer?.types.includes("Files")) {
            event.preventDefault();
        }
    });


    // ==================================================
    // FORM SUBMISSION
    // ==================================================

    form.addEventListener("submit", (event) => {
        if (isSubmitting) {
            event.preventDefault();
            return;
        }

        if (!validateDate()) {
            event.preventDefault();
            dateInput.reportValidity();
            return;
        }

        if (!form.checkValidity()) {
            event.preventDefault();
            form.reportValidity();
            return;
        }

        if (selectedFiles.length > MAX_PHOTOS) {
            event.preventDefault();

            alert("Maksimal 5 foto untuk setiap jurnal.");
            return;
        }

        // Sinkronisasi file sebelum dikirim ke Flask.
        synchronizeFileInput();

        isSubmitting = true;

        if (submitButton) {
            submitButton.disabled = true;
        }

        if (submitLabel) {
            submitLabel.textContent = "Saving Journal...";
        }

        form.setAttribute("aria-busy", "true");
    });


    // ==================================================
    // CLEANUP
    // ==================================================

    window.addEventListener("pagehide", revokeObjectUrls);
});