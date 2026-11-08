import bcrypt
import io
import uuid
from datetime import date
from datetime import date
from pathlib import Path

from flask import (
    render_template,
    session,
    request,
    redirect,
    url_for,
    flash,
    current_app,
    abort,
    send_file,
)

from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.utils import secure_filename
from mysql.connector import IntegrityError

from app.student import student_bp
from app.utils.decorators import student_required
from app.db import get_db_connection

from app.services.journal_service import (
    create_journal,
    get_journal_detail,
    update_journal,
    JournalValidationError,
    JournalSaveError,
    get_journals_for_report,
    get_gallery_photos,
)

from app.services.photo_service import PhotoValidationError
from app.services.pdf_service import build_journal_report_pdf


def _parse_report_period(start_value, end_value):
    """Validasi rentang tanggal rekap jurnal."""
    try:
        start_date = date.fromisoformat(start_value or "")
        end_date = date.fromisoformat(end_value or "")
    except (TypeError, ValueError):
        raise ValueError("Tanggal awal dan akhir wajib diisi dengan format yang valid.")

    if start_date > end_date:
        raise ValueError("Tanggal awal tidak boleh melewati tanggal akhir.")

    if end_date > date.today():
        raise ValueError("Tanggal akhir tidak boleh melebihi hari ini.")

    return start_date, end_date


def _get_report_student(user_id):
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT full_name, student_code
            FROM users
            WHERE user_id = %s
            LIMIT 1
            """,
            (user_id,),
        )
        return cursor.fetchone() or {}
    finally:
        cursor.close()
        connection.close()


# =====================================================
# JOURNAL REPORTS
# =====================================================

@student_bp.get("/reports")
@student_required
def reports():
    today = date.today()
    default_start = today.replace(day=1)
    start_value = request.args.get("start_date", default_start.isoformat())
    end_value = request.args.get("end_date", today.isoformat())

    journals = []
    start_date = default_start
    end_date = today
    error = None

    try:
        start_date, end_date = _parse_report_period(start_value, end_value)
        journals = get_journals_for_report(
            user_id=session["user_id"],
            start_date=start_date,
            end_date=end_date,
        )
    except ValueError as exc:
        error = str(exc)
    except JournalSaveError:
        current_app.logger.exception(
            "[ACTRACE][REPORT] Gagal memuat rekap | user_id=%s",
            session.get("user_id"),
        )
        error = "Rekap jurnal gagal dimuat. Silakan coba kembali."

    return render_template(
        "student/reports.html",
        start_date=start_value,
        end_date=end_value,
        journals=journals,
        total_journals=len(journals),
        total_photos=sum(int(journal.get("photo_count") or 0) for journal in journals),
        total_activity_days=len({str(journal.get("activity_date"))[:10] for journal in journals if journal.get("activity_date") is not None}),
        error=error,
        today=today.isoformat(),
    )


@student_bp.get("/reports/pdf")
@student_required
def download_journal_report():
    try:
        start_date, end_date = _parse_report_period(
            request.args.get("start_date"),
            request.args.get("end_date"),
        )
        student_id = session["user_id"]
        journals = get_journals_for_report(
            user_id=student_id,
            start_date=start_date,
            end_date=end_date,
        )
        if not journals:
            flash("Tidak ada jurnal pada periode tersebut. PDF tidak dibuat.", "info")
            return redirect(url_for(
                "student.reports",
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
            ))

        student = _get_report_student(student_id)
        pdf_file = build_journal_report_pdf(
            student=student,
            journals=journals,
            start_date=start_date,
            end_date=end_date,
            photo_root=current_app.config["UPLOAD_FOLDER"],
        )
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("student.reports"))
    except JournalSaveError:
        current_app.logger.exception(
            "[ACTRACE][REPORT] Gagal membuat PDF | user_id=%s",
            session.get("user_id"),
        )
        flash("PDF rekap jurnal gagal dibuat. Silakan coba kembali.", "error")
        return redirect(url_for("student.reports"))
    except Exception:
        current_app.logger.exception(
            "[ACTRACE][REPORT] Kesalahan saat membuat PDF | user_id=%s",
            session.get("user_id"),
        )
        flash("Terjadi kesalahan saat membuat PDF rekap jurnal.", "error")
        return redirect(url_for("student.reports"))

    filename = (
        f"ACTRACE_Rekap_Jurnal_{start_date.isoformat()}_"
        f"{end_date.isoformat()}.pdf"
    )
    return send_file(
        pdf_file,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename,
    )

# =====================================================
# PROFILE PHOTO STORAGE
# =====================================================

def _save_profile_photo(upload):
    """
    Memvalidasi dan menyimpan foto profil sebagai WebP.
    Foto disimpan terpisah dari dokumentasi jurnal.
    """

    if not upload or not upload.filename:
        return None, None

    stream = upload.stream

    try:
        stream.seek(0, 2)
        file_size = stream.tell()
        stream.seek(0)

        if file_size <= 0:
            raise ValueError("File foto kosong.")

        if file_size > 2 * 1024 * 1024:
            raise ValueError(
                "Ukuran foto profil maksimal 2 MB."
            )

        image = Image.open(stream)

        if image.format not in {"JPEG", "PNG", "WEBP"}:
            raise ValueError(
                "Format foto harus JPEG, PNG, atau WebP."
            )

        if image.width * image.height > 20_000_000:
            raise ValueError(
                "Resolusi foto terlalu besar."
            )

        image.verify()

        stream.seek(0)

        image = Image.open(stream)

        if getattr(image, "is_animated", False):
            raise ValueError(
                "Foto profil harus berupa gambar statis."
            )

        image = ImageOps.exif_transpose(image)
        image.thumbnail((512, 512))

        if image.mode not in {"RGB", "RGBA"}:
            image = image.convert("RGB")

        upload_folder = (
            Path(current_app.instance_path)
            / "uploads"
            / "profile_photos"
        )

        upload_folder.mkdir(
            parents=True,
            exist_ok=True,
        )

        filename = f"{uuid.uuid4().hex}.webp"
        destination = upload_folder / filename

        image.save(
            destination,
            format="WEBP",
            quality=85,
            method=6,
        )

        return filename, destination

    except ValueError:
        raise

    except (
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
    ) as exc:
        raise ValueError(
            "File yang diunggah bukan gambar yang valid."
        ) from exc


# =====================================================
# STUDENT PROFILE
# =====================================================

@student_bp.route("/profile", methods=["GET", "POST"])
@student_required
def profile():

    user_id = session["user_id"]

    # =================================================
    # UPDATE PROFILE
    # =================================================

    if request.method == "POST":

        full_name = request.form.get("full_name", "").strip()
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()

        photo_upload = request.files.get("photo")
        remove_photo = request.form.get("remove_photo") == "1"

        # ---------------------------------------------
        # ACADEMIC INFORMATION
        # ---------------------------------------------

        school_name = request.form.get("school_name", "").strip()
        class_name = request.form.get("class_name", "").strip()
        major = request.form.get("major", "").strip()
        academic_year = request.form.get("academic_year", "").strip()

        # ---------------------------------------------
        # INTERNSHIP INFORMATION
        # ---------------------------------------------

        internship_company = request.form.get(
            "internship_company", ""
        ).strip()

        internship_industry = request.form.get(
            "internship_industry", ""
        ).strip()

        internship_address = request.form.get(
            "internship_address", ""
        ).strip()

        supervisor_name = request.form.get(
            "supervisor_name", ""
        ).strip()

        supervisor_position = request.form.get(
            "supervisor_position", ""
        ).strip()

        start_value = request.form.get(
            "internship_start_date", ""
        ).strip()

        end_value = request.form.get(
            "internship_end_date", ""
        ).strip()

        # ---------------------------------------------
        # VALIDATE ACCOUNT INFORMATION
        # ---------------------------------------------

        if not full_name or len(full_name) > 100:
            flash(
                "Nama lengkap wajib diisi dan maksimal 100 karakter.",
                "error",
            )
            return redirect(url_for("student.profile"))

        if not 3 <= len(username) <= 50:
            flash(
                "Username harus terdiri dari 3–50 karakter.",
                "error",
            )
            return redirect(url_for("student.profile"))

        if not username.replace("_", "").replace("-", "").replace(".", "").isalnum():
            flash(
                "Username hanya boleh berisi huruf, angka, titik, "
                "garis bawah, dan tanda hubung.",
                "error",
            )
            return redirect(url_for("student.profile"))

        if (
            not email
            or len(email) > 100
            or "@" not in email
            or email.startswith("@")
            or email.endswith("@")
            or any(char.isspace() for char in email)
        ):
            flash(
                "Alamat email tidak valid.",
                "error",
            )
            return redirect(url_for("student.profile"))

        # ---------------------------------------------
        # VALIDATE ACADEMIC AND INTERNSHIP FIELDS
        # ---------------------------------------------

        profile_fields = {
            "Nama sekolah": (school_name, 150),
            "Kelas": (class_name, 50),
            "Jurusan": (major, 100),
            "Tahun akademik": (academic_year, 20),
            "Nama perusahaan": (internship_company, 150),
            "Bidang industri": (internship_industry, 100),
            "Alamat perusahaan": (internship_address, 255),
            "Nama pembimbing": (supervisor_name, 100),
            "Jabatan pembimbing": (supervisor_position, 100),
        }

        for label, (value, maximum) in profile_fields.items():

            if len(value) > maximum:
                flash(
                    f"{label} maksimal {maximum} karakter.",
                    "error",
                )
                return redirect(url_for("student.profile"))

        # ---------------------------------------------
        # VALIDATE INTERNSHIP DATES
        # ---------------------------------------------

        internship_start_date = None
        internship_end_date = None

        try:

            if start_value:
                internship_start_date = date.fromisoformat(start_value)

            if end_value:
                internship_end_date = date.fromisoformat(end_value)

        except ValueError:
            flash(
                "Format tanggal PKL tidak valid.",
                "error",
            )
            return redirect(url_for("student.profile"))

        if (
            internship_start_date
            and internship_end_date
            and internship_start_date > internship_end_date
        ):
            flash(
                "Tanggal mulai PKL tidak boleh melewati tanggal selesai.",
                "error",
            )
            return redirect(url_for("student.profile"))

        # ---------------------------------------------
        # SAVE PROFILE PHOTO
        # ---------------------------------------------

        new_photo_name = None
        new_photo_path = None

        if photo_upload and photo_upload.filename:

            try:
                new_photo_name, new_photo_path = (
                    _save_profile_photo(photo_upload)
                )

            except ValueError as exc:
                flash(str(exc), "error")
                return redirect(url_for("student.profile"))

        # ---------------------------------------------
        # DATABASE TRANSACTION
        # ---------------------------------------------

        connection = None
        cursor = None

        old_photo_name = None
        final_photo = None
        update_success = False

        try:

            connection = get_db_connection()
            cursor = connection.cursor(dictionary=True)

            cursor.execute(
                """
                SELECT photo
                FROM users
                WHERE user_id = %s
                LIMIT 1
                """,
                (user_id,),
            )

            existing_user = cursor.fetchone()

            if not existing_user:
                raise RuntimeError("Akun siswa tidak ditemukan.")

            old_photo_name = existing_user.get("photo")

            # Foto baru diprioritaskan daripada permintaan hapus.
            if new_photo_name:
                final_photo = new_photo_name

            elif remove_photo:
                final_photo = None

            else:
                final_photo = old_photo_name

            # -----------------------------------------
            # UPDATE USERS
            # -----------------------------------------

            cursor.execute(
                """
                UPDATE users
                SET
                    full_name = %s,
                    username = %s,
                    email = %s,
                    photo = %s
                WHERE user_id = %s
                """,
                (
                    full_name,
                    username,
                    email,
                    final_photo,
                    user_id,
                ),
            )

            # -----------------------------------------
            # INSERT OR UPDATE STUDENT PROFILE
            # -----------------------------------------

            cursor.execute(
                """
                INSERT INTO student_profiles (
                    user_id,
                    school_name,
                    class_name,
                    major,
                    academic_year,
                    internship_company,
                    internship_industry,
                    internship_address,
                    supervisor_name,
                    supervisor_position,
                    internship_start_date,
                    internship_end_date
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s
                )
                ON DUPLICATE KEY UPDATE
                    school_name = VALUES(school_name),
                    class_name = VALUES(class_name),
                    major = VALUES(major),
                    academic_year = VALUES(academic_year),
                    internship_company = VALUES(internship_company),
                    internship_industry = VALUES(internship_industry),
                    internship_address = VALUES(internship_address),
                    supervisor_name = VALUES(supervisor_name),
                    supervisor_position = VALUES(supervisor_position),
                    internship_start_date = VALUES(internship_start_date),
                    internship_end_date = VALUES(internship_end_date)
                """,
                (
                    user_id,
                    school_name or None,
                    class_name or None,
                    major or None,
                    academic_year or None,
                    internship_company or None,
                    internship_industry or None,
                    internship_address or None,
                    supervisor_name or None,
                    supervisor_position or None,
                    internship_start_date,
                    internship_end_date,
                ),
            )

            connection.commit()
            update_success = True

        except IntegrityError:

            if connection:
                connection.rollback()

            current_app.logger.exception(
                "[ACTRACE][PROFILE] Konflik data profil | user_id=%s",
                user_id,
            )

            flash(
                "Username atau email sudah digunakan oleh akun lain.",
                "error",
            )

        except RuntimeError:

            if connection:
                connection.rollback()

            current_app.logger.exception(
                "[ACTRACE][PROFILE] Database gagal | user_id=%s",
                user_id,
            )

            flash(
                "Profil gagal diperbarui karena gangguan database.",
                "error",
            )

        except Exception:

            if connection:
                connection.rollback()

            current_app.logger.exception(
                "[ACTRACE][PROFILE] Gagal memperbarui profil | user_id=%s",
                user_id,
            )

            flash(
                "Terjadi kesalahan saat memperbarui profil.",
                "error",
            )

        finally:

            if cursor:
                cursor.close()

            if connection:
                connection.close()

        # ---------------------------------------------
        # CLEANUP NEW PHOTO ON FAILURE
        # ---------------------------------------------

        if not update_success:

            if new_photo_path and new_photo_path.exists():
                new_photo_path.unlink(missing_ok=True)

            return redirect(url_for("student.profile"))

        # ---------------------------------------------
        # DELETE OLD PHOTO AFTER SUCCESSFUL COMMIT
        # ---------------------------------------------

        if old_photo_name and old_photo_name != final_photo:

            old_photo_path = (
                Path(current_app.instance_path)
                / "uploads"
                / "profile_photos"
                / Path(old_photo_name).name
            )

            if old_photo_path.is_file():
                old_photo_path.unlink(missing_ok=True)

        # ---------------------------------------------
        # UPDATE SESSION
        # ---------------------------------------------

        session["full_name"] = full_name

        flash(
            "Profil berhasil diperbarui.",
            "success",
        )

        return redirect(url_for("student.profile"))

    # =================================================
    # GET PROFILE DATA
    # =================================================

    connection = None
    cursor = None

    try:

        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        # ---------------------------------------------
        # ACCOUNT + ACADEMIC + INTERNSHIP DATA
        # ---------------------------------------------

        cursor.execute(
            """
            SELECT
                u.user_id,
                u.student_code,
                u.full_name,
                u.username,
                u.email,
                u.photo,
                u.created_at,
                u.updated_at,

                sp.school_name,
                sp.class_name,
                sp.major,
                sp.academic_year,

                sp.internship_company,
                sp.internship_industry,
                sp.internship_address,

                sp.supervisor_name,
                sp.supervisor_position,

                sp.internship_start_date,
                sp.internship_end_date

            FROM users AS u

            LEFT JOIN student_profiles AS sp
                ON sp.user_id = u.user_id

            WHERE u.user_id = %s
            LIMIT 1
            """,
            (user_id,),
        )

        user = cursor.fetchone()

        activity_stats = {}

        if user:
            cursor.execute(
                """
                SELECT
                    COUNT(DISTINCT j.journal_id) AS total_journals,
                    COUNT(DISTINCT jp.photo_id) AS total_photos,
                    MAX(j.activity_date) AS latest_activity
                FROM journals AS j
                LEFT JOIN journal_photos AS jp
                    ON jp.journal_id = j.journal_id
                WHERE j.user_id = %s
                """,
                (user_id,),
            )

            activity_stats = cursor.fetchone() or {}
        # ---------------------------------------------
        # JOURNAL STATISTICS
        # ---------------------------------------------

        cursor.execute(
            """
            SELECT
                COUNT(DISTINCT j.journal_id) AS total_journals,
                COUNT(DISTINCT jp.photo_id) AS total_photos,
                MAX(j.activity_date) AS latest_activity

            FROM journals AS j

            LEFT JOIN journal_photos AS jp
                ON jp.journal_id = j.journal_id

            WHERE j.user_id = %s
            """,
            (user_id,),
        )

        activity_stats = cursor.fetchone() or {}

    except Exception:

        current_app.logger.exception(
            "[ACTRACE][PROFILE] Gagal mengambil profil | user_id=%s",
            user_id,
        )

        flash(
            "Informasi profil gagal dimuat.",
            "error",
        )

        return redirect(url_for("student.dashboard"))

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()

    if not user:
        abort(404)

    # ---------------------------------------------
    # CALCULATE INTERNSHIP STATUS
    # ---------------------------------------------

    today = date.today()

    start_date = user.get("internship_start_date")
    end_date = user.get("internship_end_date")
    company = user.get("internship_company")

    if not company and not start_date and not end_date:

        internship_status = {
            "key": "empty",
            "label": "Not Set",
        }

    elif start_date and start_date > today:

        internship_status = {
            "key": "upcoming",
            "label": "Upcoming",
        }

    elif end_date and end_date < today:

        internship_status = {
            "key": "completed",
            "label": "Completed",
        }

    elif start_date:

        internship_status = {
            "key": "active",
            "label": "In Progress",
        }

    else:

        internship_status = {
            "key": "incomplete",
            "label": "Details Incomplete",
        }

    # ---------------------------------------------
    # RENDER PROFILE
    # ---------------------------------------------

    return render_template(
        "student/profile.html",
        user=user,
        activity_stats=activity_stats,
        internship_status=internship_status,
    )


# =====================================================
# STUDENT PROFILE DETAILS FORM
# =====================================================

@student_bp.post("/profile/details")
@student_required
def profile_details():
    user_id = session["user_id"]

    fields = {
        "school_name": request.form.get("school_name", "").strip(),
        "class_name": request.form.get("class_name", "").strip(),
        "major": request.form.get("major", "").strip(),
        "academic_year": request.form.get("academic_year", "").strip(),
        "internship_company": request.form.get("internship_company", "").strip(),
        "internship_industry": request.form.get("internship_industry", "").strip(),
        "internship_address": request.form.get("internship_address", "").strip(),
        "supervisor_name": request.form.get("supervisor_name", "").strip(),
        "supervisor_position": request.form.get("supervisor_position", "").strip(),
    }

    limits = {
        "school_name": 150,
        "class_name": 50,
        "major": 100,
        "academic_year": 20,
        "internship_company": 150,
        "internship_industry": 100,
        "internship_address": 255,
        "supervisor_name": 100,
        "supervisor_position": 100,
    }

    for field, value in fields.items():
        if len(value) > limits[field]:
            flash(
                f"Kolom {field.replace('_', ' ').title()} "
                f"maksimal {limits[field]} karakter.",
                "error",
            )
            return redirect(url_for("student.profile"))

    start_value = request.form.get("internship_start_date", "").strip()
    end_value = request.form.get("internship_end_date", "").strip()

    try:
        start_date = date.fromisoformat(start_value) if start_value else None
        end_date = date.fromisoformat(end_value) if end_value else None
    except ValueError:
        flash("Format tanggal PKL tidak valid.", "error")
        return redirect(url_for("student.profile"))

    if start_date and end_date and start_date > end_date:
        flash(
            "Tanggal mulai PKL tidak boleh melewati tanggal selesai.",
            "error",
        )
        return redirect(url_for("student.profile"))

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            INSERT INTO student_profiles (
                user_id,
                school_name,
                class_name,
                major,
                academic_year,
                internship_company,
                internship_industry,
                internship_address,
                supervisor_name,
                supervisor_position,
                internship_start_date,
                internship_end_date
            )
            VALUES (
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s
            )
            ON DUPLICATE KEY UPDATE
                school_name = VALUES(school_name),
                class_name = VALUES(class_name),
                major = VALUES(major),
                academic_year = VALUES(academic_year),
                internship_company = VALUES(internship_company),
                internship_industry = VALUES(internship_industry),
                internship_address = VALUES(internship_address),
                supervisor_name = VALUES(supervisor_name),
                supervisor_position = VALUES(supervisor_position),
                internship_start_date = VALUES(internship_start_date),
                internship_end_date = VALUES(internship_end_date)
            """,
            (
                user_id,
                fields["school_name"] or None,
                fields["class_name"] or None,
                fields["major"] or None,
                fields["academic_year"] or None,
                fields["internship_company"] or None,
                fields["internship_industry"] or None,
                fields["internship_address"] or None,
                fields["supervisor_name"] or None,
                fields["supervisor_position"] or None,
                start_date,
                end_date,
            ),
        )

        connection.commit()
        flash(
            "Informasi akademik dan PKL berhasil disimpan.",
            "success",
        )

    except Exception:
        if connection:
            connection.rollback()

        current_app.logger.exception(
            "[ACTRACE][PROFILE] Gagal menyimpan detail profil | user_id=%s",
            user_id,
        )

        flash(
            "Informasi profil gagal disimpan. Silakan coba kembali.",
            "error",
        )

    finally:
        if cursor:
            cursor.close()

        if connection:
            connection.close()

    return redirect(url_for("student.profile"))

# =====================================================
# PRIVATE PROFILE PHOTO
# =====================================================

@student_bp.get("/profile/photo")
@student_required
def profile_photo():

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT photo
            FROM users
            WHERE user_id = %s
            LIMIT 1
            """,
            (session["user_id"],),
        )

        user = cursor.fetchone()

    finally:
        if cursor:
            cursor.close()

        if connection:
            connection.close()

    if not user or not user.get("photo"):
        abort(404)

    filename = user["photo"]

    # Hanya izinkan nama file WebP yang dibuat aplikasi.
    if (
        Path(filename).name != filename
        or not filename.endswith(".webp")
    ):
        abort(404)

    photo_path = (
        Path(current_app.instance_path)
        / "uploads"
        / "profile_photos"
        / filename
    ).resolve()

    upload_folder = (
        Path(current_app.instance_path)
        / "uploads"
        / "profile_photos"
    ).resolve()

    if (
        photo_path.parent != upload_folder
        or not photo_path.is_file()
    ):
        abort(404)

    return send_file(
        photo_path,
        mimetype="image/webp",
        as_attachment=False,
        conditional=True,
        max_age=0,
    )

# =====================================================
# STUDENT ACCOUNT SETTINGS
# =====================================================

@student_bp.route("/settings", methods=["GET", "POST"])
@student_required
def settings():

    user_id = session["user_id"]

    if request.method == "POST":

        current_password = request.form.get(
            "current_password", ""
        )

        new_password = request.form.get(
            "new_password", ""
        )

        confirm_password = request.form.get(
            "confirm_password", ""
        )

        # ---------------------------------------------
        # INPUT VALIDATION
        # ---------------------------------------------

        if not current_password or not new_password or not confirm_password:
            flash(
                "Semua kolom kata sandi wajib diisi.",
                "error",
            )
            return redirect(url_for("student.settings"))

        if len(new_password) < 12:
            flash(
                "Kata sandi baru minimal harus terdiri dari 12 karakter.",
                "error",
            )
            return redirect(url_for("student.settings"))

        # bcrypt hanya memproses maksimal 72 byte.
        if len(new_password.encode("utf-8")) > 72:
            flash(
                "Kata sandi baru terlalu panjang. "
                "Maksimal 72 byte dalam UTF-8.",
                "error",
            )
            return redirect(url_for("student.settings"))

        if new_password != confirm_password:
            flash(
                "Konfirmasi kata sandi baru tidak cocok.",
                "error",
            )
            return redirect(url_for("student.settings"))

        connection = None
        cursor = None

        try:
            connection = get_db_connection()
            cursor = connection.cursor(dictionary=True)

            cursor.execute(
                """
                SELECT password_hash
                FROM users
                WHERE user_id = %s
                LIMIT 1
                """,
                (user_id,),
            )

            user = cursor.fetchone()

            if not user:
                abort(404)

            stored_hash = user["password_hash"]

            if isinstance(stored_hash, str):
                stored_hash = stored_hash.encode("utf-8")

            try:
                password_valid = bcrypt.checkpw(
                    current_password.encode("utf-8"),
                    stored_hash,
                )
            except (ValueError, TypeError, AttributeError):
                password_valid = False

            if not password_valid:
                flash(
                    "Kata sandi saat ini tidak sesuai.",
                    "error",
                )
                return redirect(url_for("student.settings"))

            if bcrypt.checkpw(
                new_password.encode("utf-8"),
                stored_hash,
            ):
                flash(
                    "Kata sandi baru harus berbeda dari kata sandi saat ini.",
                    "error",
                )
                return redirect(url_for("student.settings"))

            new_hash = bcrypt.hashpw(
                new_password.encode("utf-8"),
                bcrypt.gensalt(),
            ).decode("utf-8")

            cursor.execute(
                """
                UPDATE users
                SET password_hash = %s
                WHERE user_id = %s
                """,
                (new_hash, user_id),
            )

            connection.commit()

            # Jangan menghapus session.
            # Pengguna tetap login pada perangkat saat ini.

            flash(
                "Kata sandi berhasil diperbarui. "
                "Sesi perangkat ini tetap aktif.",
                "success",
            )

            return redirect(url_for("student.settings"))

        except RuntimeError:
            if connection:
                connection.rollback()

            current_app.logger.exception(
                "[ACTRACE][SETTINGS] Koneksi database gagal | user_id=%s",
                user_id,
            )

            flash(
                "Kata sandi gagal diperbarui karena gangguan database.",
                "error",
            )

        except Exception:
            if connection:
                connection.rollback()

            current_app.logger.exception(
                "[ACTRACE][SETTINGS] Gagal memperbarui kata sandi | user_id=%s",
                user_id,
            )

            flash(
                "Terjadi kesalahan saat memperbarui kata sandi.",
                "error",
            )

        finally:
            if cursor:
                cursor.close()

            if connection:
                connection.close()

        return redirect(url_for("student.settings"))

    # ---------------------------------------------
    # GET ACCOUNT INFORMATION
    # ---------------------------------------------

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT
                full_name,
                username,
                student_code
            FROM users
            WHERE user_id = %s
            LIMIT 1
            """,
            (user_id,),
        )

        user = cursor.fetchone()

    except RuntimeError:
        current_app.logger.exception(
            "[ACTRACE][SETTINGS] Gagal mengambil informasi akun | user_id=%s",
            user_id,
        )

        flash(
            "Informasi akun gagal dimuat.",
            "error",
        )

        return redirect(url_for("student.dashboard"))

    finally:
        if cursor:
            cursor.close()

        if connection:
            connection.close()

    if not user:
        abort(404)

    return render_template(
        "student/settings.html",
        user=user,
    )

# =====================================================
# STUDENT DASHBOARD
# =====================================================

@student_bp.get("/dashboard")
@student_required
def dashboard():

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    try:
        cur.execute(
            """
            SELECT COUNT(*) AS total
            FROM journals
            WHERE user_id = %s
            """,
            (session["user_id"],)
        )

        total = cur.fetchone()["total"]

        cur.execute(
            """
            SELECT activity_date, title
            FROM journals
            WHERE user_id = %s
            ORDER BY activity_date DESC, journal_id DESC
            LIMIT 1
            """,
            (session["user_id"],)
        )

        latest = cur.fetchone()

    finally:
        cur.close()
        conn.close()

    return render_template(
        "student/dashboard.html",
        total_journals=total,
        latest_activity=latest
    )

# =====================================================
# JOURNAL HISTORY
# =====================================================

@student_bp.get("/history")
@student_required
def history():
    """Menampilkan riwayat jurnal milik siswa."""

    keyword = request.args.get("q", "").strip()[:100]
    start_value = request.args.get("start_date", "").strip()
    end_value = request.args.get("end_date", "").strip()

    start_date = None
    end_date = None
    error = None

    # -------------------------------------------------
    # VALIDASI RENTANG TANGGAL
    # -------------------------------------------------

    try:
        if start_value:
            start_date = date.fromisoformat(start_value)

        if end_value:
            end_date = date.fromisoformat(end_value)

        if start_date and end_date and start_date > end_date:
            raise ValueError()

    except ValueError:
        error = (
            "Rentang tanggal tidak valid. "
            "Periksa kembali tanggal yang dipilih."
        )

        start_date = None
        end_date = None

    # -------------------------------------------------
    # PAGINATION
    # -------------------------------------------------

    try:
        page = max(1, int(request.args.get("page", 1)))
    except (TypeError, ValueError):
        page = 1

    per_page = 10

    journals = []
    total_journals = 0
    total_pages = 1

    # -------------------------------------------------
    # QUERY JOURNAL HISTORY
    # -------------------------------------------------

    if error is None:

        conditions = ["j.user_id = %s"]
        params = [session["user_id"]]

        if keyword:
            conditions.append(
                "(j.title LIKE %s OR j.description LIKE %s)"
            )

            search_term = f"%{keyword}%"

            params.extend([
                search_term,
                search_term
            ])

        if start_date:
            conditions.append("j.activity_date >= %s")
            params.append(start_date)

        if end_date:
            conditions.append("j.activity_date <= %s")
            params.append(end_date)

        where_clause = " AND ".join(conditions)

        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        try:

            # TOTAL DATA
            cursor.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM journals AS j
                WHERE {where_clause}
                """,
                tuple(params)
            )

            total_journals = int(
                (cursor.fetchone() or {}).get("total", 0)
            )

            # TOTAL HALAMAN
            total_pages = max(
                1,
                (total_journals + per_page - 1) // per_page
            )

            page = min(page, total_pages)

            offset = (page - 1) * per_page

            # AMBIL DATA JURNAL
            cursor.execute(
                f"""
                SELECT
                    j.journal_id,
                    j.activity_date,
                    j.title,
                    j.description,
                    j.created_at,
                    j.updated_at,

                    (
                        SELECT COUNT(*)
                        FROM journal_photos AS jp
                        WHERE jp.journal_id = j.journal_id
                    ) AS photo_count

                FROM journals AS j

                WHERE {where_clause}

                ORDER BY
                    j.activity_date DESC,
                    j.journal_id DESC

                LIMIT %s OFFSET %s
                """,
                tuple(params + [per_page, offset])
            )

            journals = cursor.fetchall()

        finally:
            cursor.close()
            connection.close()

    # -------------------------------------------------
    # RENDER TEMPLATE
    # -------------------------------------------------

    return render_template(
        "student/history.html",

        journals=journals,

        keyword=keyword,

        start_date=start_value,
        end_date=end_value,

        total_journals=total_journals,

        page=page,
        per_page=per_page,
        total_pages=total_pages,

        error=error
    )

# =====================================================
# MY JOURNALS
# =====================================================

@student_bp.get("/journals")
@student_required
def journals():

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    try:
        cur.execute(
            """
            SELECT
                journal_id,
                activity_date,
                title,
                description
            FROM journals
            WHERE user_id = %s
            ORDER BY activity_date DESC, journal_id DESC
            """,
            (session["user_id"],)
        )

        rows = cur.fetchall()

    finally:
        cur.close()
        conn.close()

    return render_template(
        "student/journals.html",
        journals=rows
    )


# =====================================================
# JOURNAL DETAIL
# =====================================================

@student_bp.get("/journals/<int:journal_id>")
@student_required
def detail_journal(journal_id):

    student_id = session["user_id"]

    try:
        journal = get_journal_detail(
            journal_id=journal_id,
            user_id=student_id,
        )

    except JournalSaveError:
        current_app.logger.exception(
            "[ACTRACE][DETAIL] Gagal mengambil detail jurnal | "
            "journal_id=%s | student_id=%s",
            journal_id,
            student_id,
        )

        flash(
            "Detail jurnal gagal dimuat. Silakan coba kembali.",
            "error"
        )

        return redirect(
            url_for("student.journals")
        )

    if not journal:
        abort(404)

    return render_template(
        "student/detail_journal.html",
        journal=journal,
    )


# =====================================================
# EDIT JOURNAL
# =====================================================

@student_bp.route("/journals/<int:journal_id>/edit", methods=["GET", "POST"])
@student_required
def edit_journal(journal_id):
    student_id = session["user_id"]

    try:
        journal = get_journal_detail(journal_id, student_id)
        if not journal:
            abort(404)

        if request.method == "POST":
            updated = update_journal(
                journal_id=journal_id,
                user_id=student_id,
                activity_date=request.form.get("activity_date", ""),
                title=request.form.get("title", ""),
                description=request.form.get("description", ""),
                new_photos=request.files.getlist("photos"),
                remove_photo_ids=request.form.getlist("remove_photo_ids"),
            )

            if not updated:
                abort(404)

            flash("Jurnal berhasil diperbarui.", "success")
            return redirect(
                url_for("student.detail_journal", journal_id=journal_id)
            )

    except (JournalValidationError, PhotoValidationError) as exc:
        flash(str(exc), "error")
        journal = get_journal_detail(journal_id, student_id)
        if not journal:
            abort(404)
        return render_template(
            "student/edit_journal.html",
            journal=journal,
            today=date.today().isoformat(),
        ), 400

    except JournalSaveError:
        current_app.logger.exception(
            "[ACTRACE][EDIT] Gagal memperbarui jurnal | journal_id=%s user_id=%s",
            journal_id, student_id,
        )
        flash("Jurnal gagal diperbarui. Silakan coba kembali.", "error")
        journal = get_journal_detail(journal_id, student_id)
        if not journal:
            abort(404)
        return render_template(
            "student/edit_journal.html",
            journal=journal,
            today=date.today().isoformat(),
        ), 500

    return render_template(
        "student/edit_journal.html",
        journal=journal,
        today=date.today().isoformat(),
    )

# =====================================================
# JOURNAL GALLERY
# =====================================================

@student_bp.get("/gallery")
@student_required
def gallery():
    """Menampilkan seluruh dokumentasi foto milik siswa."""

    try:
        page = max(1, int(request.args.get("page", 1)))
    except (TypeError, ValueError):
        page = 1

    per_page = 24

    try:
        photos, total_photos = get_gallery_photos(
            user_id=session["user_id"],
            page=page,
            per_page=per_page,
        )

        total_pages = max(
            1,
            (total_photos + per_page - 1) // per_page,
        )

        page = min(page, total_pages)

        # Jika halaman yang diminta melebihi jumlah halaman,
        # ambil ulang data dari halaman terakhir.
        if page > 1 and not photos and total_photos:
            photos, total_photos = get_gallery_photos(
                user_id=session["user_id"],
                page=page,
                per_page=per_page,
            )

    except JournalSaveError:
        current_app.logger.exception(
            "[ACTRACE][GALLERY] Gagal memuat Gallery | user_id=%s",
            session.get("user_id"),
        )

        flash(
            "Gallery gagal dimuat. Silakan coba kembali.",
            "error",
        )

        photos = []
        total_photos = 0
        total_pages = 1
        page = 1

    return render_template(
        "student/gallery.html",
        photos=photos,
        total_photos=total_photos,
        page=page,
        total_pages=total_pages,
        per_page=per_page,
    )

# =====================================================
# PRIVATE JOURNAL PHOTO
# =====================================================

@student_bp.get(
    "/journals/<int:journal_id>/photos/<int:photo_id>"
)
@student_required
def journal_photo(journal_id, photo_id):

    student_id = session["user_id"]

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    try:
        # -------------------------------------------------
        # VERIFY JOURNAL OWNERSHIP AND PHOTO RELATIONSHIP
        # -------------------------------------------------

        cur.execute(
            """
            SELECT
                jp.file_name,
                jp.file_path
            FROM journal_photos AS jp
            INNER JOIN journals AS j
                ON j.journal_id = jp.journal_id
            WHERE jp.photo_id = %s
              AND jp.journal_id = %s
              AND j.user_id = %s
            LIMIT 1
            """,
            (
                photo_id,
                journal_id,
                student_id,
            )
        )

        photo = cur.fetchone()

    finally:
        cur.close()
        conn.close()

    if not photo:
        abort(404)

    # -----------------------------------------------------
    # RESOLVE PRIVATE PHOTO PATH
    # -----------------------------------------------------

    upload_root = Path(
        current_app.config["UPLOAD_FOLDER"]
    ).resolve()

    file_path = (
        upload_root / photo["file_path"]
    ).resolve()

    # -----------------------------------------------------
    # PREVENT PATH TRAVERSAL
    # -----------------------------------------------------

    try:
        file_path.relative_to(upload_root)

    except ValueError:
        current_app.logger.warning(
            "[ACTRACE][PHOTO] Akses path tidak valid | "
            "journal_id=%s | photo_id=%s | student_id=%s",
            journal_id,
            photo_id,
            student_id,
        )

        abort(404)

    # -----------------------------------------------------
    # CHECK FILE EXISTENCE
    # -----------------------------------------------------

    if not file_path.is_file():
        current_app.logger.warning(
            "[ACTRACE][PHOTO] File foto tidak ditemukan | "
            "journal_id=%s | photo_id=%s",
            journal_id,
            photo_id,
        )

        abort(404)

    # -----------------------------------------------------
    # SEND PRIVATE PHOTO
    # -----------------------------------------------------

    return send_file(
        file_path,
        mimetype=None,
        as_attachment=False,
        download_name=photo["file_name"],
        conditional=True,
        max_age=0,
    )


# =====================================================
# ADD JOURNAL
# =====================================================

@student_bp.route(
    "/journals/add",
    methods=["GET", "POST"]
)
@student_required
def add_journal():

    if request.method == "POST":

        student_id = session["user_id"]

        current_app.logger.info(
            "[ACTRACE][JOURNAL] POST request diterima | student_id=%s",
            student_id
        )

        # -------------------------------------------------
        # FORM DATA
        # -------------------------------------------------

        activity_date = request.form.get(
            "activity_date",
            ""
        )

        title = request.form.get(
            "title",
            ""
        )

        description = request.form.get(
            "description",
            ""
        )

        current_app.logger.info(
            "[ACTRACE][JOURNAL] Data formulir diterima | "
            "student_id=%s | date_present=%s | title_present=%s",
            student_id,
            bool(activity_date),
            bool(title)
        )

        # -------------------------------------------------
        # PHOTO REQUEST DIAGNOSTIC
        # -------------------------------------------------

        photos = request.files.getlist("photos")

        current_app.logger.info(
            "[ACTRACE][JOURNAL] Pemeriksaan upload | "
            "content_type=%s | content_length=%s | files_count=%s",
            request.content_type,
            request.content_length,
            len(photos)
        )

        for index, photo in enumerate(photos, start=1):

            current_app.logger.info(
                "[ACTRACE][JOURNAL] File #%s diterima | "
                "filename=%s | content_type=%s",
                index,
                photo.filename,
                photo.content_type
            )

        # -------------------------------------------------
        # CREATE JOURNAL
        # -------------------------------------------------

        try:

            current_app.logger.info(
                "[ACTRACE][JOURNAL] Memulai create_journal"
            )

            journal_id = create_journal(
                user_id=student_id,
                activity_date=activity_date,
                title=title,
                description=description,
                photos=photos,
            )

            current_app.logger.info(
                "[ACTRACE][JOURNAL] Jurnal berhasil dibuat | "
                "journal_id=%s | student_id=%s",
                journal_id,
                student_id
            )

            flash(
                "Jurnal aktivitas berhasil disimpan.",
                "success"
            )

            return redirect(
                url_for("student.journals")
            )

        # -------------------------------------------------
        # VALIDATION ERROR
        # -------------------------------------------------

        except (
            JournalValidationError,
            PhotoValidationError,
        ) as exc:

            current_app.logger.exception(
                "[ACTRACE][JOURNAL][VALIDATION ERROR] "
                "student_id=%s | error=%s",
                student_id,
                str(exc)
            )

            flash(str(exc), "error")

        # -------------------------------------------------
        # JOURNAL SAVE ERROR
        # -------------------------------------------------

        except JournalSaveError:

            current_app.logger.exception(
                "[ACTRACE][JOURNAL][SAVE ERROR] "
                "student_id=%s",
                student_id
            )

            flash(
                "Jurnal gagal disimpan. Silakan coba kembali.",
                "error"
            )

        # -------------------------------------------------
        # UNEXPECTED ERROR
        # -------------------------------------------------

        except Exception:

            current_app.logger.exception(
                "[ACTRACE][JOURNAL][UNEXPECTED ERROR] "
                "student_id=%s",
                student_id
            )

            flash(
                "Terjadi kesalahan pada sistem. "
                "Silakan coba kembali.",
                "error"
            )

    return render_template(
        "student/add_journal.html",
        today=date.today().isoformat()
    )
