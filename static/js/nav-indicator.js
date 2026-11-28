/* ==========================================================================
   ACTRACE | nav-indicator.js
   Animated Navigation Indicator untuk sidebar (lapisan frontend saja).

   Prinsip:
   - Link navigasi asli dan atribut aria-current dari Flask TIDAK diubah.
     Item aktif ditentukan server (request.endpoint) lewat .nav-link--active.
   - Satu elemen .nav-indicator dibuat di dalam .sidebar__top dan hanya
     bergeser dengan transform. Ia melayani kedua grup menu (WORKSPACE dan
     PERSONAL).
   - ACTRACE memakai navigasi server-side (halaman dimuat ulang tiap menu).
     Supaya perpindahan terasa mulus, indikator dibuat bergerak dalam DUA
     tahap yang menyambung:

       Tahap 1 (halaman asal): begitu link diklik, indikator langsung
       meluncur ke item tujuan (optimistik) tanpa menunggu server. Waktu
       klik dan item asal/tujuan dicatat di sessionStorage.

       Tahap 2 (halaman tujuan): bila gerakan tahap 1 belum selesai saat
       halaman baru tampil, gerakan DILANJUTKAN dari titik yang sama
       (currentTime = waktu yang sudah berlalu), bukan diulang dari awal.
       Bila sudah selesai, indikator langsung diam di item aktif.

   - Klik tidak dicegat dan tidak ditunda; navigasi tetap native.
   - Jika JavaScript mati, gaya aktif statis (.nav-link--active) tetap
     dipakai.
   ========================================================================== */

(function () {
    'use strict';

    var root = document.documentElement;
    var sidebar = document.getElementById('sidebar');
    var container = sidebar && sidebar.querySelector('.sidebar__top');

    if (!sidebar || !container) return;

    var LINK_SELECTOR = '.nav-link';
    var ACTIVE_SELECTOR = '.nav-link--active';
    var STORAGE_KEY = 'actrace:nav';

    // Penanda dianggap basi setelah jeda ini.
    var FLAG_TTL_MS = 10000;

    // Harus sama dengan --motion-nav-duration (300ms) dan --motion-ease
    // di student.css, supaya tahap 1 dan tahap 2 identik.
    var SLIDE_MS = 300;
    var SLIDE_EASING = 'cubic-bezier(.22, 1, .36, 1)';

    // Bila navigasi tidak kunjung berpindah halaman (dibatalkan, server
    // lambat sekali), indikator dikembalikan ke item aktif.
    var PENDING_REVERT_MS = 8000;

    var indicator = null;
    var ready = false;
    var activeAnimation = null;
    var pendingTimer = null;


    /* -----------------------------------------------------
       DETEKSI FITUR
    ----------------------------------------------------- */

    // Cross-document View Transitions (Chrome 126+, Safari 18.2+).
    // Peramban lain memakai animasi masuk CSS biasa (html.no-vt).
    // Dashboard punya reveal sendiri (js-reveal), jadi tidak dobel animasi.
    if (
        !('CSSViewTransitionRule' in window) &&
        !root.classList.contains('js-reveal')
    ) {
        root.classList.add('no-vt');
    }

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

    // Back/Forward tidak memakai animasi masuk halaman.
    if (isBackForwardNavigation()) {
        root.classList.add('no-page-motion');
    }


    /* -----------------------------------------------------
       PENYIMPANAN ANTAR-HALAMAN
    ----------------------------------------------------- */

    function linkKey(link) {
        // Path tanpa query/hash cukup unik untuk menu sidebar ACTRACE.
        return link.pathname;
    }

    function findLinkByKey(key) {
        var links = container.querySelectorAll(LINK_SELECTOR);

        for (var i = 0; i < links.length; i++) {
            if (linkKey(links[i]) === key) return links[i];
        }

        return null;
    }

    function saveNav(fromKey, toKey) {
        try {
            window.sessionStorage.setItem(
                STORAGE_KEY,
                JSON.stringify({ from: fromKey, to: toKey, ts: Date.now() })
            );
        } catch (err) { /* penyimpanan tidak tersedia: tanpa sambungan */ }
    }

    function clearNav() {
        try {
            window.sessionStorage.removeItem(STORAGE_KEY);
        } catch (err) { /* abaikan */ }
    }

    // Dibaca sekali lalu dihapus agar tidak terulang saat refresh.
    function consumeNav() {
        var raw = null;

        try {
            raw = window.sessionStorage.getItem(STORAGE_KEY);
            window.sessionStorage.removeItem(STORAGE_KEY);
        } catch (err) {
            return null;
        }

        if (!raw) return null;

        try {
            var data = JSON.parse(raw);
            var age = Date.now() - data.ts;

            if (
                data &&
                typeof data.from === 'string' &&
                typeof data.to === 'string' &&
                age >= 0 &&
                age <= FLAG_TTL_MS
            ) {
                return { from: data.from, to: data.to, elapsed: age };
            }
        } catch (err) { /* abaikan */ }

        return null;
    }


    /* -----------------------------------------------------
       POSISI
    ----------------------------------------------------- */

    function offsetFor(link) {
        // offsetTop/offsetHeight tidak terpengaruh transform sidebar mobile.
        return 'translate3d(0, ' + link.offsetTop + 'px, 0)';
    }

    function place(link) {
        indicator.style.height = link.offsetHeight + 'px';
        indicator.style.transform = offsetFor(link);
    }

    function setVisible(isVisible) {
        indicator.classList.toggle('is-visible', isVisible);
    }

    function stopAnimation() {
        if (activeAnimation) {
            try { activeAnimation.cancel(); } catch (err) { /* abaikan */ }
            activeAnimation = null;
        }
    }

    // Tempatkan indikator tanpa transisi.
    function snapTo(link) {
        stopAnimation();
        indicator.classList.remove('is-animating');

        if (!link) {
            setVisible(false);
            return;
        }

        place(link);
        setVisible(true);
    }

    function clearPending() {
        window.clearTimeout(pendingTimer);
        pendingTimer = null;

        var stale = container.querySelectorAll('.is-pending, .is-deactivating');

        for (var i = 0; i < stale.length; i++) {
            stale[i].classList.remove('is-pending', 'is-deactivating');
        }
    }

    function resync() {
        if (!ready) return;

        // Jangan memotong pergeseran yang sedang berjalan.
        if (indicator.classList.contains('is-animating')) return;
        if (activeAnimation) return;

        snapTo(container.querySelector(ACTIVE_SELECTOR));
    }


    /* -----------------------------------------------------
       TAHAP 2: HALAMAN TUJUAN
    ----------------------------------------------------- */

    // Lanjutkan gerakan dari titik yang sama dengan halaman asal.
    function continueSlide(from, to, elapsed) {
        var fromY = from.offsetTop;
        var toY = to.offsetTop;

        // Posisi akhir sebagai dasar, juga bila Web Animations tak ada.
        place(to);
        setVisible(true);

        if (typeof indicator.animate !== 'function') return;

        activeAnimation = indicator.animate(
            [
                { transform: 'translate3d(0, ' + fromY + 'px, 0)' },
                { transform: 'translate3d(0, ' + toY + 'px, 0)' }
            ],
            {
                duration: SLIDE_MS,
                easing: SLIDE_EASING,
                fill: 'both'
            }
        );

        activeAnimation.currentTime = Math.min(elapsed, SLIDE_MS - 1);

        activeAnimation.onfinish = function () {
            place(to);
            stopAnimation();
        };
    }

    function init() {
        var active = container.querySelector(ACTIVE_SELECTOR);
        var nav = consumeNav();

        indicator = document.createElement('span');
        indicator.className = 'nav-indicator';
        indicator.setAttribute('aria-hidden', 'true');
        container.insertBefore(indicator, container.firstChild);

        sidebar.classList.add('has-nav-indicator');

        var from = nav ? findLinkByKey(nav.from) : null;

        var canContinue =
            active &&
            from &&
            nav.to === linkKey(active) &&
            from !== active &&
            nav.elapsed < SLIDE_MS &&
            !prefersReducedMotion() &&
            !isBackForwardNavigation();

        if (canContinue) {
            continueSlide(from, active, nav.elapsed);
        } else {
            // Gerakan sudah selesai di halaman asal, atau tidak relevan.
            snapTo(active);
        }

        ready = true;
    }


    /* -----------------------------------------------------
       TAHAP 1: HALAMAN ASAL (saat klik)
    ----------------------------------------------------- */

    function startPending(link, active) {
        clearPending();

        active.classList.add('is-deactivating');
        link.classList.add('is-pending');

        // Transisi CSS biasa: sumber gerak sama dengan tahap 2.
        indicator.classList.add('is-animating');
        place(link);

        pendingTimer = window.setTimeout(function () {
            // Navigasi tidak terjadi: kembalikan ke item aktif.
            clearNav();
            clearPending();
            indicator.classList.add('is-animating');
            place(active);
        }, PENDING_REVERT_MS);
    }

    // Catat item asal/tujuan dan mulai gerakan (navigasi tidak dicegat).
    container.addEventListener('click', function (event) {
        if (
            event.defaultPrevented ||
            event.button !== 0 ||
            event.metaKey || event.ctrlKey || event.shiftKey || event.altKey
        ) {
            return;
        }

        var link = event.target.closest && event.target.closest(LINK_SELECTOR);
        var active = container.querySelector(ACTIVE_SELECTOR);

        if (!link || !active || link === active) return;
        if (link.target && link.target !== '_self') return;

        saveNav(linkKey(active), linkKey(link));

        if (ready && !prefersReducedMotion()) {
            startPending(link, active);
        }
    });

    init();

    // Sinkronkan ulang bila tata letak berubah (breakpoint, font Inter selesai).
    if ('ResizeObserver' in window) {
        new ResizeObserver(resync).observe(container);
    } else {
        window.addEventListener('resize', resync);
    }

    if (document.fonts && document.fonts.ready) {
        document.fonts.ready.then(resync);
    }

    // Halaman dipulihkan dari bfcache: bersihkan keadaan menggantung.
    window.addEventListener('pageshow', function (event) {
        if (!event.persisted) return;

        clearNav();
        clearPending();
        snapTo(container.querySelector(ACTIVE_SELECTOR));
    });

})();
