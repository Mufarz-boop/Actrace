"""
Utilitas bersama untuk pengujian ACTRACE.

Prinsip:
- Tes TIDAK pernah terhubung ke database sungguhan. Semua pemanggilan
  ``get_db_connection`` diganti dengan tiruan (lihat ``patch_db``).
- Konfigurasi diisi dari environment tes SEBELUM ``config`` diimpor,
  sehingga nilai pada file ``.env`` asli tidak dipakai (python-dotenv
  tidak menimpa variabel yang sudah ada).
- ``bcrypt`` dan ``mysql.connector`` dipakai apa adanya bila terpasang.
  Pengganti sederhana HANYA dipasang bila paket tersebut tidak dapat
  diimpor (mis. lingkungan sandbox tanpa wheel yang sesuai), dan
  peringatan dicetak ke stderr agar tidak tersamar.
"""

import datetime
import os
import sys
import types
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------
# Environment tes (harus diset sebelum `import config`)
# ---------------------------------------------------------

TEST_SECRET_KEY = "s" * 48
TEST_API_KEY = "k" * 48

os.environ.update(
    {
        "APP_NAME": "ACTRACE-TEST",
        "DEBUG": "false",
        "SECRET_KEY": TEST_SECRET_KEY,
        "SHARED_API_KEY": TEST_API_KEY,
        "DB_HOST": "127.0.0.1",
        "DB_PORT": "3306",
        "DB_USER": "test_user",
        "DB_PASSWORD": "test_password",
        "DB_NAME": "db_actrace_test",
        "SESSION_COOKIE_SECURE": "false",
    }
)


# ---------------------------------------------------------
# Fallback dependensi yang tidak terpasang
# ---------------------------------------------------------

STUBBED_DEPENDENCIES = []


def _install_missing_dependency_stubs():

    try:
        import bcrypt  # noqa: F401
    except ImportError:
        stub = types.ModuleType("bcrypt")
        stub.gensalt = lambda *a, **k: b""
        stub.hashpw = lambda password, salt: b"stub-hash:" + password
        stub.checkpw = lambda password, hashed: (
            hashed == b"stub-hash:" + password
        )
        sys.modules["bcrypt"] = stub
        STUBBED_DEPENDENCIES.append("bcrypt")

    try:
        import mysql.connector  # noqa: F401
    except ImportError:
        connector = types.ModuleType("mysql.connector")

        class Error(Exception):
            pass

        class DatabaseError(Error):
            pass

        class IntegrityError(DatabaseError):
            pass

        def connect(**kwargs):
            raise Error("Tes tidak boleh membuka koneksi database.")

        connector.Error = Error
        connector.DatabaseError = DatabaseError
        connector.IntegrityError = IntegrityError
        connector.connect = connect

        package = types.ModuleType("mysql")
        package.connector = connector

        sys.modules["mysql"] = package
        sys.modules["mysql.connector"] = connector
        STUBBED_DEPENDENCIES.append("mysql.connector")


_install_missing_dependency_stubs()

if STUBBED_DEPENDENCIES:
    print(
        "[tests] PERINGATAN: dependensi berikut tidak terpasang dan "
        "diganti stub: " + ", ".join(STUBBED_DEPENDENCIES),
        file=sys.stderr,
    )


# ---------------------------------------------------------
# Database tiruan
# ---------------------------------------------------------

class FakeCursor:
    """Kursor tiruan: mengembalikan baris yang sudah disiapkan berurutan."""

    def __init__(self, fetchone=(), fetchall=()):
        self._fetchone = list(fetchone)
        self._fetchall = list(fetchall)
        self.executed = []
        self.closed = False
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        return self._fetchone.pop(0) if self._fetchone else None

    def fetchall(self):
        return self._fetchall.pop(0) if self._fetchall else []

    def close(self):
        self.closed = True


class FakeConnection:
    """Koneksi tiruan yang mencatat apakah sudah ditutup."""

    def __init__(self, cursor=None):
        self._cursor = cursor or FakeCursor()
        self.closed = False
        self.committed = False
        self.rolled_back = False

    def cursor(self, *args, **kwargs):
        return self._cursor

    def start_transaction(self):
        pass

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


_DB_MODULES = (
    "app.db",
    "app.auth.routes",
    "app.api.routes",
    "app.student.routes",
    "app.services.journal_service",
    "app.services.photo_service",
    "app.services.pdf_service",
)


@contextmanager
def patch_db(connection=None, error=None):
    """
    Ganti ``get_db_connection`` di semua modul yang memakainya.

    - ``connection``: objek yang dikembalikan (mis. ``FakeConnection``).
    - ``error``: exception yang dilempar (mis. ``RuntimeError``).
    - Tanpa argumen: setiap akses DB melempar AssertionError sehingga
      tes dapat memastikan DB tidak disentuh (cek ``call_count``).

    Mengembalikan list mock agar pemanggil bisa memeriksa ``call_count``
    gabungan lewat ``total_calls``.
    """

    import importlib

    mocks = []

    with ExitStack() as stack:
        for name in _DB_MODULES:
            module = importlib.import_module(name)

            if not hasattr(module, "get_db_connection"):
                continue

            if connection is not None:
                m = mock.patch.object(
                    module, "get_db_connection", return_value=connection
                )
            elif error is not None:
                m = mock.patch.object(
                    module, "get_db_connection", side_effect=error
                )
            else:
                m = mock.patch.object(
                    module,
                    "get_db_connection",
                    side_effect=AssertionError(
                        "Database tidak boleh diakses pada skenario ini."
                    ),
                )

            mocks.append(stack.enter_context(m))

        yield mocks


def total_calls(mocks):
    return sum(m.call_count for m in mocks)


# ---------------------------------------------------------
# Factory aplikasi
# ---------------------------------------------------------

def make_app(debug=False, csrf=True):
    """Buat instans aplikasi baru yang terisolasi untuk satu tes."""

    from app import create_app
    from config import Config

    with mock.patch.object(Config, "DEBUG", debug):
        app = create_app()

    app.config["WTF_CSRF_ENABLED"] = csrf

    # Agar handler 500 dijalankan (bukan exception dilempar ke test client)
    app.config["PROPAGATE_EXCEPTIONS"] = False

    return app


def make_student_row(password=b"correct-password", **overrides):
    """Baris ``users`` tiruan dengan hash bcrypt (cost rendah agar cepat)."""

    import bcrypt

    row = {
        "user_id": 7,
        "student_code": "S-0007",
        "full_name": "Siswa Uji",
        "password_hash": bcrypt.hashpw(
            password, bcrypt.gensalt(rounds=4)
        ).decode("utf-8"),
    }
    row.update(overrides)
    return row


def today():
    return datetime.date(2026, 11, 11)
