import logging
from datetime import date

from mysql.connector import Error

from app.db import get_db_connection

from app.services.photo_service import (
    save_journal_photos,
    delete_saved_photos,
    delete_photo_files,
    PhotoValidationError,
)

logger = logging.getLogger(__name__)

class JournalValidationError(Exception):
    """Kesalahan validasi data jurnal."""

class JournalSaveError(Exception):
    """Kesalahan ketika jurnal gagal disimpan."""


class JournalDeleteError(Exception):
    """Kesalahan ketika jurnal gagal dihapus."""

# =====================================================
# JOURNAL VALIDATION
# =====================================================

def validate_journal_data(activity_date, title, description):
    """
    Memvalidasi data utama jurnal sebelum disimpan.
    """

    if not activity_date:
        raise JournalValidationError(
            "Tanggal aktivitas wajib diisi."
        )

    if not title or not title.strip():
        raise JournalValidationError(
            "Judul aktivitas wajib diisi."
        )

    if not description or not description.strip():
        raise JournalValidationError(
            "Deskripsi aktivitas wajib diisi."
        )

    title = title.strip()
    description = description.strip()

    if len(title) > 150:
        raise JournalValidationError(
            "Judul maksimal 150 karakter."
        )

    try:
        parsed_date = date.fromisoformat(activity_date)

    except (ValueError, TypeError):
        raise JournalValidationError(
            "Format tanggal aktivitas tidak valid."
        )

    if parsed_date > date.today():
        raise JournalValidationError(
            "Tanggal aktivitas tidak boleh melebihi hari ini."
        )

    return parsed_date, title, description


# =====================================================
# CREATE JOURNAL
# =====================================================

def create_journal(
    user_id,
    activity_date,
    title,
    description,
    photos=None,
):
    """
    Membuat jurnal baru beserta foto dokumentasinya.

    Data jurnal dan metadata foto disimpan dalam
    satu transaksi database.
    """

    if not user_id:
        raise JournalValidationError(
            "Sesi pengguna tidak valid."
        )

    parsed_date, title, description = validate_journal_data(
        activity_date,
        title,
        description,
    )

    saved_photos = []
    connection = None
    cursor = None

    try:
        # =================================================
        # 1. DATABASE CONNECTION
        # =================================================

        connection = get_db_connection()
        connection.start_transaction()

        cursor = connection.cursor()

        # =================================================
        # 2. INSERT JOURNAL
        # =================================================

        cursor.execute(
            """
            INSERT INTO journals (
                user_id,
                activity_date,
                title,
                description
            )
            VALUES (%s, %s, %s, %s)
            """,
            (
                user_id,
                parsed_date,
                title,
                description,
            ),
        )

        journal_id = cursor.lastrowid

        if not journal_id:
            raise JournalSaveError(
                "ID jurnal gagal dibuat."
            )

        # =================================================
        # 3. SAVE JOURNAL PHOTOS
        # =================================================

        selected_photos = [
            photo for photo in (photos or [])
            if photo and photo.filename
        ]

        if selected_photos:
            saved_photos = save_journal_photos(
                selected_photos,
                journal_id,
            )

        # =================================================
        # 4. INSERT PHOTO METADATA
        # =================================================

        if saved_photos:
            photo_records = [
                (
                    journal_id,
                    photo["file_name"],
                    photo["file_path"],
                )
                for photo in saved_photos
            ]

            cursor.executemany(
                """
                INSERT INTO journal_photos (
                    journal_id,
                    file_name,
                    file_path
                )
                VALUES (%s, %s, %s)
                """,
                photo_records,
            )

        # =================================================
        # 5. COMMIT TRANSACTION
        # =================================================

        connection.commit()

        logger.info(
            "Jurnal berhasil dibuat. "
            "Journal ID: %s, User ID: %s, Jumlah foto: %s",
            journal_id,
            user_id,
            len(saved_photos),
        )

        return journal_id

    except PhotoValidationError:
        if connection and connection.is_connected():
            connection.rollback()

        delete_saved_photos(saved_photos)

        logger.exception(
            "Validasi foto jurnal gagal. User ID: %s",
            user_id,
        )

        raise

    except JournalSaveError:
        if connection and connection.is_connected():
            connection.rollback()

        delete_saved_photos(saved_photos)

        logger.exception(
            "Penyimpanan jurnal gagal. User ID: %s",
            user_id,
        )

        raise

    except Error as exc:
        if connection and connection.is_connected():
            connection.rollback()

        delete_saved_photos(saved_photos)

        logger.exception(
            "Database error saat menyimpan jurnal. User ID: %s",
            user_id,
        )

        raise JournalSaveError(
            "Jurnal gagal disimpan karena terjadi "
            "kesalahan database."
        ) from exc

    except Exception as exc:
        if connection and connection.is_connected():
            connection.rollback()

        delete_saved_photos(saved_photos)

        logger.exception(
            "Unexpected error saat menyimpan jurnal. User ID: %s",
            user_id,
        )

        raise JournalSaveError(
            "Terjadi kesalahan ketika menyimpan jurnal."
        ) from exc

    finally:
        if cursor:
            try:
                cursor.close()
            except Error:
                logger.exception(
                    "Gagal menutup database cursor."
                )

        if connection:
            try:
                if connection.is_connected():
                    connection.close()
            except Error:
                logger.exception(
                    "Gagal menutup koneksi database."
                )


# =====================================================
# GET JOURNAL DETAIL
# =====================================================

def get_journal_detail(journal_id, user_id):
    """
    Mengambil detail jurnal beserta seluruh foto
    dokumentasinya.

    Keamanan:
    - Jurnal harus dimiliki oleh user yang meminta.
    - Query menggunakan parameterized query.
    - Foto hanya diambil dari jurnal tersebut.

    Mengembalikan:
    - Dictionary berisi detail jurnal dan daftar foto.
    - None jika jurnal tidak ditemukan atau bukan milik user.
    """

    if not journal_id or not user_id:
        return None

    connection = None
    cursor = None

    try:
        # =================================================
        # 1. DATABASE CONNECTION
        # =================================================

        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        # =================================================
        # 2. GET JOURNAL DATA
        # =================================================

        cursor.execute(
            """
            SELECT
                journal_id,
                user_id,
                activity_date,
                title,
                description,
                created_at,
                updated_at
            FROM journals
            WHERE journal_id = %s
              AND user_id = %s
            LIMIT 1
            """,
            (
                journal_id,
                user_id,
            ),
        )

        journal = cursor.fetchone()

        if not journal:
            return None

        # =================================================
        # 3. GET JOURNAL PHOTOS
        # =================================================

        cursor.execute(
            """
            SELECT
                photo_id,
                journal_id,
                file_name,
                file_path,
                uploaded_at
            FROM journal_photos
            WHERE journal_id = %s
            ORDER BY photo_id ASC
            """,
            (journal_id,),
        )

        journal["photos"] = cursor.fetchall()

        # =================================================
        # 4. RETURN JOURNAL DATA
        # =================================================

        return journal

    except Error as exc:
        logger.exception(
            "Gagal mengambil detail jurnal. "
            "Journal ID: %s, User ID: %s",
            journal_id,
            user_id,
        )

        raise JournalSaveError(
            "Detail jurnal gagal dimuat."
        ) from exc

    finally:
        if cursor:
            try:
                cursor.close()
            except Error:
                logger.exception(
                    "Gagal menutup database cursor."
                )

        if connection:
            try:
                if connection.is_connected():
                    connection.close()
            except Error:
                logger.exception(
                    "Gagal menutup koneksi database."
                )


# =====================================================
# UPDATE JOURNAL
# =====================================================

def update_journal(
    journal_id,
    user_id,
    activity_date,
    title,
    description,
    new_photos=None,
    remove_photo_ids=None,
):
    """Memperbarui jurnal dan dokumentasinya secara aman."""
    if not journal_id or not user_id:
        raise JournalValidationError("Data jurnal tidak valid.")

    parsed_date, title, description = validate_journal_data(
        activity_date, title, description
    )

    selected_photos = [
        photo for photo in (new_photos or [])
        if photo and photo.filename
    ]

    try:
        remove_ids = sorted({
            int(photo_id) for photo_id in (remove_photo_ids or [])
        })
    except (TypeError, ValueError):
        raise JournalValidationError("Permintaan penghapusan foto tidak valid.")

    if any(photo_id <= 0 for photo_id in remove_ids):
        raise JournalValidationError("ID foto tidak valid.")

    connection = None
    cursor = None
    saved_photos = []
    paths_to_delete = []

    try:
        connection = get_db_connection()
        connection.start_transaction()
        cursor = connection.cursor(dictionary=True)

        # Lock jurnal agar dua permintaan edit tidak saling menimpa.
        cursor.execute(
            """
            SELECT journal_id
            FROM journals
            WHERE journal_id = %s AND user_id = %s
            FOR UPDATE
            """,
            (journal_id, user_id),
        )
        if not cursor.fetchone():
            connection.rollback()
            return False

        cursor.execute(
            """
            SELECT photo_id, file_path
            FROM journal_photos
            WHERE journal_id = %s
            ORDER BY photo_id
            FOR UPDATE
            """,
            (journal_id,),
        )
        current_photos = cursor.fetchall()
        current_by_id = {int(row["photo_id"]): row for row in current_photos}

        # ID foto yang dikirim harus benar-benar milik jurnal ini.
        if not set(remove_ids).issubset(current_by_id):
            raise JournalValidationError(
                "Salah satu foto yang dipilih tidak ditemukan pada jurnal ini."
            )

        remaining_count = len(current_photos) - len(remove_ids)
        if remaining_count + len(selected_photos) > 5:
            raise PhotoValidationError(
                "Maksimal 5 foto per jurnal. Hapus foto lama atau kurangi foto baru."
            )

        if len(selected_photos) > 5:
            raise PhotoValidationError("Maksimal 5 foto untuk setiap jurnal.")

        # Simpan file baru sebelum commit; jika transaksi gagal, file dibersihkan.
        if selected_photos:
            saved_photos = save_journal_photos(selected_photos, journal_id)

        cursor.execute(
            """
            UPDATE journals
            SET activity_date = %s,
                title = %s,
                description = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE journal_id = %s AND user_id = %s
            """,
            (parsed_date, title, description, journal_id, user_id),
        )

        if remove_ids:
            placeholders = ", ".join(["%s"] * len(remove_ids))
            cursor.execute(
                f"""
                DELETE FROM journal_photos
                WHERE journal_id = %s
                  AND photo_id IN ({placeholders})
                """,
                (journal_id, *remove_ids),
            )
            paths_to_delete = [
                current_by_id[photo_id]["file_path"]
                for photo_id in remove_ids
            ]

        if saved_photos:
            cursor.executemany(
                """
                INSERT INTO journal_photos (journal_id, file_name, file_path)
                VALUES (%s, %s, %s)
                """,
                [
                    (journal_id, photo["file_name"], photo["file_path"])
                    for photo in saved_photos
                ],
            )

        connection.commit()

        # File fisik baru dihapus hanya setelah transaksi DB berhasil.
        if paths_to_delete:
            delete_photo_files(paths_to_delete)

        logger.info(
            "Jurnal diperbarui. journal_id=%s user_id=%s added=%s removed=%s",
            journal_id, user_id, len(saved_photos), len(paths_to_delete)
        )
        return True

    except (JournalValidationError, PhotoValidationError):
        if connection and connection.is_connected():
            connection.rollback()
        delete_saved_photos(saved_photos)
        raise

    except Error as exc:
        if connection and connection.is_connected():
            connection.rollback()
        delete_saved_photos(saved_photos)
        logger.exception(
            "Database error saat memperbarui jurnal. journal_id=%s user_id=%s",
            journal_id, user_id
        )
        raise JournalSaveError("Perubahan jurnal gagal disimpan.") from exc

    except Exception as exc:
        if connection and connection.is_connected():
            connection.rollback()
        delete_saved_photos(saved_photos)
        logger.exception(
            "Kesalahan saat memperbarui jurnal. journal_id=%s user_id=%s",
            journal_id, user_id
        )
        raise JournalSaveError("Terjadi kesalahan saat memperbarui jurnal.") from exc

    finally:
        if cursor:
            try:
                cursor.close()
            except Error:
                logger.exception("Gagal menutup database cursor.")
        if connection:
            try:
                if connection.is_connected():
                    connection.close()
            except Error:
                logger.exception("Gagal menutup koneksi database.")


# =====================================================
# JOURNAL REPORT DATA
# =====================================================

def get_journals_for_report(user_id, start_date, end_date):
    """
    Mengambil jurnal milik siswa pada rentang tanggal inklusif,
    beserta seluruh metadata foto yang terhubung.
    """
    if not user_id or not start_date or not end_date:
        raise JournalValidationError("Parameter rekap jurnal tidak valid.")

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT
                j.journal_id,
                j.activity_date,
                j.title,
                j.description,
                j.created_at,
                j.updated_at
            FROM journals AS j
            WHERE j.user_id = %s
              AND j.activity_date BETWEEN %s AND %s
            ORDER BY j.activity_date ASC, j.journal_id ASC
            """,
            (user_id, start_date, end_date),
        )
        journals = cursor.fetchall()

        if not journals:
            return []

        journal_ids = [journal["journal_id"] for journal in journals]
        placeholders = ", ".join(["%s"] * len(journal_ids))
        cursor.execute(
            f"""
            SELECT
                jp.photo_id,
                jp.journal_id,
                jp.file_name,
                jp.file_path,
                jp.uploaded_at
            FROM journal_photos AS jp
            INNER JOIN journals AS j
                ON j.journal_id = jp.journal_id
            WHERE j.user_id = %s
              AND jp.journal_id IN ({placeholders})
            ORDER BY jp.journal_id ASC, jp.photo_id ASC
            """,
            (user_id, *journal_ids),
        )
        photos_by_journal = {}
        for photo in cursor.fetchall():
            photos_by_journal.setdefault(photo["journal_id"], []).append(photo)

        for journal in journals:
            journal["photos"] = photos_by_journal.get(journal["journal_id"], [])
            journal["photo_count"] = len(journal["photos"])

        return journals

    except Error as exc:
        logger.exception(
            "Gagal mengambil data rekap jurnal. user_id=%s",
            user_id,
        )
        raise JournalSaveError("Data rekap jurnal gagal dimuat.") from exc

    finally:
        if cursor:
            try:
                cursor.close()
            except Error:
                logger.exception("Gagal menutup cursor rekap jurnal.")
        if connection:
            try:
                if connection.is_connected():
                    connection.close()
            except Error:
                logger.exception("Gagal menutup koneksi rekap jurnal.")

# =====================================================
# GET STUDENT GALLERY PHOTOS
# =====================================================

def get_gallery_photos(user_id, page=1, per_page=24):
    """
    Mengambil foto dokumentasi milik seorang peserta.

    Foto hanya diambil dari jurnal yang dimiliki user_id.
    Hasil diurutkan berdasarkan tanggal aktivitas terbaru.
    """

    if not user_id:
        raise JournalSaveError("Sesi pengguna tidak valid.")

    page = max(1, int(page))
    per_page = max(1, min(int(per_page), 100))
    offset = (page - 1) * per_page

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)

        # Total foto milik peserta
        cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM journal_photos AS jp
            INNER JOIN journals AS j
                ON j.journal_id = jp.journal_id
            WHERE j.user_id = %s
            """,
            (user_id,),
        )

        total_photos = int(
            (cursor.fetchone() or {}).get("total", 0)
        )

        # Data foto beserta tanggal dan jurnal asal
        cursor.execute(
            """
            SELECT
                jp.photo_id,
                jp.journal_id,
                jp.file_name,
                jp.file_path,
                jp.uploaded_at,
                j.activity_date,
                j.title
            FROM journal_photos AS jp
            INNER JOIN journals AS j
                ON j.journal_id = jp.journal_id
            WHERE j.user_id = %s
            ORDER BY
                j.activity_date DESC,
                j.journal_id DESC,
                jp.photo_id DESC
            LIMIT %s OFFSET %s
            """,
            (user_id, per_page, offset),
        )

        photos = cursor.fetchall()

        return photos, total_photos

    except Error as exc:
        logger.exception(
            "Gagal mengambil Gallery. User ID: %s",
            user_id,
        )

        raise JournalSaveError(
            "Gallery gagal dimuat."
        ) from exc

    finally:
        if cursor:
            cursor.close()

        if connection:
            connection.close()

# =====================================================
# DELETE JOURNAL
# =====================================================

def delete_journal(journal_id, user_id):
    """
    Menghapus jurnal milik pengguna beserta metadata
    dan file fisik foto dokumentasinya.

    Alur:
    1. Validasi parameter.
    2. Membuka transaksi database.
    3. Memastikan jurnal dimiliki pengguna.
    4. Mengunci data jurnal.
    5. Mengambil seluruh path foto.
    6. Menghapus jurnal.
    7. Melakukan commit.
    8. Menghapus file foto fisik.

    Returns:
        dict:
            {
                "deleted": bool,
                "cleanup_pending": bool
            }

    JournalDeleteError:
        Jika proses database gagal.
    """

    if not journal_id or not user_id:

        raise JournalValidationError(
            "Data jurnal tidak valid."
        )

    connection = None
    cursor = None

    photo_paths = []
    transaction_committed = False

    try:

        # =================================================
        # 1. DATABASE CONNECTION
        # =================================================

        connection = get_db_connection()

        connection.start_transaction()

        cursor = connection.cursor(
            dictionary=True
        )

        # =================================================
        # 2. VALIDATE JOURNAL OWNERSHIP
        # =================================================

        cursor.execute(
            """
            SELECT journal_id
            FROM journals
            WHERE journal_id = %s
              AND user_id = %s
            FOR UPDATE
            """,
            (
                journal_id,
                user_id,
            ),
        )

        journal = cursor.fetchone()

        if not journal:

            connection.rollback()

            return {
                "deleted": False,
                "cleanup_pending": False,
            }

        # =================================================
        # 3. GET JOURNAL PHOTO PATHS
        # =================================================

        cursor.execute(
            """
            SELECT file_path
            FROM journal_photos
            WHERE journal_id = %s
            FOR UPDATE
            """,
            (journal_id,),
        )

        photo_records = cursor.fetchall()

        photo_paths = [
            row["file_path"]
            for row in photo_records
            if row.get("file_path")
        ]

        # =================================================
        # 4. DELETE JOURNAL
        # =================================================

        cursor.execute(
            """
            DELETE FROM journals
            WHERE journal_id = %s
              AND user_id = %s
            """,
            (
                journal_id,
                user_id,
            ),
        )

        if cursor.rowcount != 1:

            connection.rollback()

            return {
                "deleted": False,
                "cleanup_pending": False,
            }

        # =================================================
        # 5. COMMIT DATABASE TRANSACTION
        # =================================================

        connection.commit()

        transaction_committed = True

        logger.info(
            "[ACTRACE][DELETE] Database journal berhasil dihapus. "
            "journal_id=%s user_id=%s photo_count=%s",
            journal_id,
            user_id,
            len(photo_paths),
        )

        # =================================================
        # 6. DELETE PHYSICAL PHOTO FILES
        # =================================================

        failed_paths = []

        if photo_paths:

            try:

                failed_paths = delete_photo_files(
                    photo_paths
                )

            except Exception:

                # Database sudah berhasil di-commit.
                # Jangan menganggap jurnal masih ada
                # hanya karena penghapusan file gagal.

                logger.exception(
                    "[ACTRACE][DELETE] "
                    "Terjadi kesalahan saat membersihkan file foto. "
                    "journal_id=%s",
                    journal_id,
                )

                failed_paths = photo_paths

        # =================================================
        # 7. CLEANUP RESULT
        # =================================================

        cleanup_pending = bool(failed_paths)

        if cleanup_pending:

            logger.error(
                "[ACTRACE][DELETE] "
                "Beberapa file foto belum berhasil dihapus. "
                "journal_id=%s failed_files=%s",
                journal_id,
                failed_paths,
            )

        else:

            logger.info(
                "[ACTRACE][DELETE] "
                "Seluruh file dokumentasi berhasil dibersihkan. "
                "journal_id=%s",
                journal_id,
            )

        return {
            "deleted": True,
            "cleanup_pending": cleanup_pending,
        }

    except Error as exc:

        if connection and not transaction_committed:

            try:

                connection.rollback()

            except Exception:

                logger.exception(
                    "Rollback transaksi penghapusan gagal."
                )

        logger.exception(
            "[ACTRACE][DELETE] Database error. "
            "journal_id=%s user_id=%s",
            journal_id,
            user_id,
        )

        raise JournalDeleteError(
            "Jurnal gagal dihapus karena kesalahan database."
        ) from exc

    except Exception as exc:

        if connection and not transaction_committed:

            try:

                connection.rollback()

            except Exception:

                logger.exception(
                    "Rollback transaksi penghapusan gagal."
                )

        logger.exception(
            "[ACTRACE][DELETE] Unexpected error. "
            "journal_id=%s user_id=%s",
            journal_id,
            user_id,
        )

        raise JournalDeleteError(
            "Terjadi kesalahan ketika menghapus jurnal."
        ) from exc

    finally:

        if cursor:

            try:

                cursor.close()

            except Exception:

                logger.exception(
                    "Gagal menutup cursor penghapusan jurnal."
                )

        if connection:

            try:

                if connection.is_connected():
                    connection.close()

            except Exception:

                logger.exception(
                    "Gagal menutup koneksi database penghapusan jurnal."
                )