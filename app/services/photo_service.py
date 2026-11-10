import logging
import uuid
from pathlib import Path

from PIL import Image, UnidentifiedImageError
from flask import current_app
from werkzeug.datastructures import FileStorage


logger = logging.getLogger(__name__)

MAX_PHOTO_SIZE = 5 * 1024 * 1024
MAX_PHOTOS = 5

ALLOWED_FORMATS = {
    "JPEG": ".jpg",
    "PNG": ".png",
    "WEBP": ".webp",
}


class PhotoValidationError(Exception):
    """Kesalahan validasi foto jurnal."""


# =====================================================
# VALIDATE PHOTO
# =====================================================

def validate_photo(file: FileStorage):
    """
    Memvalidasi satu file foto berdasarkan:
    - Keberadaan file
    - Ukuran file
    - Format gambar aktual menggunakan Pillow
    """

    if not file or not file.filename:
        raise PhotoValidationError(
            "File foto tidak valid."
        )

    file.stream.seek(0, 2)
    file_size = file.stream.tell()
    file.stream.seek(0)

    if file_size <= 0:
        raise PhotoValidationError(
            "File foto tidak boleh kosong."
        )

    if file_size > MAX_PHOTO_SIZE:
        raise PhotoValidationError(
            "Ukuran setiap foto maksimal 5 MB."
        )

    try:
        with Image.open(file.stream) as image:
            image_format = image.format

            if image_format not in ALLOWED_FORMATS:
                raise PhotoValidationError(
                    "Format foto hanya boleh JPG, PNG, atau WebP."
                )

            image.verify()

        file.stream.seek(0)

    except PhotoValidationError:
        raise

    except (
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:

        raise PhotoValidationError(
            "File yang diunggah bukan gambar yang valid."
        ) from exc

    extension = ALLOWED_FORMATS[image_format]

    return {
        "extension": extension,
        "size": file_size,
    }


# =====================================================
# SAVE JOURNAL PHOTOS
# =====================================================

def save_journal_photos(files, journal_id):
    """
    Menyimpan foto ke direktori privat:

    instance/uploads/journal_photos/<journal_id>/

    Mengembalikan metadata foto untuk disimpan ke database.
    """

    selected_files = [
        file for file in files
        if file and file.filename
    ]

    if len(selected_files) > MAX_PHOTOS:
        raise PhotoValidationError(
            "Maksimal 5 foto untuk setiap jurnal."
        )

    if not selected_files:
        return []

    upload_root = Path(
        current_app.config["UPLOAD_FOLDER"]
    )

    journal_directory = (
        upload_root / str(journal_id)
    )

    saved_files = []

    try:

        journal_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        for file in selected_files:

            validation = validate_photo(file)

            stored_name = (
                f"{uuid.uuid4().hex}"
                f"{validation['extension']}"
            )

            destination = (
                journal_directory / stored_name
            )

            file.stream.seek(0)
            file.save(destination)

            saved_files.append({
                "file_name": stored_name,
                "file_path": (
                    f"{journal_id}/{stored_name}"
                ),
                "absolute_path": destination,
            })

        return saved_files

    except Exception:

        delete_saved_photos(saved_files)

        raise


# =====================================================
# DELETE SAVED PHOTOS
# =====================================================

def delete_saved_photos(photos):
    """
    Menghapus file foto yang sudah terlanjur disimpan
    apabila proses penyimpanan jurnal gagal.
    """

    for photo in photos:

        try:

            path = photo.get("absolute_path")

            if path and Path(path).is_file():
                Path(path).unlink()

        except OSError:

            logger.exception(
                "Gagal menghapus foto jurnal."
            )


# =====================================================
# DELETE PHOTO FILES
# =====================================================

def delete_photo_files(file_paths):
    """
    Menghapus file foto setelah transaksi database berhasil.

    Keamanan:
    - Seluruh path dibatasi ke direktori upload ACTRACE.
    - Path traversal ditolak.
    - Symlink yang mengarah keluar direktori upload ditolak.

    Returns:
        list:
            Daftar path file yang gagal dihapus.
            List kosong berarti seluruh file berhasil
            dihapus atau memang sudah tidak tersedia.
    """

    upload_folder = current_app.config.get(
        "UPLOAD_FOLDER"
    )

    if not upload_folder:

        logger.error(
            "UPLOAD_FOLDER belum dikonfigurasi."
        )

        return list(file_paths or [])

    upload_root = Path(
        upload_folder
    ).resolve()

    failed_paths = []

    for relative_path in file_paths or []:

        try:

            if not isinstance(relative_path, str):
                raise ValueError(
                    "Path foto tidak valid."
                )

            if not relative_path.strip():
                raise ValueError(
                    "Path foto kosong."
                )

            candidate = (
                upload_root / relative_path
            ).resolve()

            # Pastikan file tetap berada
            # di dalam direktori upload.
            candidate.relative_to(upload_root)

            # File yang sudah tidak tersedia
            # dianggap sudah bersih.
            if candidate.is_file():
                candidate.unlink()

        except (
            ValueError,
            OSError,
            TypeError,
        ):

            failed_paths.append(
                str(relative_path)
            )

            logger.exception(
                "Gagal menghapus file foto jurnal: %s",
                relative_path,
            )

    return failed_paths