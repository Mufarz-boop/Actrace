import bcrypt
import io
import uuid
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

from PIL import Image, UnidentifiedImageError
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
