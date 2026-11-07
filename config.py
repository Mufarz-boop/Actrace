
import os
from pathlib import Path
from datetime import timedelta

from dotenv import load_dotenv


# =========================================================
# BASE DIRECTORY & ENVIRONMENT
# =========================================================

BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")


# =========================================================
# ENVIRONMENT HELPERS
# =========================================================

def env_bool(name, default=False):
    """
    Membaca environment variable bertipe boolean.
    """

    value = os.getenv(name)

    if value is None:
        return default

    value = value.strip().lower()

    if value in {"1", "true", "yes", "on"}:
        return True

    if value in {"0", "false", "no", "off"}:
        return False

    raise RuntimeError(
        f"Environment variable {name} harus berupa "
        "true/false, 1/0, yes/no, atau on/off."
    )


def env_int(name, default):
    """
    Membaca environment variable bertipe integer.
    """

    value = os.getenv(name, str(default)).strip()

    try:
        return int(value)
    except (ValueError, TypeError):
        raise RuntimeError(
            f"Environment variable {name} harus berupa angka."
        )


# =========================================================
# APPLICATION CONFIGURATION
# =========================================================

class Config:

    # -----------------------------------------------------
    # Application
    # -----------------------------------------------------

    APP_NAME = os.getenv("APP_NAME", "ACTRACE").strip()

    DEBUG = env_bool("DEBUG", False)

    SECRET_KEY = os.getenv("SECRET_KEY", "").strip()

    HOST = os.getenv("HOST", "127.0.0.1").strip()

    PORT = env_int("PORT", 5000)

    # -----------------------------------------------------
    # Database
    # -----------------------------------------------------

    DB_HOST = os.getenv("DB_HOST", "localhost").strip()

    DB_PORT = env_int("DB_PORT", 3306)

    DB_USER = os.getenv("DB_USER", "root").strip()

    DB_PASSWORD = os.getenv("DB_PASSWORD", "")

    DB_NAME = os.getenv("DB_NAME", "db_actrace").strip()

    # -----------------------------------------------------
    # API Integration
    # -----------------------------------------------------

    SHARED_API_KEY = os.getenv(
        "SHARED_API_KEY", "").strip()

    # -----------------------------------------------------
    # Upload Configuration
    # -----------------------------------------------------

    MAX_CONTENT_LENGTH = env_int("MAX_CONTENT_LENGTH", 26 * 1024 * 1024)
    UPLOAD_FOLDER = (BASE_DIR/ "instance"/ "uploads"/ "journal_photos")
    ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}

    # -----------------------------------------------------
    # Session Security
    # -----------------------------------------------------

    SESSION_COOKIE_HTTPONLY = True

    SESSION_COOKIE_SAMESITE = "Lax"

    SESSION_COOKIE_SECURE = env_bool(
        "SESSION_COOKIE_SECURE",
        False
    )

    PERMANENT_SESSION_LIFETIME = timedelta(hours=2)

    # =====================================================
    # CONFIGURATION VALIDATION
    # =====================================================

    @classmethod
    def validate(cls):

        errors = []

        # -------------------------------------------------
        # 1. APPLICATION VALIDATION
        # -------------------------------------------------

        if not cls.APP_NAME:
            errors.append("APP_NAME tidak boleh kosong.")

        if not cls.HOST:
            errors.append("HOST tidak boleh kosong.")

        if not 1 <= cls.PORT <= 65535:
            errors.append(
                "PORT harus berada antara 1 sampai 65535."
            )

        # -------------------------------------------------
        # 2. SECRET KEY VALIDATION
        # -------------------------------------------------

        if len(cls.SECRET_KEY) < 32:
            errors.append(
                "SECRET_KEY wajib minimal 32 karakter."
            )

        # -------------------------------------------------
        # 3. DATABASE VALIDATION
        # -------------------------------------------------

        if not cls.DB_HOST:
            errors.append("DB_HOST tidak boleh kosong.")

        if not cls.DB_USER:
            errors.append("DB_USER tidak boleh kosong.")

        if not cls.DB_NAME:
            errors.append("DB_NAME tidak boleh kosong.")

        if not 1 <= cls.DB_PORT <= 65535:
            errors.append(
                "DB_PORT harus berada antara 1 sampai 65535."
            )

        # -------------------------------------------------
        # 4. API KEY VALIDATION
        # -------------------------------------------------

        if not cls.SHARED_API_KEY:
            errors.append(
                "SHARED_API_KEY belum dikonfigurasi."
            )

        elif len(cls.SHARED_API_KEY) < 32:
            errors.append(
                "SHARED_API_KEY wajib minimal 32 karakter."
            )

        elif any(char.isspace() for char in cls.SHARED_API_KEY):
            errors.append(
                "SHARED_API_KEY tidak boleh mengandung spasi."
            )

        elif cls.SHARED_API_KEY == cls.SECRET_KEY:
            errors.append(
                "SHARED_API_KEY harus berbeda dari SECRET_KEY."
            )

        # -------------------------------------------------
        # 5. UPLOAD VALIDATION
        # -------------------------------------------------

        if cls.MAX_CONTENT_LENGTH <= 0:
            errors.append(
                "MAX_CONTENT_LENGTH harus lebih besar dari 0."
            )

        if not cls.ALLOWED_IMAGE_EXTENSIONS:
            errors.append(
                "ALLOWED_IMAGE_EXTENSIONS tidak boleh kosong."
            )

        # -------------------------------------------------
        # 6. DISPLAY ALL CONFIGURATION ERRORS
        # -------------------------------------------------

        if errors:
            error_message = "\n".join(
                f"- {error}" for error in errors
            )

            raise RuntimeError(
                "Validasi konfigurasi ACTRACE gagal:\n"
                f"{error_message}"
            )

        # -------------------------------------------------
        # 7. CREATE UPLOAD DIRECTORY
        # -------------------------------------------------

        try:
            cls.UPLOAD_FOLDER.mkdir(
                parents=True,
                exist_ok=True
            )
        except OSError as exc:
            raise RuntimeError(
                "Folder penyimpanan foto ACTRACE "
                "tidak dapat dibuat."
            ) from exc