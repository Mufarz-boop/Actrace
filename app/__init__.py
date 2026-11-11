
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
from config import Config


# ==========================================
# CSRF PROTECTION
# ==========================================

csrf = CSRFProtect()


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

        return render_template(
            "errors/403.html"
        ), 403


    @app.errorhandler(404)
    def not_found(error):

        return render_template(
            "errors/404.html"
        ), 404


    @app.errorhandler(500)
    def server_error(error):

        # Record the actual exception in the server log.
        current_app.logger.error(
            "Internal Server Error: %s",
            error,
            exc_info=True
        )

        return render_template(
            "errors/500.html"
        ), 500


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