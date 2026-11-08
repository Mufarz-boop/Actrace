document.addEventListener("DOMContentLoaded", function () {
    const photoItems = Array.from(
        document.querySelectorAll(".gallery-photo")
    );

    const lightbox = document.getElementById("galleryLightbox");
    const lightboxImage = document.getElementById(
        "galleryLightboxImage"
    );

    const counter = document.getElementById(
        "galleryLightboxCounter"
    );

    const closeButton = document.getElementById(
        "galleryLightboxClose"
    );

    const previousButton = document.getElementById(
        "galleryLightboxPrev"
    );

    const nextButton = document.getElementById(
        "galleryLightboxNext"
    );

    if (
        !lightbox ||
        !lightboxImage ||
        !closeButton ||
        !previousButton ||
        !nextButton
    ) {
        return;
    }

    if (!photoItems.length) {
        return;
    }

    let currentIndex = 0;
    let previousFocus = null;

    function updateLightbox() {
        const currentPhoto = photoItems[currentIndex];

        lightboxImage.src = currentPhoto.dataset.photoUrl;

        counter.textContent =
            `${currentIndex + 1} / ${photoItems.length}`;

        const hasMultiplePhotos = photoItems.length > 1;

        previousButton.hidden = !hasMultiplePhotos;
        nextButton.hidden = !hasMultiplePhotos;
    }

    function openLightbox(index) {
        currentIndex = index;
        previousFocus = document.activeElement;

        updateLightbox();

        lightbox.classList.add("is-active");
        lightbox.setAttribute("aria-hidden", "false");

        document.body.style.overflow = "hidden";

        closeButton.focus();
    }

    function closeLightbox() {
        lightbox.classList.remove("is-active");
        lightbox.setAttribute("aria-hidden", "true");

        lightboxImage.removeAttribute("src");

        document.body.style.overflow = "";

        if (previousFocus) {
            previousFocus.focus();
            previousFocus = null;
        }
    }

    function showNext() {
        currentIndex =
            (currentIndex + 1) % photoItems.length;

        updateLightbox();
    }

    function showPrevious() {
        currentIndex =
            (currentIndex - 1 + photoItems.length) %
            photoItems.length;

        updateLightbox();
    }

    photoItems.forEach(function (photo, index) {
        photo.addEventListener("click", function () {
            openLightbox(index);
        });
    });

    closeButton.addEventListener("click", closeLightbox);
    nextButton.addEventListener("click", showNext);
    previousButton.addEventListener("click", showPrevious);

    lightbox.addEventListener("click", function (event) {
        if (event.target === lightbox) {
            closeLightbox();
        }
    });

    document.addEventListener("keydown", function (event) {
        if (!lightbox.classList.contains("is-active")) {
            return;
        }

        if (event.key === "Escape") {
            closeLightbox();
        }

        if (
            event.key === "ArrowRight" &&
            photoItems.length > 1
        ) {
            showNext();
        }

        if (
            event.key === "ArrowLeft" &&
            photoItems.length > 1
        ) {
            showPrevious();
        }
    });
});