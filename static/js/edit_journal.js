document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("edit-journal-form");
    if (!form) return;

    const fileInput = document.getElementById("edit-photos");
    const previews = document.getElementById("edit-new-photo-preview");
    const countLabel = document.getElementById("edit-photo-count");
    const remainingLabel = document.getElementById("edit-photo-remaining");
    const saveButton = document.getElementById("edit-save-button");
    let selectedFiles = [];

    const remainingExisting = () => {
        const all = [...document.querySelectorAll("[data-remove-photo]")];
        return all.filter(item => !item.checked).length;
    };

    const renderCount = () => {
        const existing = remainingExisting();
        const total = existing + selectedFiles.length;
        countLabel.textContent = total;
        remainingLabel.textContent = `Kapasitas tersisa ${Math.max(0, 5-total)} foto`;
        remainingLabel.classList.toggle("is-limit", total > 5);
    };

    document.querySelectorAll("[data-remove-photo]").forEach(input => {
        input.addEventListener("change", () => {
            if (remainingExisting() + selectedFiles.length > 5) {
                input.checked = !input.checked;
                alert("Jumlah foto tidak boleh melebihi 5.");
                return;
            }
            input.closest(".edit-existing-photo").classList.toggle("is-removed", input.checked);
            renderCount();
        });
    });

    fileInput.addEventListener("change", () => {
        selectedFiles = [...fileInput.files];
        if (remainingExisting() + selectedFiles.length > 5) {
            selectedFiles = [];
            fileInput.value = "";
            previews.replaceChildren();
            alert("Jumlah foto baru melebihi kapasitas yang tersedia. Pilih lebih sedikit foto atau tandai foto lama untuk dihapus.");
            renderCount();
            return;
        }
        previews.replaceChildren();

        selectedFiles.forEach(file => {
            const card = document.createElement("div");
            card.className = "edit-new-photo";
            const image = document.createElement("img");
            const label = document.createElement("span");
            label.textContent = file.name;
            card.append(image, label);
            previews.append(card);
            if (file.type.startsWith("image/")) {
                const reader = new FileReader();
                reader.onload = event => image.src = event.target.result;
                reader.readAsDataURL(file);
            }
        });
        renderCount();
    });

    form.addEventListener("submit", event => {
        const title = document.getElementById("edit-title").value.trim();
        const description = document.getElementById("edit-description").value.trim();
        const total = remainingExisting() + selectedFiles.length;

        if (!title || !description) {
            event.preventDefault();
            alert("Judul dan deskripsi wajib diisi.");
            return;
        }
        if (total > 5) {
            event.preventDefault();
            alert("Maksimal 5 foto. Kurangi foto baru atau pilih foto lama untuk dihapus.");
            return;
        }
        if (selectedFiles.some(file => file.size > 5 * 1024 * 1024)) {
            event.preventDefault();
            alert("Ukuran setiap foto maksimal 5 MB.");
            return;
        }

        saveButton.disabled = true;
        saveButton.querySelector("span").textContent = "Menyimpan...";
        saveButton.insertAdjacentHTML("afterbegin", '<i class="fas fa-spinner fa-spin"></i>');
    });

    renderCount();
});
