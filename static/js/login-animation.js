/* ==========================================================================
   ACTRACE | login-animation.js
   Animasi login "Circular Iris Opening" (lapisan frontend saja).

   Cara kerja:
   - Halaman login: saat form login dikirim, skrip hanya menaruh penanda
     waktu di sessionStorage. Form TIDAK dicegat, TIDAK ditunda, dan tetap
     dikirim native (POST + CSRF + endpoint auth.login tidak berubah).
   - Jika kredensial salah, server me-render ulang halaman login. Skrip
     menghapus penanda saat halaman itu dimuat, jadi animasi tidak pernah
     tampil untuk login yang gagal.
   - Jika kredensial benar, server membuat session lalu me-redirect ke
     dashboard. Di dashboard (tag <script> dengan atribut data-reveal),
     penanda dikonsumsi sekali dan iris dibuka di atas dashboard yang
     sudah dirender. Dashboard sampai ke browser hanya jika backend sudah
     menyatakan login berhasil.
   - Jika JavaScript mati atau gagal dimuat, login tetap berjalan normal,
     hanya tanpa animasi.

   Dimuat di <head> pada dashboard (tanpa defer) agar dashboard dapat
   disembunyikan sebelum sempat tampil sekilas. Pada halaman login dimuat
   dengan defer.
   ========================================================================== */

(function () {
    'use strict';

    /* -----------------------------------------------------
       KONFIGURASI
    ----------------------------------------------------- */

    var FORM_SELECTOR = '[data-login-form]';
    var OVERLAY_ID = 'login-transition';
    var PENDING_CLASS = 'login-reveal-pending';

    var STORAGE_KEY = 'actrace:login-requested';

    // Penanda dianggap basi setelah jeda ini (mis. koneksi putus saat kirim).
    var FLAG_TTL_MS = 15000;

    // Timeline (harus sejalan dengan variabel --li-* di student.css):
    // 0-500 overlay navy | 500-1800 iris membuka | 1800-2700 logo
    // 2700-3500 logo memudar, overlay hilang.
    var TOTAL_MS = 3500;

    // prefers-reduced-motion: tanpa gerakan iris, hanya logo singkat + fade.
    var TOTAL_REDUCED_MS = 1300;

    // Jaring pengaman: dashboard tidak boleh tetap tersembunyi.
    var FAILSAFE_MS = 6000;

    var scriptEl = document.currentScript;
    var REVEAL_MODE = !!(scriptEl && scriptEl.hasAttribute('data-reveal'));

    var state = {
        started: false,
        overlay: null,
        timer: null,
        failsafe: null,
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

    function setFlag() {
        try { window.sessionStorage.setItem(STORAGE_KEY, String(Date.now())); }
        catch (err) { /* penyimpanan tidak tersedia: animasi dilewati */ }
    }

    function clearFlag() {
        try { window.sessionStorage.removeItem(STORAGE_KEY); }
        catch (err) { /* abaikan */ }
    }

    // Membaca penanda sekaligus menghapusnya agar animasi tidak berulang
    // saat halaman dimuat ulang.
    function consumeFlag() {
        var raw = null;

        try { raw = window.sessionStorage.getItem(STORAGE_KEY); }
        catch (err) { return false; }

        clearFlag();

        if (!raw) return false;

        var age = Date.now() - parseInt(raw, 10);

        return isFinite(age) && age >= 0 && age <= FLAG_TTL_MS;
    }

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

    function releasePending() {
        document.documentElement.classList.remove(PENDING_CLASS);
    }


    /* -----------------------------------------------------
       HALAMAN LOGIN: PASANG PENANDA SAAT FORM DIKIRIM
       Tidak ada preventDefault dan tidak ada penundaan.
    ----------------------------------------------------- */

    function onSubmit(event) {
        var form = event.target;

        if (!form || !form.matches || !form.matches(FORM_SELECTOR)) return;

        // Submit yang dibatalkan pengendali lain (mis. klik ganda): abaikan.
        if (event.defaultPrevented) return;

        setFlag();
    }

    document.addEventListener('submit', onSubmit);

    // Halaman login dipulihkan dari bfcache: penanda lama tidak berlaku.
    window.addEventListener('pageshow', function (event) {
        if (!event.persisted) return;

        if (!REVEAL_MODE) {
            clearFlag();
        } else if (state.started && state.overlay) {
            finish();
        }
    });


    /* -----------------------------------------------------
       DASHBOARD: KONDISI OVERLAY
    ----------------------------------------------------- */

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
        // Fokus tidak berpindah ke dashboard selama animasi berjalan.
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

    // Akhiri animasi: overlay hilang, dashboard dapat langsung dipakai.
    function finish() {
        window.clearTimeout(state.timer);
        window.clearTimeout(state.failsafe);

        if (state.overlay) hideOverlay(state.overlay);

        releasePending();

        state.timer = null;
        state.failsafe = null;
    }


    /* -----------------------------------------------------
       DASHBOARD: MEMULAI ANIMASI
    ----------------------------------------------------- */

    function overlayIsStyled(overlay) {
        // Jika student.css gagal dimuat, overlay tidak boleh tampil
        // sebagai blok tanpa gaya.
        return window.getComputedStyle(overlay).position === 'fixed';
    }

    function start() {
        if (state.started) return; // cegah animasi ganda
        state.started = true;

        var overlay = document.getElementById(OVERLAY_ID);

        if (!overlay || !overlayIsStyled(overlay)) {
            releasePending();
            return;
        }

        state.overlay = overlay;

        try {
            showOverlay(overlay);
        } catch (err) {
            finish();
            return;
        }

        // Overlay navy sudah menutup layar; dashboard boleh dirender di
        // bawahnya. Iris yang membukanya secara bertahap.
        window.requestAnimationFrame(releasePending);

        state.timer = window.setTimeout(
            finish,
            prefersReducedMotion() ? TOTAL_REDUCED_MS : TOTAL_MS
        );
    }


    /* -----------------------------------------------------
       INISIALISASI
    ----------------------------------------------------- */

    if (!REVEAL_MODE) {
        // Halaman login (termasuk render ulang setelah login gagal).
        clearFlag();
        return;
    }

    if (!consumeFlag() || isBackForwardNavigation()) return;

    // Sembunyikan dashboard sampai overlay siap (lihat student.css).
    document.documentElement.classList.add(PENDING_CLASS);

    state.failsafe = window.setTimeout(finish, FAILSAFE_MS);

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }

})();
