"""
Tes Tahap B ACTRACE: statistik bersama, konstanta terpusat, halaman error.

Semua tanpa database sungguhan (database tiruan). Hasilnya tidak
membuktikan perilaku pada MySQL asli.

    python -m unittest discover -s tests -t . -v
"""

import io
import re
import unittest
from pathlib import Path

from werkzeug.datastructures import FileStorage

# tests.support harus diimpor lebih dulu: ia memasang stub dependensi
# (mysql, bcrypt) sebelum modul app diimpor.
from tests import support
from tests.support import (
    FakeConnection,
    FakeCursor,
    make_app,
    patch_db,
    total_calls,
)

from app import constants
from app.services.journal_service import (
    JournalValidationError,
    validate_journal_data,
)
from app.services.photo_service import (
    PhotoValidationError,
    save_journal_photos,
    validate_photo,
)
from app.services.stats_service import (
    get_student_stats,
    summarize_journal_period,
)


ROOT = Path(__file__).resolve().parent.parent
STATS_MARKER = "COUNT(DISTINCT j.journal_id)"


def stats_row(total=3, photos=2, latest=None, title="Judul"):
    return {
        "total_journals": total,
        "total_photos": photos,
        "latest_activity": latest if latest is not None else support.today(),
        "latest_title": title,
    }


def login(client, user_id=7):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id


def flashed(client):
    with client.session_transaction() as sess:
        return [message for _, message in sess.get("_flashes", [])]


# =========================================================
# STATISTIK
# =========================================================

class StudentStatsTests(unittest.TestCase):

    def test_dengan_cursor_tidak_membuka_koneksi_baru(self):
        cursor = FakeCursor(fetchone=[stats_row()])

        with patch_db() as mocks:
            result = get_student_stats(7, cursor=cursor)

        self.assertEqual(total_calls(mocks), 0)
        self.assertEqual(len(cursor.executed), 1)
        self.assertIn(STATS_MARKER, cursor.executed[0][0])
        self.assertEqual(result["total_journals"], 3)
        self.assertEqual(result["total_photos"], 2)
        self.assertEqual(result["latest_activity"], support.today())
        self.assertEqual(result["latest_title"], "Judul")

    def test_tanpa_cursor_membuka_dan_menutup_koneksi(self):
        cursor = FakeCursor(fetchone=[stats_row()])
        connection = FakeConnection(cursor)

        with patch_db(connection=connection):
            get_student_stats(7)

        self.assertTrue(cursor.closed)
        self.assertTrue(connection.closed)

    def test_koneksi_ditutup_walau_query_gagal(self):
        class BrokenCursor(FakeCursor):
            def execute(self, sql, params=None):
                raise RuntimeError("db error")

        cursor = BrokenCursor()
        connection = FakeConnection(cursor)

        with patch_db(connection=connection):
            with self.assertRaises(RuntimeError):
                get_student_stats(7)

        self.assertTrue(cursor.closed)
        self.assertTrue(connection.closed)

    def test_hanya_memfilter_user_id_yang_diminta(self):
        cursor = FakeCursor(fetchone=[stats_row()])

        get_student_stats(42, cursor=cursor)

        sql, params = cursor.executed[0]

        self.assertEqual(params, (42, 42))
        self.assertEqual(sql.count("user_id = %s"), 2)

    def test_siswa_tanpa_jurnal(self):
        cursor = FakeCursor(
            fetchone=[
                {
                    "total_journals": 0,
                    "total_photos": 0,
                    "latest_activity": None,
                    "latest_title": None,
                }
            ]
        )

        result = get_student_stats(7, cursor=cursor)

        self.assertEqual(result["total_journals"], 0)
        self.assertEqual(result["total_photos"], 0)
        self.assertIsNone(result["latest_activity"])
        self.assertIsNone(result["latest_title"])

    def test_baris_kosong_menghasilkan_nol(self):
        result = get_student_stats(7, cursor=FakeCursor(fetchone=[]))

        self.assertEqual(result["total_journals"], 0)
        self.assertEqual(result["total_photos"], 0)


class JournalPeriodSummaryTests(unittest.TestCase):

    def test_daftar_kosong(self):
        self.assertEqual(
            summarize_journal_period([]),
            {"total_journals": 0, "total_activity_days": 0, "total_photos": 0},
        )

    def test_hari_unik_dan_foto_dari_daftar_photos(self):
        journals = [
            {"activity_date": "2026-11-01", "photos": [1, 2], "photo_count": 2},
            {"activity_date": "2026-11-01", "photos": [], "photo_count": 0},
            {"activity_date": "2026-11-03", "photos": [3], "photo_count": 1},
        ]

        self.assertEqual(
            summarize_journal_period(journals),
            {"total_journals": 3, "total_activity_days": 2, "total_photos": 3},
        )

    def test_fallback_ke_photo_count_bila_photos_kosong(self):
        journals = [
            {"activity_date": "2026-11-01", "photo_count": 2},
            {"activity_date": "2026-11-02", "photo_count": "x"},
        ]

        self.assertEqual(
            summarize_journal_period(journals)["total_photos"], 2
        )

    def test_tanggal_kosong_tidak_dihitung_sebagai_hari(self):
        journals = [{"activity_date": None}, {"activity_date": "2026-11-02"}]

        self.assertEqual(
            summarize_journal_period(journals)["total_activity_days"], 1
        )


class StatsIntegrationTests(unittest.TestCase):

    def setUp(self):
        self.app = make_app(csrf=False)
        self.client = self.app.test_client()
        login(self.client)

    def test_dashboard_satu_query_dan_menutup_koneksi(self):
        cursor = FakeCursor(fetchone=[stats_row(total=5, title="Judul Baru")])
        connection = FakeConnection(cursor)

        with patch_db(connection=connection):
            response = self.client.get("/student/dashboard")

        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(cursor.executed), 1)
        self.assertIn("Judul Baru", html)
        self.assertIn("11-11-2026", html)
        self.assertTrue(connection.closed)
        self.assertTrue(cursor.closed)

    def test_dashboard_siswa_tanpa_jurnal(self):
        row = {
            "total_journals": 0,
            "total_photos": 0,
            "latest_activity": None,
            "latest_title": None,
        }

        with patch_db(connection=FakeConnection(FakeCursor(fetchone=[row]))):
            response = self.client.get("/student/dashboard")

        self.assertEqual(response.status_code, 200)

    def test_profile_menjalankan_query_statistik_sekali(self):
        user = {
            "user_id": 7,
            "student_code": "S-0007",
            "full_name": "Siswa Uji",
            "username": "siswa",
            "email": "siswa@example.test",
            "photo": None,
            "created_at": support.datetime.datetime(2026, 1, 1),
            "updated_at": support.datetime.datetime(2026, 1, 1),
            "school_name": "SMK",
            "class_name": "XII",
            "major": "RPL",
            "academic_year": "2026",
            "internship_company": "PT Uji",
            "internship_industry": "IT",
            "internship_address": "Jl. Uji",
            "supervisor_name": "Pembimbing",
            "supervisor_position": "Manajer",
            "internship_start_date": support.datetime.date(2026, 1, 1),
            "internship_end_date": support.datetime.date(2026, 12, 1),
        }
        cursor = FakeCursor(fetchone=[user, stats_row(total=7, photos=4)])
        connection = FakeConnection(cursor)

        with patch_db(connection=connection):
            response = self.client.get("/student/profile")

        stats_queries = [
            sql for sql, _ in cursor.executed if STATS_MARKER in sql
        ]

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(stats_queries), 1)
        self.assertEqual(len(cursor.executed), 2)
        self.assertIn("11 Nov 2026", response.get_data(as_text=True))
        self.assertTrue(connection.closed)

    def test_api_summary_tanpa_jurnal_mengembalikan_null(self):
        cursor = FakeCursor(
            fetchone=[
                {
                    "user_id": 7,
                    "student_code": "S-0007",
                    "full_name": "Siswa Uji",
                },
                {
                    "total_journals": 0,
                    "total_photos": 0,
                    "latest_activity": None,
                    "latest_title": None,
                },
            ]
        )

        with patch_db(connection=FakeConnection(cursor)):
            response = self.app.test_client().get(
                "/api/students/S-0007/summary",
                headers={"X-API-Key": support.TEST_API_KEY},
            )

        data = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["total_journals"], 0)
        self.assertIsNone(data["latest_activity"])
        self.assertEqual(
            sorted(data),
            ["latest_activity", "student", "success", "total_journals"],
        )

    def test_api_summary_memakai_user_id_siswa_yang_diminta(self):
        cursor = FakeCursor(
            fetchone=[
                {"user_id": 99, "student_code": "S-0099", "full_name": "X"},
                stats_row(),
            ]
        )

        with patch_db(connection=FakeConnection(cursor)):
            self.app.test_client().get(
                "/api/students/S-0099/summary",
                headers={"X-API-Key": support.TEST_API_KEY},
            )

        self.assertEqual(cursor.executed[1][1], (99, 99))


# =========================================================
# KONSTANTA
# =========================================================

class ConstantsTests(unittest.TestCase):

    def test_nilai_batas_tidak_berubah(self):
        self.assertEqual(constants.MAX_PHOTOS_PER_JOURNAL, 5)
        self.assertEqual(constants.MAX_PHOTO_SIZE_MB, 5)
        self.assertEqual(constants.MAX_PHOTO_SIZE_BYTES, 5 * 1024 * 1024)
        self.assertEqual(constants.MAX_JOURNAL_TITLE_LENGTH, 150)
        self.assertEqual(constants.MIN_PASSWORD_LENGTH, 12)
        self.assertEqual(constants.BCRYPT_MAX_PASSWORD_BYTES, 72)

    def test_judul_tepat_150_diterima_151_ditolak(self):
        validate_journal_data("2026-11-01", "a" * 150, "isi")

        with self.assertRaises(JournalValidationError) as ctx:
            validate_journal_data("2026-11-01", "a" * 151, "isi")

        self.assertEqual(str(ctx.exception), "Judul maksimal 150 karakter.")

    def test_foto_melebihi_5_mb_ditolak(self):
        upload = FileStorage(
            stream=io.BytesIO(b"x" * (5 * 1024 * 1024 + 1)),
            filename="besar.jpg",
        )

        with self.assertRaises(PhotoValidationError) as ctx:
            validate_photo(upload)

        self.assertEqual(
            str(ctx.exception), "Ukuran setiap foto maksimal 5 MB."
        )

    def test_foto_tepat_5_mb_lolos_pemeriksaan_ukuran(self):
        upload = FileStorage(
            stream=io.BytesIO(b"x" * (5 * 1024 * 1024)),
            filename="pas.jpg",
        )

        # Isi bukan gambar, jadi tetap ditolak, tetapi bukan karena ukuran.
        with self.assertRaises(PhotoValidationError) as ctx:
            validate_photo(upload)

        self.assertNotIn("maksimal 5 MB", str(ctx.exception))

    def test_lebih_dari_5_foto_ditolak(self):
        files = [
            FileStorage(stream=io.BytesIO(b"x"), filename=f"{i}.jpg")
            for i in range(6)
        ]

        with self.assertRaises(PhotoValidationError) as ctx:
            save_journal_photos(files, journal_id=1)

        self.assertEqual(
            str(ctx.exception), "Maksimal 5 foto untuk setiap jurnal."
        )

    def test_password_11_karakter_ditolak(self):
        client = make_app(csrf=False).test_client()
        login(client)

        with patch_db():
            response = client.post(
                "/student/settings",
                data={
                    "current_password": "lama",
                    "new_password": "a" * 11,
                    "confirm_password": "a" * 11,
                },
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            flashed(client),
            ["Kata sandi baru minimal harus terdiri dari 12 karakter."],
        )

    def test_password_73_byte_ditolak_berdasarkan_byte_bukan_karakter(self):
        client = make_app(csrf=False).test_client()
        login(client)

        # 37 karakter "é" = 74 byte UTF-8, tetapi hanya 37 karakter.
        password = "é" * 37
        self.assertLess(len(password), 72)
        self.assertGreater(len(password.encode("utf-8")), 72)

        with patch_db():
            client.post(
                "/student/settings",
                data={
                    "current_password": "lama",
                    "new_password": password,
                    "confirm_password": password,
                },
            )

        self.assertEqual(
            flashed(client),
            [
                "Kata sandi baru terlalu panjang. "
                "Maksimal 72 byte dalam UTF-8."
            ],
        )

    def test_password_tepat_72_byte_lolos_validasi_batas(self):
        client = make_app(csrf=False).test_client()
        login(client)

        password = "é" * 36
        self.assertEqual(len(password.encode("utf-8")), 72)

        # Lolos validasi ke tahap database (yang sengaja dibuat gagal).
        with patch_db(error=RuntimeError("db mati")):
            client.post(
                "/student/settings",
                data={
                    "current_password": "lama",
                    "new_password": password,
                    "confirm_password": password,
                },
            )

        self.assertEqual(
            flashed(client),
            ["Kata sandi gagal diperbarui karena gangguan database."],
        )

    def test_template_menerima_batas_dari_context_processor(self):
        app = make_app()

        context = {}

        with app.test_request_context():
            app.update_template_context(context)

        self.assertEqual(
            context["app_limits"],
            {
                "max_photos_per_journal": 5,
                "max_photo_size_mb": 5,
                "max_journal_title_length": 150,
                "min_password_length": 12,
                "bcrypt_max_password_bytes": 72,
            },
        )

    def test_form_jurnal_mengirim_batas_ke_javascript(self):
        client = make_app(csrf=False).test_client()
        login(client)

        with patch_db():
            html = client.get("/student/journals/add").get_data(as_text=True)

        self.assertIn('data-max-photos="5"', html)
        self.assertIn('data-max-photo-size-mb="5"', html)
        self.assertIn('data-max-title-length="150"', html)
        self.assertIn('maxlength="150"', html)

    def test_settings_menampilkan_batas_password(self):
        client = make_app(csrf=False).test_client()
        login(client)

        user = {"full_name": "Siswa Uji", "username": "siswa", "student_code": "S-0007"}

        with patch_db(connection=FakeConnection(FakeCursor(fetchone=[user]))):
            response = client.get("/student/settings")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)

        self.assertEqual(html.count('minlength="12"'), 2)
        self.assertEqual(html.count('maxlength="72"'), 2)
        self.assertIn("Minimal 12 karakter dan maksimal 72 byte", html)

    def test_javascript_tidak_menulis_ulang_angka_batas(self):
        forbidden = (
            r"\b5 \* 1024",
            r"/150\b",
            r">= 150",
            r"\b> 5\b",
            r"\b5 foto\b",
            r"\b5 MB\b",
            r"MAX_PHOTOS\s*=\s*5",
        )

        for name in ("journal.js", "edit_journal.js"):
            source = (ROOT / "static" / "js" / name).read_text(encoding="utf-8")

            for pattern in forbidden:
                with self.subTest(file=name, pattern=pattern):
                    self.assertIsNone(re.search(pattern, source))

    def test_service_tidak_menulis_ulang_konstanta_lama(self):
        for rel in (
            "app/services/photo_service.py",
            "app/services/journal_service.py",
        ):
            source = (ROOT / rel).read_text(encoding="utf-8")

            self.assertNotIn("5 * 1024 * 1024", source, rel)
            self.assertIsNone(re.search(r"> 150\b", source), rel)
            self.assertIsNone(re.search(r"> 5\b", source), rel)


# =========================================================
# HALAMAN ERROR
# =========================================================

class ConsolidatedErrorPageTests(unittest.TestCase):

    EXPECTED = {
        403: ("Akses Ditolak", "ACCESS FORBIDDEN", "data-go-back"),
        404: ("Halaman Tidak Ditemukan", "PAGE NOT FOUND", "data-go-back"),
        500: ("Terjadi Kesalahan Server", "INTERNAL SERVER ERROR", "data-reload"),
    }

    def _fetch(self, code):
        app = make_app(debug=True)
        client = app.test_client()

        if code == 500:
            with self.assertLogs(app.logger, level="ERROR"):
                return client.get(f"/test-error/{code}")

        return client.get(f"/test-error/{code}")

    def test_setiap_kode_memakai_status_dan_pesan_yang_benar(self):
        for code, (title, label, button) in self.EXPECTED.items():
            with self.subTest(code=code):
                response = self._fetch(code)
                html = response.get_data(as_text=True)

                self.assertEqual(response.status_code, code)
                self.assertIn(title, html)
                self.assertIn(label, html)
                self.assertIn(f"HTTP ERROR {code}", html)
                self.assertIn(f"<title>{code}</title>", html)
                self.assertIn(f"error-illustration error-{code}", html)
                self.assertIn(button, html)
                self.assertIn("Kembali ke Beranda", html)

    def test_tombol_sekunder_sesuai_jenis_error(self):
        self.assertNotIn("data-reload", self._fetch(404).get_data(as_text=True))
        self.assertNotIn("data-go-back", self._fetch(500).get_data(as_text=True))

    def test_hanya_satu_template_error(self):
        self.assertTrue((ROOT / "templates" / "error.html").is_file())
        self.assertFalse((ROOT / "templates" / "errors").exists())

    def test_500_tidak_membocorkan_detail_dan_tetap_dicatat(self):
        app = make_app()
        secret = "RAHASIA-INTERNAL-98765"

        @app.get("/__boom")
        def boom():
            raise RuntimeError(secret)

        with self.assertLogs(app.logger, level="ERROR") as logs:
            response = app.test_client().get("/__boom")

        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 500)
        self.assertNotIn(secret, body)
        self.assertNotIn("Traceback", body)
        self.assertTrue(any(secret in line for line in logs.output))

    def test_500_saat_database_mati_tetap_menampilkan_halaman_error(self):
        app = make_app(csrf=False)
        client = app.test_client()
        login(client)

        with patch_db(error=RuntimeError("db mati")):
            with self.assertLogs(app.logger, level="ERROR"):
                response = client.get("/student/dashboard")

        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 500)
        self.assertIn("Terjadi Kesalahan Server", html)
        self.assertNotIn("db mati", html)


if __name__ == "__main__":
    unittest.main()
