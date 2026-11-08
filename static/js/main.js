
/* ==========================================================================
   ACTRACE | main.js
   Global JavaScript
   ========================================================================== */

(function () {
    'use strict';

    /* =====================================================
       COPYRIGHT YEAR
    ===================================================== */

    function initYear() {
        var year = String(new Date().getFullYear());

        document.querySelectorAll('[data-year]').forEach(function (el) {
            el.textContent = year;
        });
    }


    /* =====================================================
       PASSWORD VISIBILITY TOGGLE
    ===================================================== */

    function initPasswordToggle() {

        // Mendukung markup baru dan markup lama ACTRACE.
        var buttons = document.querySelectorAll(
            '.password-toggle, [data-toggle-password]'
        );

        buttons.forEach(function (button) {

            var targetId =
                button.getAttribute('data-target') ||
                button.getAttribute('aria-controls');

            var input = document.getElementById(targetId);

            if (!input) return;

            // Hindari pemasangan event listener berulang.
            if (button.dataset.passwordInitialized === 'true') return;

            button.dataset.passwordInitialized = 'true';

            button.addEventListener('click', function () {

                var isVisible = input.type === 'text';
                var showPassword = !isVisible;

                input.type = showPassword ? 'text' : 'password';

                // Animasi ikon mata.
                button.classList.toggle('is-visible', showPassword);

                // Aksesibilitas.
                button.setAttribute(
                    'aria-pressed',
                    String(showPassword)
                );

                button.setAttribute(
                    'aria-label',
                    showPassword ? 'Hide password' : 'Show password'
                );

                button.setAttribute(
                    'title',
                    showPassword ? 'Hide password' : 'Show password'
                );

            });

        });
    }


    /* =====================================================
       FORM LOADING
    ===================================================== */

    function setLoading(form, isLoading) {

        var button = form.querySelector('button[type="submit"]');

        if (!button) return;

        var label = button.querySelector('.btn__label');

        if (label && !label.dataset.defaultText) {
            label.dataset.defaultText = label.textContent;
        }

        form.dataset.submitting = String(isLoading);

        form.setAttribute('aria-busy', String(isLoading));

        button.classList.toggle('is-loading', isLoading);

        button.setAttribute('aria-disabled', String(isLoading));

        if (label) {
            label.textContent = isLoading
                ? (button.dataset.loadingLabel || label.dataset.defaultText)
                : label.dataset.defaultText;
        }
    }


    function initLoadingForms() {

        document.querySelectorAll('form[data-loading-form]').forEach(function (form) {

            form.addEventListener('submit', function (event) {

                if (form.dataset.submitting === 'true') {
                    event.preventDefault();
                    return;
                }

                setLoading(form, true);

            });

        });


        // Reset loading ketika halaman dipulihkan dari browser cache.
        window.addEventListener('pageshow', function (event) {

            if (!event.persisted) return;

            document.querySelectorAll('form[data-loading-form]').forEach(function (form) {
                setLoading(form, false);
            });

        });

    }


    /* =====================================================
       AUTOFOCUS
    ===================================================== */

    function initAutofocus() {

        // Hindari keyboard otomatis muncul pada perangkat sentuh.
        if (
            !window.matchMedia ||
            !window.matchMedia('(pointer: fine)').matches
        ) {
            return;
        }

        var fields = document.querySelectorAll('[data-autofocus]');

        for (var i = 0; i < fields.length; i++) {

            if (!fields[i].value) {
                fields[i].focus();
                return;
            }

        }

    }


    /* =====================================================
       INITIALIZATION
    ===================================================== */

    function init() {

        initYear();

        initPasswordToggle();

        initLoadingForms();

        initAutofocus();

    }


    if (document.readyState === 'loading') {

        document.addEventListener('DOMContentLoaded', init);

    } else {

        init();

    }

})();