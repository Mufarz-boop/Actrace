
import logging

from flask import (
    Flask,
    redirect,
    url_for,
    session,
    render_template,
    abort,
    current_app,
)

from flask_wtf.csrf import CSRFProtect

from app import constants
from config import Config


# ==========================================
# CSRF PROTECTION
# ==========================================

csrf = CSRFProtect()


# ==========================================
# ERROR PAGES
# ==========================================
# Isi tiap halaman error. Semuanya dirender oleh templates/error.html.
# Hanya teks statis di sini; detail exception tidak pernah dikirim ke
# template. "action" menentukan tombol sekunder: "back" (halaman
# sebelumnya) atau "reload" (coba lagi).

ERROR_PAGES = {
    403: {
        "label": "ACCESS FORBIDDEN",
        "title": "Akses Ditolak",
        "message": (
            "Maaf, kamu tidak memiliki izin untuk mengakses "
            "halaman atau sumber daya ini."
        ),
        "icon": "!",
        "action": "back",
    },
    404: {
        "label": "PAGE NOT FOUND",
        "title": "Halaman Tidak Ditemukan",
        "message": (
            "Halaman yang kamu cari mungkin telah dipindahkan, "
            "dihapus, atau alamat yang dimasukkan tidak benar."
        ),
        "icon": "?",
        "action": "back",
    },
    500: {
        "label": "INTERNAL SERVER ERROR",
        "title": "Terjadi Kesalahan Server",
        "message": (
            "Sistem sedang mengalami gangguan internal. "
            "Silakan coba kembali beberapa saat lagi."
        ),
        "icon": "!",
        "action": "reload",
    },
}


def render_error_page(status_code):

    page = ERROR_PAGES[status_code]

    return render_template(
        "error.html",
        error_code=status_code,
        error_label=page["label"],
        error_title=page["title"],
        error_message=page["message"],
        error_icon=page["icon"],
        error_action=page["action"],
    ), status_code


# ==========================================
# APPLICATION FACTORY
# ==========================================

def create_app():

    app = Flask(
        __name__,
        template_folder="../templates",
        static_folder="../static"
    )

    # Load application configuration
    app.config.from_object(Config)

    # Validate environment configuration
    Config.validate()

    # Initialize CSRF protection
    csrf.init_app(app)


    # ======================================
    # REGISTER BLUEPRINTS
    # ======================================

    from app.auth import auth_bp
    from app.student import student_bp
    from app.api import api_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(student_bp)
    app.register_blueprint(api_bp)

    # API authentication uses its own API key.
    # Exempt API routes from browser CSRF protection.
    csrf.exempt(api_bp)


    # ======================================
    # APPLICATION LOGGER
    # ======================================

    app.logger.setLevel(logging.INFO)


    # ======================================
    # SECURITY HEADERS
    # ======================================

    @app.after_request
    def add_security_headers(response):

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=()"
        )

        return response


    # ======================================
    # TEMPLATE CONTEXT: APPLICATION LIMITS
    # ======================================
    # Nilai batas berasal dari app/constants.py. Template memakainya untuk
    # teks/atribut HTML dan meneruskannya ke JavaScript lewat atribut data-*.

    @app.context_processor
    def inject_app_limits():

        return {
            "app_limits": {
                "max_photos_per_journal": constants.MAX_PHOTOS_PER_JOURNAL,
                "max_photo_size_mb": constants.MAX_PHOTO_SIZE_MB,
                "max_journal_title_length": constants.MAX_JOURNAL_TITLE_LENGTH,
                "min_password_length": constants.MIN_PASSWORD_LENGTH,
                "bcrypt_max_password_bytes": constants.BCRYPT_MAX_PASSWORD_BYTES,
            }
        }


    # ======================================
    # MAIN ROUTE
    # ======================================

    @app.get("/")
    def index():

        if session.get("user_id"):
            return redirect(url_for("student.dashboard"))

        return redirect(url_for("auth.login"))


    # ======================================
    # ERROR HANDLERS
    # ======================================

    @app.errorhandler(403)
    def forbidden(error):

        return render_error_page(403)


    @app.errorhandler(404)
    def not_found(error):

        return render_error_page(404)


    @app.errorhandler(500)
    def server_error(error):

        # Record the actual exception in the server log.
        current_app.logger.error(
            "Internal Server Error: %s",
            error,
            exc_info=True
        )

        return render_error_page(500)


    # ======================================
    # DEVELOPMENT-ONLY ERROR PREVIEW ROUTES
    # ======================================
    # Hanya didaftarkan saat DEBUG aktif agar halaman error dapat
    # dipratinjau saat pengembangan. Pada konfigurasi produksi
    # (DEBUG=False) route ini tidak ada sama sekali (404).

    if app.config.get("DEBUG"):

        @app.get("/test-error/403")
        def test_error_403():

            abort(403)


        @app.get("/test-error/404")
        def test_error_404():

            abort(404)


        @app.get("/test-error/500")
        def test_error_500():

            raise RuntimeError(
                "ACTRACE testing: Internal Server Error"
            )


    # ======================================
    # RETURN APPLICATION
    # ======================================

    return app