"""
ACTRACE | account_service.py

Pembuatan akun siswa lewat form tersembunyi di halaman login
(shortcut Alt + F1 + U).

PENTING: shortcut keyboard hanyalah saklar tampilan, BUKAN kontrol keamanan.
Siapa pun yang membaca JavaScript halaman login dapat menemukannya. Seluruh
perlindungan ada di server:

1. Fitur dimatikan lewat konfigurasi (ACCOUNT_PROVISIONING_ENABLED).
2. Kode akses operator (PROVISIONING_ACCESS_CODE) wajib benar.
3. Percobaan kode akses yang salah dibatasi per alamat IP.
4. CSRF tetap aktif (CSRFProtect global).
5. Semua input divalidasi ulang di server; query memakai parameter.

Aturan bisnis yang dipakai sama dengan ``create_student.py`` dan halaman
Settings: bcrypt cost 12, kata sandi minimal 12 karakter dan maksimal 72 byte.
"""

import hmac
import re
import threading
import time
import unicodedata
from collections import deque

import bcrypt
import mysql.connector
from flask import current_app

from app.db import get_db_connection


# =========================================================
# ATURAN VALIDASI
# =========================================================

PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_BYTES = 72  # batas bcrypt

# Tanpa "/" karena student_code dipakai sebagai segmen URL pada
# /api/students/<string:student_code>/..., dan converter <string:>
# Flask tidak menerima garis miring.
STUDENT_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,29}$")

# Tanpa "@" agar username tidak pernah bisa sama dengan email siapa pun.
# Login memakai ``WHERE username = %s OR email = %s``; tanpa aturan ini
# seseorang bisa mendaftar dengan username berupa email orang lain.
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,49}$")

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")

# Huruf (Unicode), spasi, titik, koma, apostrof, strip. Tanpa angka dan
# simbol markup, sehingga aman dipakai di PDF/HTML.
FULL_NAME_RE = re.compile(
    r"^[^\W\d_]+(?:[ .,'\u2019-]+[^\W\d_]+)*\.?$"
)

FIELD_ORDER = (
    "student_code",
    "full_name",
    "username",
    "email",
    "password",
    "confirm_password",
)


class DuplicateAccountError(Exception):
    """Salah satu kolom UNIQUE sudah dipakai. ``field`` dapat None."""

    def __init__(self, field=None):
        super().__init__(field or "duplicate")
        self.field = field


def validate_new_account(form):
    """
    Validasi data form. Mengembalikan ``(clean, errors)``.

    ``clean`` berisi nilai yang sudah dinormalisasi; ``errors`` berupa
    dict ``{nama_field: pesan}`` dan kosong bila semuanya valid.
    """

    errors = {}

    student_code = (form.get("student_code") or "").strip()
    full_name = unicodedata.normalize(
        "NFC", " ".join((form.get("full_name") or "").split())
    )
    username = (form.get("username") or "").strip().lower()
    email = (form.get("email") or "").strip().lower()
    password = form.get("password") or ""
    confirm_password = form.get("confirm_password") or ""

    if not STUDENT_CODE_RE.fullmatch(student_code):
        errors["student_code"] = (
            "Kode siswa 3-30 karakter: huruf, angka, titik, "
            "garis bawah, atau strip."
        )

    if not 2 <= len(full_name) <= 100 or not FULL_NAME_RE.fullmatch(full_name):
        errors["full_name"] = (
            "Nama lengkap 2-100 karakter, hanya huruf, spasi, "
            "titik, koma, apostrof, dan strip."
        )

    if not USERNAME_RE.fullmatch(username):
        errors["username"] = (
            "Username 3-50 karakter: huruf kecil, angka, titik, "
            "garis bawah, atau strip. Tidak boleh memakai @."
        )

    if len(email) > 100 or not EMAIL_RE.fullmatch(email):
        errors["email"] = "Format email tidak valid (maksimal 100 karakter)."

    if len(password) < PASSWORD_MIN_LENGTH:
        errors["password"] = (
            f"Kata sandi minimal {PASSWORD_MIN_LENGTH} karakter."
        )
    elif len(password.encode("utf-8")) > PASSWORD_MAX_BYTES:
        errors["password"] = (
            f"Kata sandi terlalu panjang. Maksimal {PASSWORD_MAX_BYTES} "
            "byte dalam UTF-8."
        )
    elif username and username in password.lower():
        errors["password"] = "Kata sandi tidak boleh memuat username."

    if "password" not in errors and password != confirm_password:
        errors["confirm_password"] = "Konfirmasi kata sandi tidak cocok."

    clean = {
        "student_code": student_code,
        "full_name": full_name,
        "username": username,
        "email": email,
        "password": password,
    }

    return clean, errors


# =========================================================
# KODE AKSES OPERATOR
# =========================================================

def verify_access_code(candidate):
    """Bandingkan kode akses dengan waktu konstan."""

    expected = current_app.config.get("PROVISIONING_ACCESS_CODE", "")

    if not expected or not candidate:
        return False

    return hmac.compare_digest(
        candidate.encode("utf-8"),
        expected.encode("utf-8"),
    )


# =========================================================
# PEMBATAS PERCOBAAN (in-memory, per proses)
# =========================================================

class AttemptLimiter:
    """
    Menghitung kegagalan per kunci (alamat IP) dalam jendela waktu.

    Batasan: state disimpan di memori proses. Jika aplikasi dijalankan
    dengan beberapa worker, batas berlaku per worker. Untuk produksi
    multi-worker gunakan Flask-Limiter dengan penyimpanan bersama.
    """

    def __init__(self, max_failures=5, window_seconds=15 * 60):
        self.max_failures = max_failures
        self.window = window_seconds
        self._hits = {}
        self._lock = threading.Lock()

    def _prune(self, key, now):
        hits = self._hits.get(key)

        if hits is None:
            return None

        while hits and now - hits[0] > self.window:
            hits.popleft()

        if not hits:
            del self._hits[key]
            return None

        return hits

    def is_blocked(self, key):
        with self._lock:
            hits = self._prune(key, time.monotonic())
            return bool(hits) and len(hits) >= self.max_failures

    def register_failure(self, key):
        now = time.monotonic()

        with self._lock:
            hits = self._prune(key, now)

            if hits is None:
                hits = self._hits.setdefault(key, deque())

            hits.append(now)

    def reset(self, key):
        with self._lock:
            self._hits.pop(key, None)

    def clear(self):
        with self._lock:
            self._hits.clear()


limiter = AttemptLimiter()


# =========================================================
# PENYIMPANAN
# =========================================================

def _duplicate_field(exc):
    """Tebak kolom yang bentrok dari pesan MySQL 1062."""

    message = str(exc).lower()

    for field in ("student_code", "username", "email"):
        if field in message:
            return field

    return None


def create_account(clean):
    """
    Simpan akun baru dan kembalikan ``user_id``.

    Hash bcrypt dibuat di sini (mahal), sehingga hanya dipanggil setelah
    kode akses dan seluruh validasi lolos. Keunikan dijaga oleh constraint
    UNIQUE di database, bukan pemeriksaan SELECT yang rawan balapan.
    """

    password_hash = bcrypt.hashpw(
        clean["password"].encode("utf-8"),
        bcrypt.gensalt(rounds=12),
    ).decode("utf-8")

    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO users (
                student_code,
                full_name,
                username,
                email,
                password_hash
            )
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                clean["student_code"],
                clean["full_name"],
                clean["username"],
                clean["email"],
                password_hash,
            ),
        )

        conn.commit()

        return cur.lastrowid

    except mysql.connector.IntegrityError as exc:
        if conn:
            conn.rollback()

        raise DuplicateAccountError(_duplicate_field(exc)) from exc

    except Exception:
        if conn:
            conn.rollback()

        raise

    finally:
        if cur is not None:
            cur.close()

        if conn is not None:
            conn.close()