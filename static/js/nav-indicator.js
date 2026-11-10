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
     Agar tetap terasa sebagai satu elemen yang bergerak, posisi item asal
     disimpan di sessionStorage saat link sidebar diklik. Di halaman tujuan
     indikator ditempatkan di item asal, lalu bergeser ke item aktif.
   - Klik tidak dicegat dan tidak ditunda; navigasi tetap native.
   - Jika JavaScript mati, gaya aktif statis (.nav-link--active) tetap
     dipakai.
   ========================================================================== */

(function () {
    'use strict';

    var sidebar = document.getElementById('sidebar');
    var container = sidebar && sidebar.querySelector('.sidebar__top');

    if (!sidebar || !container) return;

    var LINK_SELECTOR = '.nav-link';
    var ACTIVE_SELECTOR = '.nav-link--active';
    var STORAGE_KEY = 'actrace:nav-from';

    // Penanda dianggap basi setelah jeda ini.
    var FLAG_TTL_MS = 10000;

    // Sejalan dengan --motion-nav-duration (300ms) di student.css.
    var SETTLE_MS = 340;

    var indicator = null;
    var ready = false;
    var settleTimer = null;


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

    function saveFrom(key) {
        try {
            window.sessionStorage.setItem(
                STORAGE_KEY,
                JSON.stringify({ key: key, ts: Date.now() })
            );
        } catch (err) { /* penyimpanan tidak tersedia: tanpa pergeseran */ }
    }

    // Dibaca sekali lalu dihapus agar tidak terulang saat refresh.
    function consumeFrom() {
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

            if (data && typeof data.key === 'string' && age >= 0 && age <= FLAG_TTL_MS) {
                return data.key;
            }
        } catch (err) { /* abaikan */ }

        return null;
    }


    /* -----------------------------------------------------
       POSISI
    ----------------------------------------------------- */

    function place(link) {
        // offsetTop/offsetHeight tidak terpengaruh transform sidebar mobile.
        indicator.style.height = link.offsetHeight + 'px';
        indicator.style.transform =
            'translate3d(0, ' + link.offsetTop + 'px, 0)';
    }

    function setVisible(isVisible) {
        indicator.classList.toggle('is-visible', isVisible);
    }

    // Tempatkan indikator tanpa transisi.
    function snapTo(link) {
        indicator.classList.remove('is-animating');

        if (!link) {
            setVisible(false);
            return;
        }

        place(link);
        setVisible(true);
    }

    function resync() {
        if (!ready) return;

        // Jangan memotong pergeseran yang sedang berjalan.
        if (indicator.classList.contains('is-animating')) return;

        var active = container.querySelector(ACTIVE_SELECTOR);

        // Ukuran/posisi berubah (resize, font): tanpa animasi.
        snapTo(active);
    }


    /* -----------------------------------------------------
       INISIALISASI
    ----------------------------------------------------- */

    function init() {
        var active = container.querySelector(ACTIVE_SELECTOR);
        var fromKey = consumeFrom();
        var from = fromKey ? findLinkByKey(fromKey) : null;

        indicator = document.createElement('span');
        indicator.className = 'nav-indicator';
        indicator.setAttribute('aria-hidden', 'true');
        container.insertBefore(indicator, container.firstChild);

        var canSlide =
            active &&
            from &&
            from !== active &&
            !prefersReducedMotion() &&
            !isBackForwardNavigation();

        if (canSlide) {
            // 1. Mulai dari item asal, tanpa transisi.
            snapTo(from);
            from.classList.add('is-leaving');
            active.classList.add('is-arriving');

            // Setel peran visual indikator sebelum transisi dinyalakan.
            sidebar.classList.add('has-nav-indicator');
            void indicator.offsetWidth; // paksa reflow

            // 2. Geser ke item aktif.
            indicator.classList.add('is-animating');
            place(active);

            from.classList.remove('is-leaving');
            active.classList.remove('is-arriving');

            settleTimer = window.setTimeout(function () {
                indicator.classList.remove('is-animating');
            }, SETTLE_MS);
        } else {
            snapTo(active);
            sidebar.classList.add('has-nav-indicator');
        }

        ready = true;
    }

    // Catat item asal saat link sidebar diklik (navigasi tidak dicegat).
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

        saveFrom(linkKey(active));
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

    // Halaman dipulihkan dari bfcache: pastikan posisi dan penanda bersih.
    window.addEventListener('pageshow', function (event) {
        if (event.persisted) resync();
    });

})();
