"""
Tes fitur pembuatan akun (form tersembunyi Alt + F1 + U).

Seperti tes Fase 1, tidak ada koneksi database sungguhan. Tes ini TIDAK
menguji JavaScript (shortcut keyboard) dan TIDAK membuktikan INSERT berjalan
pada MySQL sungguhan; keduanya perlu uji manual / integrasi.

Menjalankan (root proyek, venv aktif):

    python -m unittest tests.test_account_provisioning -v
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import support  # noqa: F401  (menyiapkan environment tes)
from tests.support import (
    FakeConnection,
    FakeCursor,
    make_app,
    patch_db,
    total_calls,
)

ACCESS_CODE = "kode-akses-operator-2026"


def valid_form(**overrides):
    data = {
        "student_code": "2026-0042",
        "full_name": "Ni Luh Putu Ayu",
        "username": "putu.ayu",
        "email": "Putu.Ayu@Contoh.com",
        "password": "sandi-aman-sekali-123",
        "confirm_password": "sandi-aman-sekali-123",
        "access_code": ACCESS_CODE,
    }
    data.update(overrides)
    return data


def make_provisioning_app(enabled=True, code=ACCESS_CODE, csrf=False):
    from config import Config

    with mock.patch.object(Config, "ACCOUNT_PROVISIONING_ENABLED", enabled), \
            mock.patch.object(Config, "PROVISIONING_ACCESS_CODE", code):
        return make_app(csrf=csrf)


class DuplicateCursor(FakeCursor):
    """Kursor yang melempar IntegrityError (MySQL 1062) saat INSERT."""

    def __init__(self, message):
        super().__init__()
        self.message = message

    def execute(self, sql, params=None):
        import mysql.connector

        super().execute(sql, params)
        raise mysql.connector.IntegrityError(self.message)


# =========================================================
# KONFIGURASI
# =========================================================

class ProvisioningConfigTests(unittest.TestCase):

    def setUp(self):
        from config import Config

        self.Config = Config
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)

        patcher = mock.patch.object(
            Config, "UPLOAD_FOLDER", Path(tmp.name) / "uploads"
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _validate(self, enabled, code):
        with mock.patch.object(
            self.Config, "ACCOUNT_PROVISIONING_ENABLED", enabled
        ), mock.patch.object(self.Config, "PROVISIONING_ACCESS_CODE", code):
            self.Config.validate()

    def test_mati_tidak_butuh_kode_akses(self):
        self._validate(False, "")

    def test_aktif_dengan_kode_valid_lolos(self):
        self._validate(True, ACCESS_CODE)

    def test_aktif_dengan_kode_pendek_ditolak(self):
        with self.assertRaises(RuntimeError) as ctx:
            self._validate(True, "pendek")

        self.assertIn("PROVISIONING_ACCESS_CODE", str(ctx.exception))

    def test_aktif_tanpa_kode_ditolak(self):
        with self.assertRaises(RuntimeError):
            self._validate(True, "")

    def test_kode_tidak_boleh_sama_dengan_secret_key(self):
        with self.assertRaises(RuntimeError):
            self._validate(True, self.Config.SECRET_KEY)

    def test_kode_tidak_boleh_sama_dengan_api_key(self):
        with self.assertRaises(RuntimeError):
            self._validate(True, self.Config.SHARED_API_KEY)


# =========================================================
# VALIDASI (fungsi murni)
# =========================================================

class ValidateNewAccountTests(unittest.TestCase):

    def _validate(self, **overrides):
        from app.services.account_service import validate_new_account

        return validate_new_account(valid_form(**overrides))

    def test_data_valid_dinormalisasi(self):
        clean, errors = self._validate(
            username="  Putu.Ayu ", full_name="  Ni   Luh  Putu "
        )

        self.assertEqual(errors, {})
        self.assertEqual(clean["username"], "putu.ayu")
        self.assertEqual(clean["email"], "putu.ayu@contoh.com")
        self.assertEqual(clean["full_name"], "Ni Luh Putu")

    def test_nama_yang_wajar_diterima(self):
        for name in (
            "Muhammad Rizky A. P.",
            "Ni Luh Putu Ayu D'Angelo",
            "Siti Nur-Haliza",
            "Zoë Müller",
        ):
            with self.subTest(name=name):
                self.assertNotIn("full_name", self._validate(full_name=name)[1])

    def test_nama_dengan_markup_atau_angka_ditolak(self):
        for name in ("Budi<script>", "Budi & Co", "Budi 2", "=cmd", "A", ""):
            with self.subTest(name=name):
                self.assertIn("full_name", self._validate(full_name=name)[1])

    def test_username_tidak_boleh_memuat_at(self):
        # Login memakai "username = ? OR email = ?"; username berisi "@"
        # dapat meniru email orang lain.
        _, errors = self._validate(username="korban@contoh.com")
        self.assertIn("username", errors)

    def test_student_code_tidak_boleh_memuat_slash(self):
        # Dipakai sebagai segmen URL /api/students/<string:student_code>/...
        _, errors = self._validate(student_code="2026/0042")
        self.assertIn("student_code", errors)

    def test_password_pendek_ditolak(self):
        _, errors = self._validate(password="pendek", confirm_password="pendek")
        self.assertIn("password", errors)

    def test_password_lebih_dari_72_byte_ditolak(self):
        long_pw = "é" * 40  # 80 byte, 40 karakter
        _, errors = self._validate(password=long_pw, confirm_password=long_pw)
        self.assertIn("password", errors)

    def test_password_memuat_username_ditolak(self):
        pw = "xx-putu.ayu-xx-123"
        _, errors = self._validate(password=pw, confirm_password=pw)
        self.assertIn("password", errors)

    def test_konfirmasi_tidak_cocok_ditolak(self):
        _, errors = self._validate(confirm_password="beda-sekali-123456")
        self.assertIn("confirm_password", errors)

    def test_email_tidak_valid_ditolak(self):
        for email in ("tanpa-at", "a@b", "a b@c.com", "a@@c.com"):
            with self.subTest(email=email):
                self.assertIn("email", self._validate(email=email)[1])


class AttemptLimiterTests(unittest.TestCase):

    def test_blokir_setelah_batas_dan_reset(self):
        from app.services.account_service import AttemptLimiter

        limiter = AttemptLimiter(max_failures=3, window_seconds=60)

        for _ in range(2):
            limiter.register_failure("1.2.3.4")

        self.assertFalse(limiter.is_blocked("1.2.3.4"))

        limiter.register_failure("1.2.3.4")

        self.assertTrue(limiter.is_blocked("1.2.3.4"))
        self.assertFalse(limiter.is_blocked("5.6.7.8"))

        limiter.reset("1.2.3.4")
        self.assertFalse(limiter.is_blocked("1.2.3.4"))

    def test_kegagalan_kedaluwarsa_setelah_jendela(self):
        from app.services.account_service import AttemptLimiter

        limiter = AttemptLimiter(max_failures=1, window_seconds=60)

        with mock.patch("app.services.account_service.time.monotonic") as clock:
            clock.return_value = 1000.0
            limiter.register_failure("ip")
            self.assertTrue(limiter.is_blocked("ip"))

            clock.return_value = 1061.0
            self.assertFalse(limiter.is_blocked("ip"))


# =========================================================
# ROUTE: FITUR MATI
# =========================================================

class ProvisioningDisabledTests(unittest.TestCase):

    def setUp(self):
        self.app = make_provisioning_app(enabled=False, code="")
        self.client = self.app.test_client()

    def test_route_404_dan_db_tidak_disentuh(self):
        with patch_db() as mocks:
            response = self.client.post(
                "/login/create-account", data=valid_form()
            )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(total_calls(mocks), 0)

    def test_halaman_login_tanpa_jejak_fitur(self):
        html = self.client.get("/login").get_data(as_text=True)

        self.assertNotIn("provision", html)
        self.assertNotIn("create-account", html)


# =========================================================
# ROUTE: FITUR AKTIF
# =========================================================

class ProvisioningRouteTests(unittest.TestCase):

    def setUp(self):
        from app.services.account_service import limiter

        limiter.clear()
        self.addCleanup(limiter.clear)

        self.app = make_provisioning_app()
        self.client = self.app.test_client()

    def _post(self, **overrides):
        return self.client.post("/login/create-account", data=valid_form(**overrides))

    def test_login_memuat_dialog_script_dan_css(self):
        html = self.client.get("/login").get_data(as_text=True)

        self.assertIn("data-provision-dialog", html)
        self.assertIn("js/provision.js", html)
        self.assertIn("css/provision.css", html)
        self.assertIn('name="csrf_token"', html)
        self.assertNotIn(ACCESS_CODE, html)
        self.assertNotIn("data-open-on-load", html)

    # ---- kode akses ----

    def test_kode_akses_salah_ditolak_tanpa_db(self):
        with patch_db() as mocks:
            response = self._post(access_code="tebakan-salah")

        self.assertEqual(response.status_code, 403)
        self.assertIn("Kode akses tidak valid", response.get_data(as_text=True))
        self.assertEqual(total_calls(mocks), 0)

    def test_kode_akses_kosong_ditolak(self):
        with patch_db() as mocks:
            response = self._post(access_code="")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(total_calls(mocks), 0)

    def test_percobaan_berulang_diblokir_walau_kode_benar(self):
        with patch_db() as mocks:
            for _ in range(5):
                self.assertEqual(self._post(access_code="salah").status_code, 403)

            response = self._post()  # kode benar, tetapi sudah diblokir

        self.assertEqual(response.status_code, 429)
        self.assertEqual(total_calls(mocks), 0)

    # ---- validasi ----

    def test_validasi_gagal_menampilkan_dialog_tanpa_mengisi_ulang_sandi(self):
        with patch_db() as mocks:
            response = self._post(
                email="bukan-email", password="rahasia-panjang-xyz-1",
                confirm_password="rahasia-panjang-xyz-1",
            )

        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(total_calls(mocks), 0)
        self.assertIn("data-open-on-load", html)
        self.assertIn("Format email tidak valid", html)
        self.assertIn("putu.ayu", html)                    # kolom lain dipertahankan
        self.assertNotIn("rahasia-panjang-xyz-1", html)    # sandi tidak dikembalikan
        self.assertNotIn(ACCESS_CODE, html)                # kode akses tidak dikembalikan

    def test_nilai_pengguna_di_html_di_escape(self):
        with patch_db():
            response = self._post(full_name='"><script>alert(1)</script>')

        html = response.get_data(as_text=True)

        self.assertNotIn("<script>alert(1)</script>", html)

    # ---- berhasil ----

    def test_berhasil_menyimpan_hash_dan_mengarahkan_ke_login(self):
        import bcrypt

        cursor = FakeCursor()
        cursor.lastrowid = 99
        conn = FakeConnection(cursor)

        with patch_db(connection=conn):
            response = self._post()

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/login"))

        self.assertEqual(len(cursor.executed), 1)
        sql, params = cursor.executed[0]

        self.assertIn("INSERT INTO users", sql)
        self.assertNotIn("putu.ayu", sql)  # nilai lewat parameter, bukan SQL

        student_code, full_name, username, email, password_hash = params

        self.assertEqual(student_code, "2026-0042")
        self.assertEqual(full_name, "Ni Luh Putu Ayu")
        self.assertEqual(username, "putu.ayu")
        self.assertEqual(email, "putu.ayu@contoh.com")
        self.assertNotEqual(password_hash, "sandi-aman-sekali-123")
        self.assertTrue(
            bcrypt.checkpw(b"sandi-aman-sekali-123", password_hash.encode("utf-8"))
        )

        self.assertTrue(conn.committed)
        self.assertTrue(conn.closed)
        self.assertTrue(cursor.closed)

    def test_berhasil_tidak_login_otomatis_dan_menampilkan_pesan(self):
        cursor = FakeCursor()
        cursor.lastrowid = 5

        with patch_db(connection=FakeConnection(cursor)):
            response = self._post()

        self.assertEqual(response.status_code, 302)

        with self.client.session_transaction() as sess:
            self.assertNotIn("user_id", sess)

        page = self.client.get(response.headers["Location"])

        self.assertIn("berhasil dibuat", page.get_data(as_text=True))

    # ---- duplikat & gangguan ----

    def test_duplikat_username_memberi_pesan_spesifik(self):
        cursor = DuplicateCursor(
            "1062 (23000): Duplicate entry 'putu.ayu' for key 'users.username'"
        )
        conn = FakeConnection(cursor)

        with patch_db(connection=conn):
            response = self._post()

        self.assertEqual(response.status_code, 409)
        self.assertIn("Username sudah digunakan", response.get_data(as_text=True))
        self.assertTrue(conn.rolled_back)
        self.assertFalse(conn.committed)
        self.assertTrue(conn.closed)

    def test_duplikat_tanpa_nama_kolom_memberi_pesan_umum(self):
        conn = FakeConnection(DuplicateCursor("1062 (23000): Duplicate entry"))

        with patch_db(connection=conn):
            response = self._post()

        self.assertEqual(response.status_code, 409)
        self.assertIn("sudah digunakan", response.get_data(as_text=True))

    def test_database_mati_memberi_pesan_umum(self):
        with patch_db(error=RuntimeError("detail internal rahasia")):
            response = self._post()

        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 503)
        self.assertIn("gangguan", html)
        self.assertNotIn("detail internal rahasia", html)

    def test_pengguna_yang_sudah_login_diarahkan_tanpa_menyentuh_db(self):
        with self.client.session_transaction() as sess:
            sess["user_id"] = 7

        with patch_db() as mocks:
            response = self._post()

        self.assertEqual(response.status_code, 302)
        self.assertIn("/dashboard", response.headers["Location"])
        self.assertEqual(total_calls(mocks), 0)

    def test_get_tidak_diizinkan(self):
        self.assertEqual(self.client.get("/login/create-account").status_code, 405)


class ProvisioningCsrfTests(unittest.TestCase):

    def test_tanpa_token_csrf_ditolak_tanpa_db(self):
        from app.services.account_service import limiter

        limiter.clear()

        app = make_provisioning_app(csrf=True)
        client = app.test_client()

        with patch_db() as mocks:
            response = client.post("/login/create-account", data=valid_form())

        self.assertEqual(response.status_code, 400)
        self.assertEqual(total_calls(mocks), 0)


if __name__ == "__main__":
    unittest.main()