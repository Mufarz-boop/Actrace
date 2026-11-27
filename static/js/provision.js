/* ==========================================================================
   ACTRACE | provision.js
   Membuka dialog "Buat akun baru" lewat shortcut Alt + F1 + U pada halaman
   login, dan memvalidasi form di sisi klien.

   CATATAN KEAMANAN: shortcut ini hanya saklar tampilan. Siapa pun dapat
   membaca file ini. Perlindungan yang sebenarnya (fitur aktif, kode akses,
   pembatasan percobaan, CSRF, validasi ulang) ada di server. Validasi di
   sini hanya untuk kenyamanan dan harus selalu cocok dengan aturan server
   (app/services/account_service.py).

   Hanya dimuat bila ACCOUNT_PROVISIONING_ENABLED aktif. Dimuat dengan defer
   setelah main.js, yang mengurus tombol tampil/sembunyi kata sandi dan
   status loading tombol submit.
   ========================================================================== */

(function () {
    'use strict';

    var dialog = document.querySelector('[data-provision-dialog]');

    // Browser tanpa <dialog> modal: fitur tidak aktif, login tetap normal.
    if (!dialog || typeof dialog.showModal !== 'function') return;

    var form = dialog.querySelector('[data-provision-form]');
    var card = dialog.querySelector('[data-prov-card]');

    if (!form || !card) return;

    var FIELDS = [
        'student_code', 'full_name', 'username', 'email',
        'password', 'confirm_password', 'access_code'
    ];

    var PASSWORD_MIN = 12;
    var PASSWORD_MAX_BYTES = 72;


    /* -----------------------------------------------------
       UTILITAS
    ----------------------------------------------------- */

    function field(name) {
        return form.elements[name];
    }

    function utf8Length(text) {
        if (typeof TextEncoder !== 'undefined') {
            return new TextEncoder().encode(text).length;
        }
        return unescape(encodeURIComponent(text)).length;
    }

    // Huruf Unicode butuh flag "u"; bila tidak didukung, pengecekan
    // format nama dilewati di klien dan diputuskan oleh server.
    var NAME_RE = null;

    try {
        NAME_RE = new RegExp(
            "^\\p{L}+(?:[ .,'\u2019-]+\\p{L}+)*\\.?$", 'u'
        );
    } catch (err) {
        NAME_RE = null;
    }

    var STUDENT_CODE_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{2,29}$/;
    var USERNAME_RE = /^[a-z0-9][a-z0-9._-]{2,49}$/;
    var EMAIL_RE = /^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$/;


    /* -----------------------------------------------------
       TAMPILAN ERROR
    ----------------------------------------------------- */

    function setError(name, message) {
        var input = field(name);
        var holder = document.getElementById('prov-' + name + '-error');

        if (!input || !holder) return;

        holder.textContent = message || '';
        holder.hidden = !message;

        if (message) {
            input.setAttribute('aria-invalid', 'true');
        } else {
            input.removeAttribute('aria-invalid');
        }
    }

    function clearErrors() {
        FIELDS.forEach(function (name) { setError(name, ''); });
    }

    function shake() {
        card.classList.remove('is-shaking');
        void card.offsetWidth; // mulai ulang animasi
        card.classList.add('is-shaking');
    }

    card.addEventListener('animationend', function (event) {
        if (event.animationName === 'prov-shake') {
            card.classList.remove('is-shaking');
        }
    });


    /* -----------------------------------------------------
       VALIDASI KLIEN (cermin aturan server)
    ----------------------------------------------------- */

    function validate() {
        var errors = {};

        var studentCode = field('student_code').value.trim();
        var fullName = field('full_name').value.split(/\s+/).join(' ').trim();
        var username = field('username').value.trim().toLowerCase();
        var email = field('email').value.trim();
        var password = field('password').value;
        var confirm = field('confirm_password').value;
        var code = field('access_code').value;

        if (!STUDENT_CODE_RE.test(studentCode)) {
            errors.student_code =
                'Kode siswa 3-30 karakter: huruf, angka, titik, garis bawah, atau strip.';
        }

        if (
            fullName.length < 2 || fullName.length > 100 ||
            (NAME_RE && !NAME_RE.test(fullName))
        ) {
            errors.full_name =
                'Nama lengkap 2-100 karakter, hanya huruf, spasi, titik, koma, apostrof, dan strip.';
        }

        if (!USERNAME_RE.test(username)) {
            errors.username =
                'Username 3-50 karakter: huruf kecil, angka, titik, garis bawah, atau strip. Tidak boleh memakai @.';
        }

        if (email.length > 100 || !EMAIL_RE.test(email)) {
            errors.email = 'Format email tidak valid (maksimal 100 karakter).';
        }

        if (password.length < PASSWORD_MIN) {
            errors.password = 'Kata sandi minimal ' + PASSWORD_MIN + ' karakter.';
        } else if (utf8Length(password) > PASSWORD_MAX_BYTES) {
            errors.password =
                'Kata sandi terlalu panjang. Maksimal ' + PASSWORD_MAX_BYTES + ' byte dalam UTF-8.';
        } else if (username && password.toLowerCase().indexOf(username) !== -1) {
            errors.password = 'Kata sandi tidak boleh memuat username.';
        }

        if (!errors.password && password !== confirm) {
            errors.confirm_password = 'Konfirmasi kata sandi tidak cocok.';
        }

        if (!code) {
            errors.access_code = 'Kode akses wajib diisi.';
        }

        return errors;
    }

    function applyErrors(errors) {
        var firstInvalid = null;

        FIELDS.forEach(function (name) {
            setError(name, errors[name] || '');

            if (errors[name] && !firstInvalid) firstInvalid = field(name);
        });

        return firstInvalid;
    }

    // Capture di level document: berjalan sebelum listener main.js pada form,
    // sehingga submit yang ditolak tidak membuat tombol terkunci "loading".
    document.addEventListener('submit', function (event) {
        var target = event.target;

        if (!target || !target.matches || !target.matches('[data-provision-form]')) {
            return;
        }

        var errors = validate();
        var firstInvalid = applyErrors(errors);

        if (!firstInvalid) return; // lolos: kirim native (POST + CSRF)

        event.preventDefault();
        event.stopImmediatePropagation();

        shake();
        firstInvalid.focus();
    }, true);


    /* -----------------------------------------------------
       SYARAT KATA SANDI (indikator langsung)
    ----------------------------------------------------- */

    var rules = form.querySelectorAll('[data-prov-rules] [data-rule]');

    function updateRules() {
        var password = field('password').value;
        var username = field('username').value.trim().toLowerCase();
        var started = password.length > 0;

        var state = {
            min: password.length >= PASSWORD_MIN,
            max: utf8Length(password) <= PASSWORD_MAX_BYTES,
            user: !(username && password.toLowerCase().indexOf(username) !== -1)
        };

        Array.prototype.forEach.call(rules, function (item) {
            var ok = state[item.getAttribute('data-rule')];

            item.classList.toggle('is-ok', started && ok);
            item.classList.toggle('is-bad', started && !ok && item.getAttribute('data-rule') !== 'min');
        });
    }

    form.addEventListener('input', function (event) {
        var name = event.target && event.target.name;

        if (!name) return;

        // Pesan error hilang begitu pengguna mengedit kolom terkait.
        setError(name, '');

        if (name === 'password' || name === 'username') updateRules();
    });


    /* -----------------------------------------------------
       BUKA / TUTUP DIALOG
    ----------------------------------------------------- */

    function openDialog() {
        if (dialog.open) return;

        try {
            dialog.showModal();
        } catch (err) {
            return; // mis. dialog sudah terbuka
        }

        var invalid = form.querySelector('[aria-invalid="true"]');
        var target = invalid || field('student_code');

        if (target) target.focus();

        updateRules();
    }

    function resetDialog() {
        form.reset();
        clearErrors();
        updateRules();

        // Sembunyikan kembali kolom kata sandi yang sempat ditampilkan,
        // lewat handler tombol milik main.js agar state ikon konsisten.
        Array.prototype.forEach.call(
            form.querySelectorAll('[data-toggle-password][aria-pressed="true"]'),
            function (button) { button.click(); }
        );

        // Isi sensitif tidak boleh bertahan di DOM setelah dialog ditutup.
        ['password', 'confirm_password', 'access_code'].forEach(function (name) {
            field(name).value = '';
        });
    }

    dialog.addEventListener('close', function () {
        resetDialog();

        var identity = document.getElementById('identity');

        if (identity) identity.focus();
    });

    Array.prototype.forEach.call(
        dialog.querySelectorAll('[data-prov-close]'),
        function (button) {
            button.addEventListener('click', function () { dialog.close(); });
        }
    );


    /* -----------------------------------------------------
       SHORTCUT: Alt + F1 + U
       Dibaca lewat event.code (posisi fisik tombol) agar tidak
       bergantung pada tata letak keyboard; di macOS Option+U adalah
       dead key sehingga event.key tidak dapat diandalkan.
       Urutan alami: tahan Alt, tekan F1, lalu tekan U.
    ----------------------------------------------------- */

    var pressed = Object.create(null);

    document.addEventListener('keydown', function (event) {
        pressed[event.code] = true;

        // Cegah bantuan browser (F1) selama Alt ditahan.
        if (event.altKey && event.code === 'F1') {
            event.preventDefault();
        }

        if (!(event.altKey && pressed.F1 && pressed.KeyU)) return;

        event.preventDefault();
        event.stopPropagation();

        if (!event.repeat) openDialog();
    }, true);

    document.addEventListener('keyup', function (event) {
        delete pressed[event.code];
    }, true);

    // Fokus pindah (Alt+Tab, jendela lain): keyup tidak akan tiba.
    window.addEventListener('blur', function () { pressed = Object.create(null); });

    document.addEventListener('visibilitychange', function () {
        pressed = Object.create(null);
    });


    /* -----------------------------------------------------
       INISIALISASI
    ----------------------------------------------------- */

    // Server menolak kiriman form: tampilkan dialog beserta pesan errornya.
    if (dialog.hasAttribute('data-open-on-load')) {
        openDialog();
        shake();
    }

})();