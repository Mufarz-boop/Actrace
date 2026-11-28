"""
Pengujian pemulihan isian halaman My Profile.

Yang diuji: saat validasi/penyimpanan gagal, isian siswa tidak hilang;
draf hanya dipakai sekali; jalur sukses membersihkan draf.
Tes memakai DB tiruan (tidak membuka koneksi MySQL).
"""

import datetime
import unittest
from unittest import mock

from tests.support import (
    FakeConnection,
    FakeCursor,
    make_app,
    patch_db,
)


def profile_row(**overrides):
    row = {
        "user_id": 7,
        "student_code": "S-0007",
        "full_name": "Siswa Uji",
        "username": "siswa.uji",
        "email": "siswa@example.test",
        "photo": None,
        "created_at": datetime.datetime(2026, 1, 5, 8, 0),
        "updated_at": datetime.datetime(2026, 11, 1, 9, 30),
        "school_name": "SMK Lama",
        "class_name": None,
        "major": None,
        "academic_year": None,
        "internship_company": None,
        "internship_industry": None,
        "internship_address": None,
        "supervisor_name": None,
        "supervisor_position": None,
        "internship_start_date": None,
        "internship_end_date": None,
    }
    row.update(overrides)
    return row


def valid_form(**overrides):
    form = {
        "full_name": "Siswa Uji",
        "username": "siswa.uji",
        "email": "siswa@example.test",
        "school_name": "SMK Negeri 1 Contoh",
        "class_name": "XII RPL 1",
        "major": "Rekayasa Perangkat Lunak",
        "academic_year": "2026/2027",
        "internship_company": "PT Contoh",
        "internship_industry": "IT",
        "internship_address": "Jl. Contoh No. 1",
        "supervisor_name": "Budi",
        "supervisor_position": "IT Supervisor",
        "internship_start_date": "2026-07-01",
        "internship_end_date": "2026-09-30",
    }
    form.update(overrides)
    return form


STATS = {"total_journals": 3, "total_photos": 5, "latest_activity": None}


class ProfileDraftTests(unittest.TestCase):

    def setUp(self):
        self.app = make_app(csrf=False)
        self.client = self.app.test_client()

        with self.client.session_transaction() as sess:
            sess["user_id"] = 7
            sess["full_name"] = "Siswa Uji"

        stats = mock.patch(
            "app.student.routes.get_student_stats", return_value=STATS
        )
        stats.start()
        self.addCleanup(stats.stop)

    def get_profile(self, row=None):
        cursor = FakeCursor(fetchone=[row or profile_row()])
        with patch_db(FakeConnection(cursor)):
            return self.client.get("/student/profile")

    def post_profile(self, data):
        # Validasi gagal terjadi sebelum DB disentuh.
        with patch_db(FakeConnection(FakeCursor())):
            return self.client.post(
                "/student/profile", data=data, follow_redirects=False
            )

    # -----------------------------------------------------

    def test_get_without_draft_shows_no_restore_note(self):
        response = self.get_profile()
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("profile-restored", html)
        self.assertNotIn('data-restored="true"', html)
        self.assertIn('data-max-photo-bytes="2097152"', html)
        self.assertIn("SMK Lama", html)

    def test_invalid_username_keeps_typed_input(self):
        response = self.post_profile(valid_form(username="ab"))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/student/profile"))

        html = self.get_profile().get_data(as_text=True)

        self.assertIn("profile-restored", html)
        self.assertIn('data-restored="true"', html)
        self.assertIn("SMK Negeri 1 Contoh", html)
        self.assertIn("PT Contoh", html)
        self.assertIn('value="2026-07-01"', html)
        self.assertNotIn("SMK Lama", html)
        self.assertIn("Username harus terdiri dari 3", html)

    def test_draft_is_used_only_once(self):
        self.post_profile(valid_form(username="ab"))
        self.get_profile()

        html = self.get_profile().get_data(as_text=True)

        self.assertNotIn("profile-restored", html)
        self.assertIn("SMK Lama", html)

    def test_invalid_date_range_keeps_typed_input(self):
        response = self.post_profile(
            valid_form(
                internship_start_date="2026-10-01",
                internship_end_date="2026-09-01",
            )
        )
        self.assertEqual(response.status_code, 302)

        html = self.get_profile().get_data(as_text=True)

        self.assertIn('value="2026-10-01"', html)
        self.assertIn('value="2026-09-01"', html)
        self.assertIn("Tanggal mulai PKL tidak boleh melewati", html)

    def test_unparseable_date_in_draft_does_not_crash(self):
        with self.client.session_transaction() as sess:
            sess["profile_draft"] = {
                "full_name": "Siswa Uji",
                "internship_start_date": "bukan-tanggal",
            }

        response = self.get_profile()
        self.assertEqual(response.status_code, 200)

    def test_internship_status_uses_saved_data_not_draft(self):
        # Draf berisi tanggal mulai di masa depan; status tetap dari DB.
        self.post_profile(
            valid_form(username="ab", internship_start_date="2099-01-01")
        )

        html = self.get_profile().get_data(as_text=True)

        self.assertIn("internship-status--empty", html)
        self.assertNotIn("internship-status--upcoming", html)

    def test_oversized_draft_is_skipped_not_stored(self):
        response = self.post_profile(
            valid_form(
                username="ab",
                full_name="\u00e9" * 100,
                email="\u00e9" * 100,
                school_name="\u00e9" * 150,
                internship_company="\u00e9" * 150,
                internship_address="\u00e9" * 255,
                major="\u00e9" * 100,
                supervisor_name="\u00e9" * 100,
            )
        )
        self.assertEqual(response.status_code, 302)

        with self.client.session_transaction() as sess:
            self.assertNotIn("profile_draft", sess)

    def test_successful_save_clears_leftover_draft(self):
        with self.client.session_transaction() as sess:
            sess["profile_draft"] = {"full_name": "Sisa lama"}

        cursor = FakeCursor(fetchone=[{"photo": None}])
        connection = FakeConnection(cursor)

        with patch_db(connection):
            response = self.client.post("/student/profile", data=valid_form())

        self.assertEqual(response.status_code, 302)
        self.assertTrue(connection.committed)

        with self.client.session_transaction() as sess:
            self.assertNotIn("profile_draft", sess)
            self.assertEqual(sess["full_name"], "Siswa Uji")

    def test_database_failure_keeps_typed_input(self):
        class Exploding(FakeCursor):
            def execute(self, sql, params=None):
                raise RuntimeError("db mati")

        connection = FakeConnection(Exploding())

        with patch_db(connection):
            response = self.client.post("/student/profile", data=valid_form())

        self.assertEqual(response.status_code, 302)
        self.assertTrue(connection.rolled_back)

        html = self.get_profile().get_data(as_text=True)

        self.assertIn("profile-restored", html)
        self.assertIn("SMK Negeri 1 Contoh", html)


if __name__ == "__main__":
    unittest.main()
