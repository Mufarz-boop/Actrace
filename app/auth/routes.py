import bcrypt
from flask import (
    abort,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    current_app,
)

from app.auth import auth_bp
from app.db import get_db_connection
from app.services.account_service import (
    DuplicateAccountError,
    create_account,
    limiter,
    validate_new_account,
    verify_access_code,
)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("student.dashboard"))

    if request.method == "POST":
        identity = request.form.get("identity", "").strip()
        password = request.form.get("password", "")

        if not identity or not password:
            flash(
                "Username/email dan kata sandi wajib diisi.",
                "error"
            )
            return render_template("auth/login.html")

        conn = None
        cur = None

        try:
            conn = get_db_connection()
            cur = conn.cursor(dictionary=True)

            cur.execute(
                """
                SELECT
                    user_id,
                    student_code,
                    full_name,
                    password_hash
                FROM users
                WHERE username = %s OR email = %s
                LIMIT 1
                """,
                (identity, identity),
            )

            user = cur.fetchone()

        except RuntimeError:
            current_app.logger.exception(
                "Gagal mengakses database saat login."
            )
            flash(
                "Layanan sedang mengalami gangguan. "
                "Silakan coba kembali.",
                "error"
            )
            return render_template("auth/login.html")

        finally:
            if cur is not None:
                cur.close()

            if conn is not None:
                conn.close()

        valid = False

        if user:
            try:
                valid = bcrypt.checkpw(
                    password.encode("utf-8"),
                    user["password_hash"].encode("utf-8")
                )
            except (ValueError, AttributeError):
                valid = False

        if not valid:
            flash(
                "Identitas atau kata sandi tidak sesuai.",
                "error"
            )
            return render_template("auth/login.html")

        session.clear()
        session.permanent = True

        session["user_id"] = user["user_id"]
        session["student_code"] = user["student_code"]
        session["full_name"] = user["full_name"]

        return redirect(url_for("student.dashboard"))

    return render_template("auth/login.html")


# =========================================================
# PEMBUATAN AKUN (form tersembunyi, Alt + F1 + U)
# =========================================================
# Shortcut hanya membuka dialog di browser. Penjaga sebenarnya ada di sini:
# fitur harus diaktifkan lewat konfigurasi, kode akses operator harus benar,
# percobaan salah dibatasi per IP, dan CSRF aktif secara global.

_DUPLICATE_MESSAGES = {
    "student_code": "Kode siswa sudah digunakan.",
    "username": "Username sudah digunakan.",
    "email": "Email sudah digunakan.",
}


def _render_provision_error(errors, status, form=None):
    """Render ulang halaman login dengan dialog terbuka. Sandi tidak diisi ulang."""

    kept = {
        key: (form.get(key) or "")
        for key in ("student_code", "full_name", "username", "email")
    } if form is not None else {}

    return render_template(
        "auth/login.html",
        provision_open=True,
        provision_errors=errors,
        provision_form=kept,
    ), status


@auth_bp.post("/login/create-account")
def create_account_route():
    if not current_app.config.get("ACCOUNT_PROVISIONING_ENABLED"):
        abort(404)

    if session.get("user_id"):
        return redirect(url_for("student.dashboard"))

    client_key = request.remote_addr or "unknown"

    if limiter.is_blocked(client_key):
        current_app.logger.warning(
            "[ACTRACE][PROVISION] Diblokir sementara | ip=%s", client_key
        )
        return _render_provision_error(
            {"_form": "Terlalu banyak percobaan. Coba lagi beberapa menit lagi."},
            429,
            request.form,
        )

    if not verify_access_code(request.form.get("access_code", "")):
        limiter.register_failure(client_key)
        current_app.logger.warning(
            "[ACTRACE][PROVISION] Kode akses salah | ip=%s", client_key
        )
        return _render_provision_error(
            {"access_code": "Kode akses tidak valid."},
            403,
            request.form,
        )

    clean, errors = validate_new_account(request.form)

    if errors:
        return _render_provision_error(errors, 400, request.form)

    try:
        user_id = create_account(clean)

    except DuplicateAccountError as exc:
        message = _DUPLICATE_MESSAGES.get(
            exc.field, "Kode siswa, username, atau email sudah digunakan."
        )
        return _render_provision_error(
            {exc.field or "_form": message}, 409, request.form
        )

    except RuntimeError:
        current_app.logger.exception(
            "[ACTRACE][PROVISION] Database tidak tersedia."
        )
        return _render_provision_error(
            {"_form": "Layanan sedang mengalami gangguan. Silakan coba kembali."},
            503,
            request.form,
        )

    except Exception:
        current_app.logger.exception(
            "[ACTRACE][PROVISION] Gagal membuat akun."
        )
        return _render_provision_error(
            {"_form": "Terjadi kesalahan saat membuat akun."},
            500,
            request.form,
        )

    limiter.reset(client_key)

    current_app.logger.info(
        "[ACTRACE][PROVISION] Akun dibuat | user_id=%s | username=%s | ip=%s",
        user_id,
        clean["username"],
        client_key,
    )

    flash(
        f"Akun {clean['username']} berhasil dibuat. Silakan masuk.",
        "success",
    )

    return redirect(url_for("auth.login"))


@auth_bp.post("/logout")
def logout():
    session.clear()
    flash("Kamu berhasil keluar dari ACTRACE.", "success")
    return redirect(url_for("auth.login"))