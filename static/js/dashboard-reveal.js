/* ==========================================================================
   ACTRACE | dashboard-reveal.js
   Orkestrasi Staggered Dashboard Reveal (lapisan frontend saja).

   Pembagian tugas:
   - Keadaan awal (tersembunyi) dipasang oleh skrip kecil di <head>
     dashboard.html lewat kelas html.js-reveal, agar tidak ada kilatan.
     Skrip itu tidak memasangnya bila prefers-reduced-motion aktif atau
     halaman dibuka lewat tombol Back/Forward.
   - Berkas ini hanya menentukan KAPAN reveal dimulai (menambah
     html.is-revealing) dan membersihkan kelas setelah selesai. Seluruh
     gerak ada di CSS (student.css, bagian "STAGGERED DASHBOARD REVEAL").

   Koordinasi dengan animasi login:
   - Setelah login, login-animation.js menutup dashboard dengan overlay
     iris selama ~3,5 detik. Reveal menunggu overlay itu selesai
     (atribut hidden kembali true), lalu dimulai. Sinyal bahwa login baru
     terjadi adalah kelas html.login-reveal-pending dari login-animation.js.

   Tanpa JavaScript, dashboard tampil biasa karena kelas
   .js-reveal tidak pernah terpasang.
   ========================================================================== */

(function () {
    'use strict';

    var root = document.documentElement;

    // Skrip <head> tidak memasang kelas (reduced motion, Back/Forward, dsb.).
    if (!root.classList.contains('js-reveal')) return;

    var REVEALING_CLASS = 'is-revealing';
    var HIDDEN_CLASS = 'js-reveal';

    // Cukup di atas durasi terpanjang:
    // indeks tertinggi * stagger + durasi item (lihat token --motion-*).
    var CLEANUP_MS = 1500;

    // Jaring pengaman bila overlay login tidak pernah memberi sinyal selesai.
    var WAIT_FAILSAFE_MS = 5000;

    var PENDING_CLASS = 'login-reveal-pending';

    var started = false;
    var sawOverlay = false;
    var observers = [];

    function cleanup() {
        root.classList.remove(REVEALING_CLASS);
        root.classList.remove(HIDDEN_CLASS);
    }

    function start() {
        if (started) return; // cegah inisialisasi ganda
        started = true;

        observers.forEach(function (observer) { observer.disconnect(); });
        observers = [];

        // Dua frame agar keadaan awal sempat digambar sebelum animasi mulai.
        window.requestAnimationFrame(function () {
            window.requestAnimationFrame(function () {
                root.classList.add(REVEALING_CLASS);
                window.setTimeout(cleanup, CLEANUP_MS);
            });
        });
    }

    function init() {
        var overlay = document.getElementById('login-transition');

        // Login baru saja berhasil bila login-animation.js sudah memasang
        // kelas pending di <head>. Skrip defer ini berjalan SEBELUM overlay
        // ditampilkan (DOMContentLoaded), jadi kelas itulah sinyalnya.
        var loginPending = root.classList.contains(PENDING_CLASS);

        if (!overlay || !loginPending || !('MutationObserver' in window)) {
            start();
            return;
        }

        // Overlay: hidden=false saat iris tampil, hidden=true saat selesai.
        // Kelas pending dilepas lebih awal (overlay sudah menutup layar)
        // atau, bila overlay gagal dipakai, tanpa overlay pernah tampil.
        function check() {
            if (!overlay.hidden) {
                sawOverlay = true;
                return;
            }

            if (sawOverlay || !root.classList.contains(PENDING_CLASS)) {
                start();
            }
        }

        var overlayObserver = new MutationObserver(check);
        overlayObserver.observe(overlay, {
            attributes: true,
            attributeFilter: ['hidden']
        });

        var rootObserver = new MutationObserver(check);
        rootObserver.observe(root, {
            attributes: true,
            attributeFilter: ['class']
        });

        observers.push(overlayObserver, rootObserver);

        check();

        window.setTimeout(start, WAIT_FAILSAFE_MS);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
