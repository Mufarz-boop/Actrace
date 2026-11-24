/* ==========================================================================
   ACTRACE | reports-motion.js
   Animasi dan interaksi halaman Activity Reports (lapisan frontend saja).

   Cakupan (hanya yang ada di halaman ini):
   - entrance      : header -> filter -> ringkasan -> metrik -> ekspor -> daftar
   - scroll-reveal : IntersectionObserver, setiap elemen hanya sekali
   - counters      : hitung naik dari nilai backend (bukan nilai karangan)
   - interactions  : validasi tanggal, indikator perubahan filter, status
                     loading nyata (submit filter dan ekspor PDF)

   Pembagian tugas dengan CSS:
   - Keadaan awal (tersembunyi) dipasang oleh skrip kecil di <head>
     reports.html lewat html.rp-pre. Skrip itu tidak memasangnya bila
     prefers-reduced-motion aktif atau halaman dibuka lewat Back/Forward.
   - Berkas ini hanya menambah kelas .rp-in (KAPAN muncul) dan
     --rp-delay (URUTAN). Seluruh gerak ada di student.css, bagian
     "ACTIVITY REPORTS - MOTION SYSTEM".

   Tanpa JavaScript, seluruh konten tampil biasa (html.rp-pre tidak pernah
   terpasang, atau dilepas oleh jaring pengaman di <head>).
   ========================================================================== */

(function () {
    'use strict';

    var page = document.querySelector('.report-page');
    if (!page || page.getAttribute('data-rp-init')) return; // cegah init ganda
    page.setAttribute('data-rp-init', '1');
    window.__rpReady = true;

    var root = document.documentElement;
    var motionOn = root.classList.contains('rp-pre');
    var cleanups = [];
    var timers = [];

    function byId(id) { return document.getElementById(id); }

    function on(target, type, handler, options) {
        if (!target) return;
        target.addEventListener(type, handler, options);
        cleanups.push(function () {
            target.removeEventListener(type, handler, options);
        });
    }

    function later(fn, ms) {
        var id = window.setTimeout(fn, ms);
        timers.push(id);
        return id;
    }

    function announce(message) {
        var status = byId('rp-status');
        if (status) status.textContent = message;
    }


    /* ======================================================================
       1. COUNTERS  (reports-counters)
       Nilai akhir selalu berasal dari data-rp-count (diisi Jinja dari
       backend). Satu loop rAF melayani semua counter aktif.
       ====================================================================== */

    function toNumber(value) {
        var n = parseFloat(value);
        return isFinite(n) ? n : 0;
    }

    // Format: int (default), decimal, percent, currency, compact.
    function makeFormatter(el) {
        var type = el.getAttribute('data-rp-format') || 'int';
        var decimals = parseInt(el.getAttribute('data-rp-decimals') || '0', 10) || 0;
        var options;

        switch (type) {
            case 'decimal':
            case 'percent':
                options = {
                    minimumFractionDigits: decimals,
                    maximumFractionDigits: decimals
                };
                break;
            case 'currency':
                options = {
                    style: 'currency',
                    currency: el.getAttribute('data-rp-currency') || 'IDR',
                    maximumFractionDigits: decimals
                };
                break;
            case 'compact':
                options = { notation: 'compact', maximumFractionDigits: 1 };
                break;
            default:
                options = { maximumFractionDigits: 0 };
        }

        var formatter = null;
        try {
            formatter = new Intl.NumberFormat('id-ID', options);
        } catch (err) { /* pakai pembulatan sederhana di bawah */ }

        return function (value) {
            var text = formatter ? formatter.format(value) : String(Math.round(value));
            return type === 'percent' ? text + '%' : text;
        };
    }

    var STORE_KEY = 'actrace:reports:prev';
    var STORE_TTL_MS = 2 * 60 * 1000;

    // Nilai sebelum filter diterapkan, agar angka bergerak dari nilai lama
    // ke nilai baru (bukan selalu dari 0). Hanya dipakai sekali.
    function readPrevious() {
        try {
            var raw = window.sessionStorage.getItem(STORE_KEY);
            window.sessionStorage.removeItem(STORE_KEY);
            if (!raw) return null;

            var data = JSON.parse(raw);
            if (!data || Date.now() - data.at > STORE_TTL_MS) return null;
            return data.values || null;
        } catch (err) {
            return null;
        }
    }

    function savePrevious() {
        try {
            var values = {};
            var els = page.querySelectorAll('[data-rp-count][data-rp-key]');
            Array.prototype.forEach.call(els, function (el) {
                values[el.getAttribute('data-rp-key')] =
                    toNumber(el.getAttribute('data-rp-count'));
            });

            if (!Object.keys(values).length) return;

            window.sessionStorage.setItem(STORE_KEY, JSON.stringify({
                at: Date.now(),
                values: values
            }));
        } catch (err) { /* storage tidak tersedia: lanjut tanpa transisi */ }
    }

    var counters = [];
    var counterRaf = 0;

    function setupCounters() {
        var previous = readPrevious();
        var els = page.querySelectorAll('[data-rp-count]');

        Array.prototype.forEach.call(els, function (el) {
            var to = toNumber(el.getAttribute('data-rp-count'));
            var key = el.getAttribute('data-rp-key');
            var from = 0;

            if (previous && key && typeof previous[key] === 'number') {
                from = previous[key];
            }

            if (from === to) return; // tidak ada perubahan: tetap statis

            var format = makeFormatter(el);

            // Lebar tetap + angka tabular agar tidak ada pergeseran tata letak.
            el.style.display = 'inline-block';
            el.style.minWidth = String(format(to)).length + 'ch';
            el.style.textAlign = 'right';
            el.textContent = format(from);

            counters.push({
                el: el,
                host: el.closest('[data-rp]'),
                from: from,
                to: to,
                format: format,
                duration: previous ? 760 : 980,
                start: 0,
                started: false,
                done: false
            });
        });
    }

    function counterTick(now) {
        var active = false;

        counters.forEach(function (c) {
            if (c.done || !c.started) return;

            if (now < c.start) {
                active = true;
                return;
            }

            var t = Math.min(1, (now - c.start) / c.duration);
            var eased = 1 - Math.pow(1 - t, 4); // easeOutQuart

            c.el.textContent = c.format(
                t < 1 ? c.from + (c.to - c.from) * eased : c.to
            );

            if (t >= 1) {
                c.done = true;
            } else {
                active = true;
            }
        });

        counterRaf = active ? window.requestAnimationFrame(counterTick) : 0;
    }

    function startCountersFor(host, delay) {
        var any = false;

        counters.forEach(function (c) {
            if (c.host === host && !c.started) {
                c.started = true;
                c.start = window.performance.now() + delay;
                any = true;
            }
        });

        if (any && !counterRaf) {
            counterRaf = window.requestAnimationFrame(counterTick);
        }
    }

    function finishAllCounters() {
        counters.forEach(function (c) {
            c.started = true;
            c.done = true;
            c.el.textContent = c.format(c.to);
        });

        if (counterRaf) {
            window.cancelAnimationFrame(counterRaf);
            counterRaf = 0;
        }
    }


    /* ======================================================================
       2. ENTRANCE + SCROLL REVEAL  (reports-entrance, reports-scroll-reveal,
          reports-responsive-motion)
       Satu IntersectionObserver untuk semua elemen [data-rp]. Elemen yang
       sudah terlihat saat dibuka membentuk urutan masuk; sisanya muncul saat
       digulir. Setiap elemen dilepas dari observer setelah tampil sehingga
       tidak ada animasi berulang.
       ====================================================================== */

    var observer = null;
    var pending = 0;
    var gotCallback = false;
    var firstBatch = true;

    function staggerStep() {
        var w = window.innerWidth;
        if (w <= 640) return 70;   // mobile
        if (w <= 1024) return 85;  // tablet
        return 100;                // desktop
    }

    var ROW_STEP = 45;    // baris daftar: rapat, tidak menahan konten
    var ROW_STEPS_MAX = 6;
    var DELAY_MAX = 1200;

    function revealBatch(batch) {
        batch.sort(function (a, b) {
            return (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING)
                ? -1
                : 1;
        });

        var step = staggerStep();
        var t = firstBatch ? 80 : 0; // atmosfer tampil lebih dulu
        var rows = 0;
        var plan = [];

        batch.forEach(function (el) {
            var isRow = el.getAttribute('data-rp') === 'row';
            var delay = Math.min(t, DELAY_MAX);

            plan.push({ el: el, delay: delay });

            if (isRow) {
                rows += 1;
                if (rows <= ROW_STEPS_MAX) t += ROW_STEP;
            } else {
                t += step;
            }
        });

        firstBatch = false;

        window.requestAnimationFrame(function () {
            plan.forEach(function (item) {
                item.el.style.setProperty('--rp-delay', item.delay + 'ms');
                item.el.classList.add('rp-in');
                startCountersFor(item.el, item.delay + 160);
            });
        });
    }

    function onIntersect(entries) {
        var batch = [];

        entries.forEach(function (entry) {
            if (!entry.isIntersecting) return;

            observer.unobserve(entry.target);
            pending -= 1;
            batch.push(entry.target);
        });

        if (!batch.length) return;

        gotCallback = true;
        revealBatch(batch);

        if (pending <= 0) {
            observer.disconnect();
            observer = null;
        }
    }

    function revealAll() {
        if (observer) {
            observer.disconnect();
            observer = null;
        }

        pending = 0;

        Array.prototype.forEach.call(page.querySelectorAll('[data-rp]'), function (el) {
            el.classList.add('rp-in');
            el.style.setProperty('--rp-delay', '0ms');
        });

        finishAllCounters();
        root.classList.add('rp-play');
        root.classList.remove('rp-pre');
    }

    function setupMotion() {
        var targets = page.querySelectorAll('[data-rp]');

        if (!('IntersectionObserver' in window) || !targets.length) {
            revealAll();
            return;
        }

        setupCounters();

        observer = new window.IntersectionObserver(onIntersect, {
            root: null,
            rootMargin: '0px 0px -6% 0px',
            threshold: 0
        });

        pending = targets.length;
        Array.prototype.forEach.call(targets, function (el) {
            observer.observe(el);
        });

        // Atmosfer latar: dua frame agar keadaan awal sempat digambar.
        window.requestAnimationFrame(function () {
            window.requestAnimationFrame(function () {
                root.classList.add('rp-play');
            });
        });

        // Jaring pengaman: konten tidak boleh tetap tersembunyi.
        later(function () {
            if (!gotCallback && document.visibilityState === 'visible') {
                revealAll();
            }
        }, 2500);
    }


    /* ======================================================================
       3. INTERACTIONS  (reports-interactions)
       Perilaku lama (validasi tanggal, status loading ekspor) dipindahkan
       ke sini tanpa mengubah maknanya, lalu ditambah umpan balik visual.
       ====================================================================== */

    var form = byId('report-filter-form');
    var start = byId('start_date');
    var end = byId('end_date');
    var errorBox = byId('report-client-error');
    var submitButton = form ? form.querySelector('button[type="submit"]') : null;
    var exportButton = byId('report-export-button');

    // ---- Indikator "periode berubah, belum diterapkan" ------------------

    function syncDirty() {
        if (!submitButton || !start || !end) return;

        var dirty =
            start.value !== start.defaultValue ||
            end.value !== end.defaultValue;

        if (dirty) {
            submitButton.setAttribute('data-dirty', 'true');
            submitButton.setAttribute(
                'title',
                'Periode berubah. Tekan untuk menampilkan rekap.'
            );
        } else {
            submitButton.removeAttribute('data-dirty');
            submitButton.removeAttribute('title');
        }
    }

    function pulseField(input) {
        var field = input && input.closest('.report-date-field');
        if (!field) return;

        field.classList.remove('is-changed');
        void field.offsetWidth; // mulai ulang animasi bila berulang
        field.classList.add('is-changed');
    }

    function clearPulse(event) {
        var field = event.target.closest && event.target.closest('.report-date-field');
        if (field) field.classList.remove('is-changed');
    }

    // ---- Validasi tanggal (perilaku asli dipertahankan) -----------------

    function showError(message) {
        if (!errorBox) return;

        errorBox.hidden = true;
        void errorBox.offsetWidth; // animasi masuk diputar ulang
        errorBox.textContent = message;
        errorBox.hidden = false;
    }

    function hideError() {
        if (errorBox) errorBox.hidden = true;
    }

    if (start && end) {
        end.min = start.value || '';

        on(start, 'change', function () {
            end.min = start.value || '';

            if (end.value && start.value && end.value < start.value) {
                end.value = start.value;
                pulseField(end);
            }

            pulseField(start);
            syncDirty();
        });

        on(end, 'change', function () {
            pulseField(end);
            syncDirty();
        });

        on(form, 'animationend', clearPulse);
    }

    // ---- Submit filter: navigasi sungguhan, bukan loading palsu --------

    function setSubmitLoading(loading) {
        if (!submitButton) return;

        submitButton.classList.toggle('is-loading', loading);

        if (loading) {
            submitButton.setAttribute('aria-busy', 'true');
        } else {
            submitButton.removeAttribute('aria-busy');
        }
    }

    on(form, 'submit', function (event) {
        hideError();

        if (start.value && end.value && start.value > end.value) {
            event.preventDefault();
            showError('Tanggal awal tidak boleh melewati tanggal akhir.');
            return;
        }

        savePrevious();
        setSubmitLoading(true);
    });

    // ---- Ekspor PDF: request asli dengan status loading yang kembali ----
    // Tautan tetap berfungsi tanpa JS. Dengan JS, PDF diambil lewat fetch
    // agar tombol tahu kapan selesai (sebelumnya tombol macet di
    // "Menyiapkan PDF..."). Bila respons bukan PDF (mis. redirect dengan
    // pesan flash atau sesi habis), halaman dinavigasi seperti biasa.

    var exportLabel = exportButton ? exportButton.querySelector('span') : null;
    var exportIcon = exportButton ? exportButton.querySelector('i') : null;
    var exportIdleLabel = exportLabel ? exportLabel.textContent : '';
    var exportIdleIcon = exportIcon ? exportIcon.className : '';
    var exportBusy = false;

    function setExportState(state) {
        if (!exportButton) return;

        exportButton.classList.toggle('is-loading', state === 'loading');
        exportButton.classList.toggle('is-done', state === 'done');

        if (state === 'loading') {
            exportButton.setAttribute('aria-busy', 'true');
            exportButton.setAttribute('aria-disabled', 'true');
            if (exportLabel) exportLabel.textContent = 'Menyiapkan PDF...';
            announce('Menyiapkan PDF.');
        } else {
            exportButton.removeAttribute('aria-busy');
            exportButton.removeAttribute('aria-disabled');

            if (state === 'done') {
                if (exportLabel) exportLabel.textContent = 'PDF siap diunduh';
                if (exportIcon) exportIcon.className = 'fas fa-check';
                announce('PDF siap diunduh.');
            } else {
                if (exportLabel) exportLabel.textContent = exportIdleLabel;
                if (exportIcon) exportIcon.className = exportIdleIcon;
            }
        }
    }

    function filenameFrom(response, fallback) {
        var header = response.headers.get('Content-Disposition') || '';
        var match = /filename\*=UTF-8''([^;]+)/i.exec(header);

        if (match) {
            try { return decodeURIComponent(match[1]); } catch (err) { /* lanjut */ }
        }

        match = /filename="?([^";]+)"?/i.exec(header);
        return match ? match[1] : fallback;
    }

    function saveBlob(blob, filename) {
        var url = window.URL.createObjectURL(blob);
        var link = document.createElement('a');

        link.href = url;
        link.download = filename;
        link.rel = 'noopener';
        document.body.appendChild(link);
        link.click();
        link.remove();

        later(function () { window.URL.revokeObjectURL(url); }, 4000);
    }

    function fallbackNavigate(href) {
        window.location.assign(href);
    }

    if (exportButton) {
        on(exportButton, 'click', function (event) {
            if (
                event.defaultPrevented || event.button !== 0 ||
                event.metaKey || event.ctrlKey || event.shiftKey || event.altKey
            ) {
                return;
            }

            var href = exportButton.getAttribute('href');

            // Peramban lama: unduhan biasa, status dipulihkan setelah jeda.
            if (!window.fetch || !window.URL || !window.Blob) {
                setExportState('loading');
                later(function () { setExportState('idle'); }, 6000);
                return;
            }

            event.preventDefault();
            if (exportBusy) return;

            exportBusy = true;
            setExportState('loading');

            window.fetch(href, { credentials: 'same-origin' })
                .then(function (response) {
                    var type = response.headers.get('Content-Type') || '';

                    if (!response.ok || type.indexOf('application/pdf') === -1) {
                        throw new Error('not-a-pdf');
                    }

                    return response.blob().then(function (blob) {
                        saveBlob(blob, filenameFrom(response, 'ACTRACE_Rekap_Jurnal.pdf'));
                    });
                })
                .then(function () {
                    exportBusy = false;
                    setExportState('done');
                    later(function () { setExportState('idle'); }, 2200);
                })
                .catch(function () {
                    exportBusy = false;
                    setExportState('idle');
                    fallbackNavigate(href);
                });
        });
    }


    /* ======================================================================
       4. LIFECYCLE
       ====================================================================== */

    // Dibuka lagi dari bfcache (Back): pulihkan status, tampilkan semuanya.
    window.addEventListener('pageshow', function (event) {
        if (!event.persisted) return;

        setSubmitLoading(false);
        exportBusy = false;
        setExportState('idle');
        revealAll();
    });

    window.addEventListener('pagehide', function (event) {
        if (event.persisted) return; // bfcache: pertahankan pendengar

        if (observer) observer.disconnect();
        if (counterRaf) window.cancelAnimationFrame(counterRaf);
        timers.forEach(function (id) { window.clearTimeout(id); });
        cleanups.forEach(function (fn) { fn(); });
        cleanups = [];
    });

    syncDirty();

    if (motionOn) {
        setupMotion();
    }

})();
