/* ==========================================================================
   ACTRACE | logout-animation.js
   Animasi logout "Circular Iris Closing" (lapisan frontend saja).

   Prinsip:
   - Form logout asli (POST + CSRF + endpoint auth.logout) TIDAK diubah.
   - Animasi berjalan di atas halaman, lalu form dikirim apa adanya
     dengan form.submit(). Redirect ke login dilakukan oleh backend.
   - Jika JavaScript mati, overlay hilang, atau animasi gagal, form tetap
     dikirim secara native sehingga logout selalu bisa dilakukan.

   Dimuat di <head> (tanpa defer) agar penjaga tombol Back bisa berjalan
   sebelum halaman dashboard sempat tampil. Pendengar submit memakai event
   delegation sehingga tidak bergantung pada kesiapan DOM.
   ========================================================================== */

(function () {
    'use strict';

    /* -----------------------------------------------------
       KONFIGURASI
    ----------------------------------------------------- */

    var FORM_SELECTOR = '.logout-form';
    var BUTTON_SELECTOR = '.logout-button';
    var OVERLAY_ID = 'logout-transition';

    // Form dikirim ke backend pada akhir tahap Final Message.
    var SUBMIT_AFTER_MS = 3500;

    // Pengguna dengan prefers-reduced-motion: tanpa gerakan iris,
    // tetapi pesan tetap terbaca sebelum form dikirim.
    var SUBMIT_AFTER_REDUCED_MS = 1100;

    // Jika server tidak menjawab setelah form dikirim, kembalikan UI
    // agar pengguna dapat mencoba lagi.
    var RECOVER_AFTER_MS = 15000;

    var STORAGE_KEY = 'actrace:logout-requested';
    var LOADING_LABEL = 'Signing out\u2026';

    var scriptEl = document.currentScript;
    var LOGIN_URL = (scriptEl && scriptEl.getAttribute('data-login-url')) || '/login';

    var state = {
        running: false,
        submitted: false,
        submitTimer: null,
        recoverTimer: null,
        form: null,
        button: null,
        label: null,
        labelText: '',
        overlay: null,
        inertTargets: []
    };


    /* -----------------------------------------------------
       UTILITAS
    ----------------------------------------------------- */

    function prefersReducedMotion() {
        try {
            return !!(
                window.matchMedia &&
                window.matchMedia('(prefers-reduced-motion: reduce)').matches
            );
        } catch (err) {
            return false;
        }
    }

    function storageSet() {
        try { window.sessionStorage.setItem(STORAGE_KEY, String(Date.now())); }
        catch (err) { /* penyimpanan tidak tersedia: abaikan */ }
    }

    function storageClear() {
        try { window.sessionStorage.removeItem(STORAGE_KEY); }
        catch (err) { /* abaikan */ }
    }

    function storageHas() {
        try { return !!window.sessionStorage.getItem(STORAGE_KEY); }
        catch (err) { return false; }
    }


    /* -----------------------------------------------------
       PENJAGA TOMBOL BACK
       Setelah logout diminta, kembali ke halaman dashboard lama
       (dari cache browser / bfcache) tidak boleh menampilkan
       dashboard. Halaman diganti ke login; server tetap menjadi
       penentu akhir karena session sudah dihapus di backend.
    ----------------------------------------------------- */

    function isBackForwardNavigation() {
        try {
            var entries = window.performance.getEntriesByType('navigation');
            if (entries && entries.length) {
                return entries[0].type === 'back_forward';
            }
            return !!(
                window.performance.navigation &&
                window.performance.navigation.type === 2
            );
        } catch (err) {
            return false;
        }
    }

    function bounceToLogin() {
        document.documentElement.classList.add('logout-transition-guard');
        window.location.replace(LOGIN_URL);
    }

    function guardBackNavigation() {
        if (!storageHas()) return;

        if (isBackForwardNavigation()) {
            bounceToLogin();
        } else {
            // Kunjungan baru (mis. login ulang): penanda sudah tidak berlaku.
            storageClear();
        }
    }

    window.addEventListener('pageshow', function (event) {
        // Halaman dipulihkan dari bfcache.
        if (event.persisted) {
            if (storageHas()) {
                bounceToLogin();
            } else if (state.running) {
                resetUi();
            }
        }
    });


    /* -----------------------------------------------------
       KONDISI TOMBOL & OVERLAY
    ----------------------------------------------------- */

    function setButtonLoading(isLoading) {
        var button = state.button;
        if (!button) return;

        if (isLoading) {
            state.label = button.querySelector('span');
            state.labelText = state.label ? state.label.textContent : '';

            if (state.label) state.label.textContent = LOADING_LABEL;

            button.classList.add('is-loading');
            button.setAttribute('aria-busy', 'true');
            button.disabled = true;
        } else {
            if (state.label) state.label.textContent = state.labelText;

            button.classList.remove('is-loading');
            button.removeAttribute('aria-busy');
            button.disabled = false;
        }
    }

    function setBackgroundInert(isInert) {
        if (isInert) {
            state.inertTargets = [];

            var layout = document.querySelector('.student-layout');
            var skip = document.querySelector('.skip-link');

            [layout, skip].forEach(function (node) {
                if (node && !node.hasAttribute('inert')) {
                    node.setAttribute('inert', '');
                    state.inertTargets.push(node);
                }
            });
        } else {
            state.inertTargets.forEach(function (node) {
                node.removeAttribute('inert');
            });
            state.inertTargets = [];
        }
    }

    function onOverlayKeydown(event) {
        // Fokus dikunci di overlay selama logout berjalan.
        if (event.key === 'Tab') event.preventDefault();
    }

    function showOverlay(overlay) {
        overlay.hidden = false;
        overlay.setAttribute('aria-hidden', 'false');
        overlay.addEventListener('keydown', onOverlayKeydown);

        // Paksa reflow agar animasi CSS dimulai dari awal.
        void overlay.offsetWidth;

        overlay.classList.add('is-active');
        setBackgroundInert(true);

        try { overlay.focus({ preventScroll: true }); }
        catch (err) { /* abaikan */ }
    }

    function hideOverlay(overlay) {
        overlay.classList.remove('is-active');
        overlay.removeEventListener('keydown', onOverlayKeydown);
        overlay.setAttribute('aria-hidden', 'true');
        overlay.hidden = true;
        setBackgroundInert(false);
    }

    function resetUi() {
        window.clearTimeout(state.submitTimer);
        window.clearTimeout(state.recoverTimer);

        if (state.overlay) hideOverlay(state.overlay);
        setButtonLoading(false);
        storageClear();

        state.running = false;
        state.submitted = false;
        state.submitTimer = null;
        state.recoverTimer = null;
    }


    /* -----------------------------------------------------
       PENGIRIMAN FORM (SATU KALI)
    ----------------------------------------------------- */

    function submitNow() {
        if (state.submitted) return;
        state.submitted = true;

        window.clearTimeout(state.submitTimer);

        var form = state.form;
        if (!form) return;

        // Penanda dipasang tepat sebelum kirim, bukan saat animasi mulai,
        // supaya logout yang tidak jadi dikirim tidak ikut menandai.
        storageSet();

        try {
            // Memanggil submit bawaan form: method POST, action, dan
            // csrf_token tetap persis seperti di markup asli.
            window.HTMLFormElement.prototype.submit.call(form);
        } catch (err) {
            state.submitted = false;
            resetUi();
            return;
        }

        // Jaring pengaman bila server tidak menjawab.
        state.recoverTimer = window.setTimeout(resetUi, RECOVER_AFTER_MS);
    }


    /* -----------------------------------------------------
       MEMULAI ANIMASI
    ----------------------------------------------------- */

    function overlayIsStyled(overlay) {
        // Jika student.css gagal dimuat, overlay tidak boleh tampil
        // sebagai blok tanpa gaya. Kembali ke submit native.
        return window.getComputedStyle(overlay).position === 'fixed';
    }

    function start(form, overlay) {
        if (!overlayIsStyled(overlay)) {
            throw new Error('logout overlay is not styled');
        }

        state.running = true;
        state.form = form;
        state.button = form.querySelector(BUTTON_SELECTOR);
        state.overlay = overlay;

        // Tahap 1: tombol loading + overlay aktif.
        setButtonLoading(true);
        showOverlay(overlay);

        // Tahap 2-4 dijalankan oleh CSS (animation-delay).
        // Tahap 5: kirim form setelah timeline selesai.
        var delay = prefersReducedMotion()
            ? SUBMIT_AFTER_REDUCED_MS
            : SUBMIT_AFTER_MS;

        state.submitTimer = window.setTimeout(submitNow, delay);
    }

    function onSubmit(event) {
        var form = event.target;

        if (!form || !form.matches || !form.matches(FORM_SELECTOR)) return;

        // Sudah berjalan: tolak submit tambahan (klik berulang / Enter).
        if (state.running) {
            event.preventDefault();
            return;
        }

        // Pengendali lain sudah membatalkan submit: hormati.
        if (event.defaultPrevented) return;

        var overlay = document.getElementById(OVERLAY_ID);

        // Overlay tidak ada: biarkan submit native berjalan.
        if (!overlay) return;

        event.preventDefault();

        try {
            start(form, overlay);
        } catch (err) {
            // Animasi gagal: logout tetap dilakukan tanpa animasi.
            window.clearTimeout(state.submitTimer);

            if (state.overlay) hideOverlay(state.overlay);

            state.running = true;
            state.submitted = false;
            state.form = form;

            submitNow();
        }
    }

    document.addEventListener('submit', onSubmit, true);


    /* -----------------------------------------------------
       INISIALISASI
    ----------------------------------------------------- */

    guardBackNavigation();

})();