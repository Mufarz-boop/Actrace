"""
Tes baseline Fase 1 ACTRACE.

Cakupan: konfigurasi, route khusus pengembangan, halaman error,
header keamanan, gerbang autentikasi, perilaku login/logout, dan
autentikasi API key. Semua tanpa database sungguhan.

Menjalankan (dari root proyek, dengan venv aktif):

    python -m unittest discover -s tests -t . -v
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import support
from tests.support import (
    FakeConnection,
    FakeCursor,
    make_app,
    make_student_row,
    patch_db,
    total_calls,
)


DEV_ONLY_PATHS = (
    "/test-error/403",
    "/test-error/404",
    "/test-error/500",
)


# =========================================================
# KONFIGURASI
# =========================================================

class ConfigValidationTests(unittest.TestCase):

    def setUp(self):
        from config import Config

        self.Config = Config
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

        # Jangan menyentuh folder upload proyek sungguhan.
        patcher = mock.patch.object(
            Config, "UPLOAD_FOLDER", Path(self._tmp.name) / "uploads"
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_konfigurasi_valid_lolos(self):
        self.Config.validate()  # tidak boleh melempar

    def test_secret_key_pendek_ditolak(self):
        with mock.patch.object(self.Config, "SECRET_KEY", "pendek"):
            with self.assertRaises(RuntimeError) as ctx:
                self.Config.validate()
        self.assertIn("SECRET_KEY", str(ctx.exception))

    def test_api_key_kosong_ditolak(self):
        with mock.patch.object(self.Config, "SHARED_API_KEY", ""):
            with self.assertRaises(RuntimeError) as ctx:
                self.Config.validate()
        self.assertIn("SHARED_API_KEY", str(ctx.exception))

    def test_api_key_tidak_boleh_sama_dengan_secret_key(self):
        same = "z" * 48
        with mock.patch.object(self.Config, "SECRET_KEY", same), \
                mock.patch.object(self.Config, "SHARED_API_KEY", same):
            with self.assertRaises(RuntimeError) as ctx:
                self.Config.validate()
        self.assertIn("berbeda", str(ctx.exception))

    def test_api_key_dengan_spasi_ditolak(self):
        with mock.patch.object(
            self.Config, "SHARED_API_KEY", "a" * 20 + " " + "b" * 20
        ):
            with self.assertRaises(RuntimeError):
                self.Config.validate()


# =========================================================
# ROUTE KHUSUS PENGEMBANGAN
# =========================================================

class DevOnlyRoutesTests(unittest.TestCase):

    def test_tidak_terdaftar_saat_debug_mati(self):
        app = make_app(debug=False)
        rules = {r.rule for r in app.url_map.iter_rules()}

        for path in DEV_ONLY_PATHS:
            self.assertNotIn(path, rules)

    def test_tidak_dapat_diakses_saat_debug_mati(self):
        client = make_app(debug=False).test_client()

        for path in DEV_ONLY_PATHS:
            with self.subTest(path=path):
                self.assertEqual(client.get(path).status_code, 404)

    def test_tersedia_saat_debug_aktif(self):
        app = make_app(debug=True)
        client = app.test_client()

        self.assertEqual(client.get("/test-error/403").status_code, 403)
        self.assertEqual(client.get("/test-error/404").status_code, 404)

        with self.assertLogs(app.logger, level="ERROR"):
            self.assertEqual(
                client.get("/test-error/500").status_code, 500
            )


# =========================================================
# HALAMAN ERROR
# =========================================================

class ErrorPageTests(unittest.TestCase):

    def test_404_menampilkan_halaman_html(self):
        response = make_app().test_client().get("/halaman-tidak-ada")

        self.assertEqual(response.status_code, 404)
        self.assertIn("text/html", response.content_type)
        self.assertTrue(response.get_data())

    def test_500_tidak_membocorkan_detail_exception(self):
        app = make_app()
        secret_marker = "RAHASIA-INTERNAL-12345"

        @app.get("/__boom")
        def boom():
            raise RuntimeError(secret_marker)

        with self.assertLogs(app.logger, level="ERROR"):
            response = app.test_client().get("/__boom")

        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 500)
        self.assertNotIn(secret_marker, body)
        self.assertNotIn("Traceback", body)


# =========================================================
# HEADER KEAMANAN
# =========================================================

class SecurityHeaderTests(unittest.TestCase):

    EXPECTED = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "strict-origin-when-cross-origin",
    }

    def _assert_headers(self, response):
        for name, value in self.EXPECTED.items():
            self.assertEqual(response.headers.get(name), value, name)

        self.assertIn(
            "camera=()", response.headers.get("Permissions-Policy", "")
        )

    def test_header_pada_halaman_login(self):
        self._assert_headers(make_app().test_client().get("/login"))

    def test_header_pada_respons_error(self):
        self._assert_headers(make_app().test_client().get("/tidak-ada"))


# =========================================================
# GERBANG AUTENTIKASI
# =========================================================

class AuthenticationGateTests(unittest.TestCase):

    def _student_requests(self, app):
        """Hasilkan (method, path) untuk setiap route siswa."""

        found = []

        for rule in app.url_map.iter_rules():
            if not rule.endpoint.startswith("student."):
                continue

            built = rule.build({arg: 1 for arg in rule.arguments})
            self.assertIsNotNone(built, rule.rule)
            path = built[1]

            for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
                found.append((method, path))

        return found

    def test_semua_route_siswa_menolak_tamu_sebelum_menyentuh_db(self):
        app = make_app(csrf=False)
        client = app.test_client()
        requests = self._student_requests(app)

        # Cegah tes kosong bila route berubah tanpa sengaja.
        self.assertGreaterEqual(len(requests), 15)

        with patch_db() as mocks:
            for method, path in requests:
                with self.subTest(method=method, path=path):
                    response = client.open(path, method=method)

                    self.assertEqual(response.status_code, 302)
                    self.assertIn(
                        "/login", response.headers["Location"]
                    )

            self.assertEqual(total_calls(mocks), 0)

    def test_root_mengarahkan_tamu_ke_login(self):
        response = make_app().test_client().get("/")

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_root_mengarahkan_pengguna_login_ke_dashboard(self):
        client = make_app().test_client()

        with client.session_transaction() as sess:
            sess["user_id"] = 7

        response = client.get("/")

        self.assertEqual(response.status_code, 302)
        self.assertIn("/student/dashboard", response.headers["Location"])


# =========================================================
# LOGIN & LOGOUT
# =========================================================

class LoginBehaviourTests(unittest.TestCase):

    def setUp(self):
        self.app = make_app(csrf=False)
        self.client = self.app.test_client()

    def _post_login(self, identity="siswa", password="correct-password"):
        return self.client.post(
            "/login", data={"identity": identity, "password": password}
        )

    def _session(self):
        with self.client.session_transaction() as sess:
            return dict(sess)

    def test_field_kosong_ditolak_tanpa_akses_db(self):
        with patch_db() as mocks:
            response = self._post_login(identity="", password="")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(total_calls(mocks), 0)
        self.assertNotIn("user_id", self._session())

    def test_login_berhasil_membuat_sesi_dan_menutup_koneksi(self):
        cursor = FakeCursor(fetchone=[make_student_row()])
        conn = FakeConnection(cursor)

        with patch_db(connection=conn):
            response = self._post_login()

        self.assertEqual(response.status_code, 302)
        self.assertIn("/student/dashboard", response.headers["Location"])

        sess = self._session()
        self.assertEqual(sess["user_id"], 7)
        self.assertEqual(sess["student_code"], "S-0007")
        self.assertEqual(sess["full_name"], "Siswa Uji")
        self.assertNotIn("password_hash", sess)

        self.assertTrue(conn.closed)
        self.assertTrue(cursor.closed)

    def test_password_salah_ditolak(self):
        conn = FakeConnection(FakeCursor(fetchone=[make_student_row()]))

        with patch_db(connection=conn):
            response = self._post_login(password="salah")

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "Identitas atau kata sandi tidak sesuai",
            response.get_data(as_text=True),
        )
        self.assertNotIn("user_id", self._session())

    def test_pengguna_tidak_ada_memberi_pesan_yang_sama(self):
        wrong_pw = FakeConnection(FakeCursor(fetchone=[make_student_row()]))
        no_user = FakeConnection(FakeCursor(fetchone=[]))

        with patch_db(connection=wrong_pw):
            body_wrong = self._post_login(password="salah").get_data(
                as_text=True
            )

        with patch_db(connection=no_user):
            body_missing = self._post_login(identity="hantu").get_data(
                as_text=True
            )

        message = "Identitas atau kata sandi tidak sesuai"
        self.assertIn(message, body_wrong)
        self.assertIn(message, body_missing)

    def test_input_dikirim_sebagai_parameter_bukan_dirangkai_ke_sql(self):
        payload = "' OR '1'='1' --"
        cursor = FakeCursor(fetchone=[])

        with patch_db(connection=FakeConnection(cursor)):
            self._post_login(identity=payload)

        sql, params = cursor.executed[0]

        self.assertNotIn(payload, sql)
        self.assertEqual(params, (payload, payload))

    def test_database_mati_menampilkan_pesan_umum(self):
        with patch_db(error=RuntimeError("Database ACTRACE tidak tersedia.")):
            # Kegagalan DB harus tercatat di log server (bukan ke pengguna).
            with self.assertLogs(self.app.logger, level="ERROR"):
                response = self._post_login()

        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Layanan sedang mengalami gangguan", body)
        self.assertNotIn("tidak tersedia.", body)
        self.assertNotIn("user_id", self._session())

    def test_login_membersihkan_data_sesi_lama(self):
        with self.client.session_transaction() as sess:
            sess["sisa_sesi_lama"] = "x"

        conn = FakeConnection(FakeCursor(fetchone=[make_student_row()]))

        with patch_db(connection=conn):
            self._post_login()

        sess = self._session()
        self.assertNotIn("sisa_sesi_lama", sess)
        self.assertIn("user_id", sess)


class LogoutTests(unittest.TestCase):

    def test_logout_via_get_tidak_diizinkan(self):
        response = make_app().test_client().get("/logout")

        self.assertEqual(response.status_code, 405)

    def test_logout_tanpa_token_csrf_ditolak_dan_sesi_tetap(self):
        client = make_app(csrf=True).test_client()

        with client.session_transaction() as sess:
            sess["user_id"] = 7

        response = client.post("/logout")

        self.assertEqual(response.status_code, 400)

        with client.session_transaction() as sess:
            self.assertEqual(sess.get("user_id"), 7)

    def test_logout_menghapus_sesi(self):
        client = make_app(csrf=False).test_client()

        with client.session_transaction() as sess:
            sess["user_id"] = 7
            sess["student_code"] = "S-0007"

        response = client.post("/logout")

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

        with client.session_transaction() as sess:
            self.assertNotIn("user_id", sess)
            self.assertNotIn("student_code", sess)


# =========================================================
# API & API KEY
# =========================================================

class ApiTests(unittest.TestCase):

    KEY = {"X-API-Key": support.TEST_API_KEY}
    PROTECTED = (
        "/api/students/S-0007/summary",
        "/api/students/S-0007/journals",
    )

    def setUp(self):
        self.app = make_app()
        self.client = self.app.test_client()

    def test_health_database_tersedia(self):
        conn = FakeConnection()

        with patch_db(connection=conn):
            response = self.client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {
                "success": True,
                "service": "ACTRACE",
                "database": "connected",
            },
        )
        self.assertTrue(conn.closed)

    def test_health_database_mati_memberi_503_tanpa_detail(self):
        with patch_db(error=RuntimeError("detail internal host=10.0.0.5")):
            response = self.client.get("/api/health")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["database"], "unavailable")
        self.assertNotIn("10.0.0.5", response.get_data(as_text=True))

    def test_endpoint_terlindungi_menolak_tanpa_key(self):
        with patch_db() as mocks:
            for path in self.PROTECTED:
                with self.subTest(path=path):
                    self.assertEqual(self.client.get(path).status_code, 401)

            self.assertEqual(total_calls(mocks), 0)

    def test_endpoint_terlindungi_menolak_key_salah(self):
        with patch_db() as mocks:
            for path in self.PROTECTED:
                with self.subTest(path=path):
                    response = self.client.get(
                        path, headers={"X-API-Key": "salah"}
                    )
                    self.assertEqual(response.status_code, 401)

            self.assertEqual(total_calls(mocks), 0)

    def test_key_lewat_query_string_tidak_diterima(self):
        with patch_db() as mocks:
            response = self.client.get(
                f"{self.PROTECTED[0]}?api_key={support.TEST_API_KEY}"
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(total_calls(mocks), 0)

    def test_api_belum_dikonfigurasi_memberi_503(self):
        self.app.config["SHARED_API_KEY"] = ""

        with patch_db() as mocks:
            for path in self.PROTECTED:
                with self.subTest(path=path):
                    response = self.client.get(path, headers=self.KEY)
                    self.assertEqual(response.status_code, 503)

            self.assertEqual(total_calls(mocks), 0)

    def test_summary_siswa_tidak_ditemukan(self):
        conn = FakeConnection(FakeCursor(fetchone=[]))

        with patch_db(connection=conn):
            response = self.client.get(
                self.PROTECTED[0], headers=self.KEY
            )

        self.assertEqual(response.status_code, 404)
        self.assertTrue(conn.closed)

    def test_summary_berhasil_dan_menutup_koneksi(self):
        cursor = FakeCursor(
            fetchone=[
                {
                    "user_id": 7,
                    "student_code": "S-0007",
                    "full_name": "Siswa Uji",
                },
                {"total": 3},
                {"activity_date": support.today(), "title": "Judul"},
            ]
        )
        conn = FakeConnection(cursor)

        with patch_db(connection=conn):
            response = self.client.get(
                self.PROTECTED[0], headers=self.KEY
            )

        data = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(data["success"])
        self.assertEqual(data["total_journals"], 3)
        self.assertEqual(
            data["latest_activity"],
            {"activity_date": "2026-11-11", "title": "Judul"},
        )
        self.assertTrue(conn.closed)
        self.assertTrue(cursor.closed)

    def test_student_code_dikirim_sebagai_parameter(self):
        payload = "x'; DROP TABLE users;--"
        cursor = FakeCursor(fetchone=[])

        with patch_db(connection=FakeConnection(cursor)):
            response = self.client.get(
                f"/api/students/{payload}/summary", headers=self.KEY
            )

        sql, params = cursor.executed[0]

        self.assertEqual(response.status_code, 404)
        self.assertNotIn("DROP TABLE", sql)
        self.assertEqual(params, (payload,))


if __name__ == "__main__":
    unittest.main()
