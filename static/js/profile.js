/* ==========================================================================
   ACTRACE | profile.js
   Peningkatan progresif untuk halaman My Profile (lapisan frontend saja).

   Fitur:
   - Pratinjau foto langsung + validasi tipe/ukuran SEBELUM diunggah.
   - Ringkasan profil (nama, username, inisial) ikut berubah saat mengetik.
   - Validasi rentang tanggal PKL (selesai tidak boleh sebelum mulai).
   - Penanda "ada perubahan belum disimpan" + tombol simpan yang tahu diri.
   - Penjaga keluar halaman: dialog konfirmasi saat ada perubahan, memakai
     beforeunload hanya untuk tutup tab / muat ulang / tautan eksternal.

   Validasi sebenarnya tetap dilakukan server (app/student/routes.py).
   Tanpa JavaScript, formulir tetap bekerja seperti biasa.
   ========================================================================== */

(function () {
    'use strict';

    var form = document.getElementById('profile-form');
    if (!form) return;

    var TRACKED_SELECTOR =
        'input[type="text"]:not(:disabled), input[type="email"], input[type="date"]';

    var ALLOWED_TYPES = ['image/jpeg', 'image/png', 'image/webp'];
    var maxPhotoBytes = parseInt(form.getAttribute('data-max-photo-bytes'), 10) || 2 * 1024 * 1024;

    var fields = Array.prototype.slice.call(form.querySelectorAll(TRACKED_SELECTOR));
    var photoInput = document.getElementById('profile-photo');
    var removeBox = form.querySelector('[data-remove-photo]');
    var photoField = form.querySelector('[data-photo-field]');
    var photoPreview = form.querySelector('[data-photo-preview]');
    var photoStatus = form.querySelector('[data-photo-status]');
    var dirtyNote = form.querySelector('[data-dirty-note]');
    var startInput = document.getElementById('internship-start-date');
    var endInput = document.getElementById('internship-end-date');
    var dateError = form.querySelector('[data-date-error]');
    var dialog = document.getElementById('profile-leave-dialog');

    var summaryAvatar = document.querySelector('[data-summary-avatar]');
    var originalPreviewHtml = photoPreview ? photoPreview.innerHTML : '';
    var originalSummaryHtml = summaryAvatar ? summaryAvatar.innerHTML : '';

    var initial = {};
    var forcedDirty = form.getAttribute('data-restored') === 'true';
    var submitting = false;
    var allowLeave = false;
    var previewUrl = null;
    var pending = null; // { type: 'link' | 'form', node: Element }


    /* -----------------------------------------------------
       KEADAAN DIRTY
    ----------------------------------------------------- */

    fields.forEach(function (input) {
        initial[input.id] = input.value;
    });

    function photoChanged() {
        var hasNewPhoto = !!(photoInput && photoInput.files && photoInput.files.length);
        var removing = !!(removeBox && removeBox.checked);
        return hasNewPhoto || removing;
    }

    function isDirty() {
        if (forcedDirty || photoChanged()) return true;

        for (var i = 0; i < fields.length; i++) {
            if (fields[i].value !== initial[fields[i].id]) return true;
        }

        return false;
    }

    function refreshDirty() {
        var dirty = isDirty();

        form.classList.toggle('is-dirty', dirty);
        form.classList.toggle('is-clean', !dirty);

        if (dirtyNote) {
            dirtyNote.textContent = dirty
                ? 'Ada perubahan yang belum disimpan'
                : 'Belum ada perubahan';
        }
    }


    /* -----------------------------------------------------
       RINGKASAN LANGSUNG
    ----------------------------------------------------- */

    function syncSummary() {
        var nameInput = document.getElementById('full-name');
        var userInput = document.getElementById('username');

        if (nameInput) {
            var name = nameInput.value.trim() || initial['full-name'] || '';

            document.querySelectorAll('[data-live="full_name"]').forEach(function (el) {
                el.textContent = name;
            });

            document.querySelectorAll('[data-live-initial]').forEach(function (el) {
                el.textContent = (name.charAt(0) || '?').toUpperCase();
            });
        }

        if (userInput) {
            var username = userInput.value.trim() || initial.username || '';

            document.querySelectorAll('[data-live="username"]').forEach(function (el) {
                el.textContent = username;
            });
        }
    }


    /* -----------------------------------------------------
       FOTO PROFIL
    ----------------------------------------------------- */

    function formatSize(bytes) {
        if (bytes < 1024 * 1024) {
            return Math.max(1, Math.round(bytes / 1024)) + ' KB';
        }

        return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    }

    function setStatus(message, state) {
        if (!photoStatus) return;

        photoStatus.textContent = message || '';
        photoStatus.classList.toggle('is-error', state === 'error');
        photoStatus.classList.toggle('is-ok', state === 'ok');
    }

    function swapAnimation(el) {
        if (!el) return;

        el.classList.remove('is-swapped');
        void el.offsetWidth; // ulangi animasi
        el.classList.add('is-swapped');
    }

    function revokePreview() {
        if (previewUrl) {
            URL.revokeObjectURL(previewUrl);
            previewUrl = null;
        }
    }

    function showPhoto(url) {
        [photoPreview, summaryAvatar].forEach(function (box) {
            if (!box) return;

            box.innerHTML = '';

            var img = document.createElement('img');
            img.src = url;
            img.alt = 'Pratinjau foto profil baru';
            box.appendChild(img);

            swapAnimation(box);
        });
    }

    function restorePhoto() {
        revokePreview();

        if (photoPreview) {
            photoPreview.innerHTML = originalPreviewHtml;
            swapAnimation(photoPreview);
        }

        if (summaryAvatar) {
            summaryAvatar.innerHTML = originalSummaryHtml;
            swapAnimation(summaryAvatar);
        }

        syncSummary();
    }

    function clearFile() {
        if (photoInput) photoInput.value = '';
    }

    function onPhotoChange() {
        var file = photoInput.files && photoInput.files[0];

        if (!file) {
            restorePhoto();
            setStatus('');
            refreshDirty();
            return;
        }

        if (ALLOWED_TYPES.indexOf(file.type) === -1) {
            clearFile();
            restorePhoto();
            setStatus('Format harus JPEG, PNG, atau WebP.', 'error');
            refreshDirty();
            return;
        }

        if (file.size > maxPhotoBytes) {
            clearFile();
            restorePhoto();
            setStatus(
                'Ukuran ' + formatSize(file.size) + ' melebihi batas ' +
                formatSize(maxPhotoBytes) + '.',
                'error'
            );
            refreshDirty();
            return;
        }

        // Foto baru membatalkan permintaan hapus (server juga begitu).
        if (removeBox) removeBox.checked = false;
        if (photoField) photoField.classList.remove('is-removing');

        revokePreview();
        previewUrl = URL.createObjectURL(file);
        showPhoto(previewUrl);

        setStatus(file.name + ' (' + formatSize(file.size) + ')', 'ok');
        refreshDirty();
    }

    function onRemoveChange() {
        var removing = removeBox.checked;

        if (photoField) photoField.classList.toggle('is-removing', removing);

        if (removing) {
            // Memilih hapus membatalkan foto baru yang belum diunggah.
            clearFile();
            restorePhoto();
            setStatus('Foto saat ini akan dihapus setelah disimpan.');
        } else {
            setStatus('');
        }

        refreshDirty();
    }

    if (photoInput) photoInput.addEventListener('change', onPhotoChange);
    if (removeBox) removeBox.addEventListener('change', onRemoveChange);


    /* -----------------------------------------------------
       RENTANG TANGGAL
    ----------------------------------------------------- */

    function validateDates() {
        if (!startInput || !endInput) return;

        endInput.min = startInput.value || '';

        var invalid =
            !!startInput.value &&
            !!endInput.value &&
            endInput.value < startInput.value;

        endInput.setCustomValidity(
            invalid ? 'Tanggal selesai tidak boleh sebelum tanggal mulai.' : ''
        );

        endInput.classList.toggle('is-invalid', invalid);

        if (dateError) {
            dateError.textContent = invalid
                ? 'Tanggal selesai tidak boleh sebelum tanggal mulai.'
                : '';
            dateError.classList.toggle('is-visible', invalid);
        }
    }

    if (startInput) startInput.addEventListener('input', validateDates);
    if (endInput) endInput.addEventListener('input', validateDates);


    /* -----------------------------------------------------
       PENJAGA KELUAR HALAMAN
    ----------------------------------------------------- */

    function isPlainLeftClick(event) {
        return (
            event.button === 0 &&
            !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey
        );
    }

    function askBeforeLeaving(type, node) {
        pending = { type: type, node: node };

        if (dialog && typeof dialog.showModal === 'function') {
            dialog.showModal();
            return true;
        }

        // Tanpa <dialog>: serahkan ke konfirmasi bawaan peramban.
        return window.confirm('Ada perubahan yang belum disimpan. Buang perubahan?');
    }

    function leaveNow() {
        var target = pending;
        pending = null;
        allowLeave = true;

        if (!target) return;

        if (target.type === 'link') {
            target.node.click();
        } else if (typeof target.node.requestSubmit === 'function') {
            target.node.requestSubmit();
        } else {
            target.node.submit();
        }
    }

    document.addEventListener('click', function (event) {
        if (allowLeave || submitting || event.defaultPrevented) return;
        if (!isPlainLeftClick(event) || !isDirty()) return;

        var link = event.target.closest && event.target.closest('a[href]');

        if (!link || (link.target && link.target !== '_self')) return;
        if (link.hasAttribute('download')) return;

        var url;

        try {
            url = new URL(link.href, window.location.href);
        } catch (err) {
            return;
        }

        // Tautan eksternal ditangani beforeunload; hash di halaman ini dilewati.
        if (url.origin !== window.location.origin) return;
        if (
            url.pathname === window.location.pathname &&
            url.search === window.location.search &&
            url.hash
        ) {
            return;
        }

        event.preventDefault();
        event.stopImmediatePropagation();

        if (askBeforeLeaving('link', link) === true && !(dialog && dialog.open)) {
            // confirm() bawaan menjawab ya: lanjutkan.
            leaveNow();
        }
    }, true);

    // Formulir lain di halaman (mis. Sign Out) juga dijaga.
    document.addEventListener('submit', function (event) {
        var other = event.target;

        if (other === form || allowLeave || submitting) return;
        if (!isDirty()) return;

        event.preventDefault();
        event.stopImmediatePropagation();

        if (askBeforeLeaving('form', other) === true && !(dialog && dialog.open)) {
            leaveNow();
        }
    }, true);

    if (dialog) {
        var stayButton = dialog.querySelector('[data-leave-stay]');
        var confirmButton = dialog.querySelector('[data-leave-confirm]');

        if (stayButton) {
            stayButton.addEventListener('click', function () {
                pending = null;
                dialog.close();
            });
        }

        if (confirmButton) {
            confirmButton.addEventListener('click', function () {
                dialog.close();
                leaveNow();
            });
        }

        // Klik di latar gelap = tetap di halaman.
        dialog.addEventListener('click', function (event) {
            if (event.target === dialog) {
                pending = null;
                dialog.close();
            }
        });

        dialog.addEventListener('cancel', function () {
            pending = null;
        });
    }

    window.addEventListener('beforeunload', function (event) {
        if (allowLeave || submitting || !isDirty()) return;

        event.preventDefault();
        event.returnValue = '';
    });


    /* -----------------------------------------------------
       KIRIM FORMULIR
    ----------------------------------------------------- */

    // Fase capture: harus berjalan SEBELUM penangan loading di main.js,
    // supaya submit kosong tidak meninggalkan tombol dalam keadaan loading.
    form.addEventListener('submit', function (event) {
        validateDates();

        if (!isDirty()) {
            // Tidak ada yang perlu disimpan.
            event.preventDefault();
            event.stopImmediatePropagation();

            if (dirtyNote) dirtyNote.textContent = 'Belum ada perubahan untuk disimpan';

            return;
        }

        submitting = true;
    }, true);

    // Dipulihkan dari bfcache: kembalikan keadaan bersih.
    window.addEventListener('pageshow', function (event) {
        if (!event.persisted) return;

        submitting = false;
        allowLeave = false;
        pending = null;
        refreshDirty();
    });


    /* -----------------------------------------------------
       INISIALISASI
    ----------------------------------------------------- */

    form.addEventListener('input', function () {
        syncSummary();
        refreshDirty();
    });

    validateDates();
    refreshDirty();

})();
