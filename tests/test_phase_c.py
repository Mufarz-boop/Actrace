"""
Tes Tahap C ACTRACE: penggabungan My Journals dan Journal History.

Semua memakai database tiruan. Hasilnya tidak membuktikan perilaku pada
MySQL asli maupun tampilan di browser.

    python -m unittest discover -s tests -t . -v
"""

import re
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest import mock

# tests.support harus diimpor lebih dulu: ia memasang stub dependensi
# sebelum modul app diimpor.
from tests import support
from tests.support import (
    FakeConnection,
    FakeCursor,
    make_app,
    patch_db,
    total_calls,
)


ROOT = Path(__file__).resolve().parent.parent
STUDENT_ID = 7


def login(client, user_id=STUDENT_ID):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id


def flashed(client):
    with client.session_transaction() as sess:
        return [message for _, message in sess.get("_flashes", [])]


def journal_row(journal_id=1, title="Belajar Flask", photo_count=0, day=11):
    return {
        "journal_id": journal_id,
        "activity_date": date(2026, 11, day),
        "title": title,
        "description": f"Deskripsi {title}",
        "created_at": datetime(2026, 11, day, 8),
        "updated_at": datetime(2026, 11, day, 9),
        "photo_count": photo_count,
    }


def open_list(client, query="", rows=(), total=None):
    """Buka /student/journals dengan DB tiruan; kembalikan (response, cursor)."""

    rows = list(rows)
    cursor = FakeCursor(
        fetchone=[{"total": len(rows) if total is None else total}],
        fetchall=[rows],
    )

    with patch_db(connection=FakeConnection(cursor)):
        response = client.get(f"/student/journals{query}")

    return response, cursor


# =========================================================
# HALAMAN MY JOURNALS
# =========================================================

class MyJournalsPageTests(unittest.TestCase):

    def setUp(self):
        self.client = make_app(csrf=False).test_client()
        login(self.client)

    def test_halaman_terbuka_dan_menampilkan_jurnal(self):
        response, _ = open_list(
            self.client,
            rows=[
                journal_row(1, "Belajar Flask", photo_count=3, day=11),
                journal_row(2, "Membuat Laporan", photo_count=0, day=10),
            ],
        )

        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("<title>My Journals", html.replace("\n", " ").replace("  ", ""))
        self.assertIn("Belajar Flask", html)
        self.assertIn("Membuat Laporan", html)
        self.assertIn("Deskripsi Belajar Flask", html)
        self.assertIn("11", html)

    def test_jumlah_foto_ditampilkan_hanya_bila_ada(self):
        response, _ = open_list(
            self.client,
            rows=[
                journal_row(1, "Ada Foto", photo_count=3),
                journal_row(2, "Tanpa Foto", photo_count=0),
            ],
        )

        html = response.get_data(as_text=True)

        self.assertEqual(html.count("history-photo-count"), 1)
        self.assertIn("3 foto", html)

    def test_hanya_jurnal_milik_siswa_yang_login(self):
        for user_id in (7, 99):
            with self.subTest(user_id=user_id):
                client = make_app(csrf=False).test_client()
                login(client, user_id)

                _, cursor = open_list(client, rows=[journal_row()])

                for sql, params in cursor.executed:
                    self.assertIn("j.user_id = %s", sql)
                    self.assertEqual(params[0], user_id)

    def test_pencarian(self):
        _, cursor = open_list(self.client, "?q=flask", rows=[journal_row()])

        sql, params = cursor.executed[0]

        self.assertIn("j.title LIKE %s OR j.description LIKE %s", sql)
        self.assertEqual(params, (STUDENT_ID, "%flask%", "%flask%"))

    def test_filter_tanggal(self):
        _, cursor = open_list(
            self.client,
            "?start_date=2026-11-01&end_date=2026-11-30",
            rows=[journal_row()],
        )

        sql, params = cursor.executed[0]

        self.assertIn("j.activity_date >= %s", sql)
        self.assertIn("j.activity_date <= %s", sql)
        self.assertEqual(
            params, (STUDENT_ID, date(2026, 11, 1), date(2026, 11, 30))
        )

    def test_rentang_tanggal_terbalik_menampilkan_error_tanpa_query(self):
        client = self.client

        with patch_db() as mocks:
            response = client.get(
                "/student/journals?start_date=2026-12-01&end_date=2026-11-01"
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Rentang tanggal tidak valid", response.get_data(as_text=True))
        self.assertEqual(total_calls(mocks), 0)

    def test_pagination_halaman_kedua(self):
        response, cursor = open_list(
            self.client,
            "?page=2&q=abc",
            rows=[journal_row(11)],
            total=25,
        )

        html = response.get_data(as_text=True)
        data_query = cursor.executed[1]

        self.assertEqual(data_query[1][-2:], (10, 10))  # LIMIT 10 OFFSET 10
        self.assertIn("Halaman", html)
        self.assertIn("<strong>3</strong>", html)  # total 3 halaman
        # Tautan sebelumnya/berikutnya memakai My Journals dan membawa filter.
        prev_href, next_href = re.findall(
            r'<a\s+href="([^"]+)"\s+rel="(?:prev|next)"', html
        )
        self.assertTrue(prev_href.startswith("/student/journals?"))
        self.assertTrue(next_href.startswith("/student/journals?"))
        self.assertIn("q=abc", prev_href)
        self.assertTrue(prev_href.endswith("page=1"))
        self.assertIn("q=abc", next_href)
        self.assertTrue(next_href.endswith("page=3"))
        self.assertNotIn("/student/history", html)

    def test_halaman_melebihi_batas_disesuaikan(self):
        _, cursor = open_list(self.client, "?page=99", rows=[journal_row()], total=25)

        self.assertEqual(cursor.executed[1][1][-2:], (10, 20))  # halaman 3

    def test_tombol_add_journal_ada_walau_belum_ada_jurnal(self):
        response, _ = open_list(self.client, rows=[], total=0)

        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('href="/student/journals/add"', html)
        self.assertIn("Belum ada jurnal aktivitas", html)
        self.assertIn("Buat jurnal pertama", html)

    def test_tombol_add_journal_ada_saat_pencarian_kosong(self):
        response, _ = open_list(self.client, "?q=tidak-ada", rows=[], total=0)

        html = response.get_data(as_text=True)

        self.assertIn('href="/student/journals/add"', html)
        self.assertIn("Belum ada jurnal yang cocok", html)

    def test_setiap_jurnal_punya_detail_edit_dan_hapus(self):
        response, _ = open_list(
            self.client,
            "?q=flask&page=1",
            rows=[journal_row(5, "Belajar Flask")],
        )

        html = response.get_data(as_text=True)

        self.assertIn('href="/student/journals/5"', html)
        self.assertIn('href="/student/journals/5/edit"', html)
        self.assertIn('action="/student/journals/5/delete"', html)
        self.assertIn('name="csrf_token"', html)
        # Konteks daftar dibawa agar redirect setelah hapus tidak membingungkan
        self.assertIn('name="origin" value="list"', html)
        self.assertIn('name="q" value="flask"', html)

    def test_ringkasan_berubah_saat_ada_filter(self):
        plain, _ = open_list(self.client, rows=[journal_row()])
        filtered, _ = open_list(self.client, "?q=x", rows=[journal_row()])

        self.assertIn("TOTAL CATATAN", plain.get_data(as_text=True))
        self.assertIn("JURNAL DITEMUKAN", filtered.get_data(as_text=True))


# =========================================================
# ROUTE DAN REDIRECT /history
# =========================================================

class RouteConsolidationTests(unittest.TestCase):

    def setUp(self):
        self.app = make_app(csrf=False)
        self.client = self.app.test_client()
        login(self.client)

    def test_history_dialihkan_ke_journals(self):
        response = self.client.get("/student/history")

        self.assertEqual(response.status_code, 301)
        self.assertEqual(response.headers["Location"], "/student/journals")

    def test_redirect_history_membawa_filter_yang_valid(self):
        response = self.client.get(
            "/student/history?q=flask&start_date=2026-11-01"
            "&end_date=2026-11-30&page=3"
        )

        location = response.headers["Location"]

        self.assertEqual(response.status_code, 301)
        self.assertTrue(location.startswith("/student/journals?"))
        for fragment in (
            "q=flask",
            "start_date=2026-11-01",
            "end_date=2026-11-30",
            "page=3",
        ):
            self.assertIn(fragment, location)

    def test_redirect_history_membuang_parameter_tak_dikenal_atau_tak_valid(self):
        response = self.client.get(
            "/student/history?_external=1&_scheme=http&x=1"
            "&start_date=bukan-tanggal&page=abc"
        )

        self.assertEqual(response.headers["Location"], "/student/journals")

    def test_redirect_history_tidak_membuka_db(self):
        with patch_db() as mocks:
            self.client.get("/student/history")

        self.assertEqual(total_calls(mocks), 0)

    def test_tamu_tetap_diarahkan_ke_login(self):
        guest = self.app.test_client()

        for path in ("/student/history", "/student/journals"):
            with self.subTest(path=path):
                response = guest.get(path)

                self.assertEqual(response.status_code, 302)
                self.assertIn("/login", response.headers["Location"])

    def test_endpoint_history_lama_dihapus_dan_endpoint_lain_dipertahankan(self):
        endpoints = set(self.app.view_functions)

        self.assertNotIn("student.history", endpoints)
        for name in (
            "student.journals",
            "student.add_journal",
            "student.detail_journal",
            "student.edit_journal",
            "student.delete_journal_route",
            "student.gallery",
            "student.reports",
        ):
            self.assertIn(name, endpoints)

    def test_url_utama_dan_url_lain_tetap_sama(self):
        rules = {rule.rule: rule.endpoint for rule in self.app.url_map.iter_rules()}

        self.assertEqual(rules["/student/journals"], "student.journals")
        self.assertEqual(rules["/student/history"], "student.legacy_history_redirect")
        self.assertEqual(rules["/student/journals/add"], "student.add_journal")
        self.assertEqual(
            rules["/student/journals/<int:journal_id>/delete"],
            "student.delete_journal_route",
        )

    def test_semua_url_for_mengarah_ke_endpoint_yang_ada(self):
        endpoints = set(self.app.view_functions)
        pattern = re.compile(r"""url_for\(\s*['"]([\w.]+)['"]""")
        sources = list((ROOT / "templates").rglob("*.html"))
        sources += list((ROOT / "app").rglob("*.py"))

        missing = []

        for path in sources:
            for name in pattern.findall(path.read_text(encoding="utf-8")):
                if name == "static":
                    continue
                if name.startswith("."):
                    name = name  # relatif blueprint; dicek terpisah
                if name not in endpoints and f"student.{name.lstrip('.')}" not in endpoints:
                    missing.append((path.name, name))

        self.assertEqual(missing, [])

    def test_hanya_satu_template_jurnal(self):
        self.assertTrue((ROOT / "templates/student/journals.html").is_file())
        self.assertFalse((ROOT / "templates/student/history.html").exists())

    def test_css_halaman_lama_dihapus_tetapi_yang_dipakai_dipertahankan(self):
        css = (ROOT / "static/css/student.css").read_text(encoding="utf-8")

        for removed in (
            ".journals-heading",
            ".journals-summary",
            ".journals-panel",
            ".journals-list",
            ".journals-empty",
            ".journal-entry",
        ):
            self.assertNotIn(removed, css)

        # masih dipakai reports.html
        self.assertIn(".journals-back-link", css)
        self.assertIn(".journal-delete-button", css)
        self.assertIn(".history-item__actions", css)


# =========================================================
# HAPUS JURNAL
# =========================================================

class DeleteFromListTests(unittest.TestCase):

    def setUp(self):
        self.client = make_app(csrf=False).test_client()
        login(self.client)

    def _delete(self, data=None, result=None):
        result = {"deleted": True, "cleanup_pending": False} if result is None else result

        with mock.patch("app.student.routes.delete_journal", return_value=result) as svc:
            response = self.client.post("/student/journals/5/delete", data=data or {})

        return response, svc

    def test_hapus_dari_daftar_kembali_ke_daftar_dengan_filter(self):
        response, svc = self._delete(
            {
                "origin": "list",
                "q": "flask",
                "start_date": "2026-11-01",
                "end_date": "2026-11-30",
                "page": "2",
            }
        )

        location = response.headers["Location"]

        self.assertEqual(response.status_code, 302)
        self.assertTrue(location.startswith("/student/journals?"))
        for fragment in ("q=flask", "start_date=2026-11-01", "end_date=2026-11-30", "page=2"):
            self.assertIn(fragment, location)
        svc.assert_called_once_with(journal_id=5, user_id=STUDENT_ID)
        self.assertEqual(flashed(self.client), ["Jurnal dan seluruh dokumentasi berhasil dihapus."])

    def test_hapus_dari_detail_kembali_ke_daftar_polos(self):
        response, _ = self._delete()

        self.assertEqual(response.headers["Location"], "/student/journals")

    def test_parameter_redirect_hapus_disaring(self):
        response, _ = self._delete(
            {"q": "x", "start_date": "bukan-tanggal", "page": "-4", "next": "http://evil.test"}
        )

        location = response.headers["Location"]

        self.assertEqual(location, "/student/journals?q=x")
        self.assertNotIn("evil", location)

    def test_jurnal_milik_orang_lain_atau_tidak_ada_menghasilkan_404(self):
        response, svc = self._delete(result={"deleted": False})

        self.assertEqual(response.status_code, 404)
        svc.assert_called_once_with(journal_id=5, user_id=STUDENT_ID)

    def test_service_selalu_dipanggil_dengan_user_id_sesi_bukan_input_form(self):
        client = make_app(csrf=False).test_client()
        login(client, 99)

        with mock.patch(
            "app.student.routes.delete_journal",
            return_value={"deleted": True, "cleanup_pending": False},
        ) as svc:
            client.post("/student/journals/5/delete", data={"user_id": "7"})

        svc.assert_called_once_with(journal_id=5, user_id=99)

    def test_gagal_hapus_dari_daftar_kembali_ke_daftar(self):
        from app.services.journal_service import JournalDeleteError

        with mock.patch("app.student.routes.delete_journal", side_effect=JournalDeleteError("x")):
            with self.assertLogs(self.client.application.logger, level="ERROR"):
                response = self.client.post(
                    "/student/journals/5/delete",
                    data={"origin": "list", "q": "flask", "page": "2"},
                )

        location = response.headers["Location"]

        self.assertTrue(location.startswith("/student/journals?"))
        self.assertIn("q=flask", location)
        self.assertIn("page=2", location)

    def test_gagal_hapus_dari_detail_kembali_ke_detail(self):
        from app.services.journal_service import JournalDeleteError

        with mock.patch("app.student.routes.delete_journal", side_effect=JournalDeleteError("x")):
            with self.assertLogs(self.client.application.logger, level="ERROR"):
                response = self.client.post("/student/journals/5/delete")

        self.assertEqual(response.headers["Location"], "/student/journals/5")

    def test_hapus_tanpa_login_ditolak(self):
        client = make_app(csrf=False).test_client()

        with mock.patch("app.student.routes.delete_journal") as svc:
            response = client.post("/student/journals/5/delete")

        self.assertEqual(response.status_code, 302)
        svc.assert_not_called()

    def test_hapus_tanpa_token_csrf_ditolak(self):
        # Membutuhkan Flask-WTF asli; pola sama dengan tes logout.
        client = make_app(csrf=True).test_client()
        login(client)

        with mock.patch("app.student.routes.delete_journal") as svc:
            response = client.post("/student/journals/5/delete")

        self.assertEqual(response.status_code, 400)
        svc.assert_not_called()


class OwnershipTests(unittest.TestCase):
    """Siswa tidak dapat membuka atau mengubah jurnal siswa lain."""

    def setUp(self):
        self.client = make_app(csrf=False).test_client()
        login(self.client, 99)

    def test_detail_memakai_user_id_sesi_dan_404_bila_bukan_miliknya(self):
        with mock.patch("app.student.routes.get_journal_detail", return_value=None) as svc:
            response = self.client.get("/student/journals/5")

        self.assertEqual(response.status_code, 404)
        svc.assert_called_once_with(journal_id=5, user_id=99)

    def test_edit_404_bila_bukan_miliknya(self):
        with mock.patch("app.student.routes.get_journal_detail", return_value=None):
            response = self.client.get("/student/journals/5/edit")

        self.assertEqual(response.status_code, 404)


# =========================================================
# NAVIGASI
# =========================================================

class SidebarTests(unittest.TestCase):

    JOURNAL_HREF = 'href="/student/journals"'

    def setUp(self):
        self.client = make_app(csrf=False).test_client()
        login(self.client)

    def _active_hrefs(self, html):
        """href setiap tautan sidebar yang ditandai aktif."""

        return re.findall(
            r'<a\s+href="([^"]+)"\s+class="nav-link nav-link--active"', html
        )

    def _assert_my_journals_active(self, html):
        self.assertEqual(self._active_hrefs(html), ["/student/journals"])
        self.assertEqual(html.count('aria-current="page"'), 1)

    def test_satu_menu_jurnal_tanpa_journal_history(self):
        response, _ = open_list(self.client, rows=[journal_row()])
        html = response.get_data(as_text=True)

        self.assertEqual(html.count("<span>My Journals</span>"), 1)
        self.assertNotIn("Journal History", html)
        self.assertNotIn("/student/history", html)
        self.assertIn("<span>Journal Gallery</span>", html)

    def test_aktif_di_my_journals(self):
        response, _ = open_list(self.client, rows=[journal_row()])

        self._assert_my_journals_active(response.get_data(as_text=True))

    def test_aktif_di_add_journal(self):
        with patch_db():
            response = self.client.get("/student/journals/add")

        self.assertEqual(response.status_code, 200)
        self._assert_my_journals_active(response.get_data(as_text=True))

    def test_aktif_di_detail_dan_edit_jurnal(self):
        journal = {
            "journal_id": 5,
            "activity_date": date(2026, 11, 11),
            "title": "Belajar Flask",
            "description": "Deskripsi",
            "created_at": datetime(2026, 11, 11, 8),
            "updated_at": datetime(2026, 11, 11, 9),
            "photos": [],
            "photo_count": 0,
        }

        for path in ("/student/journals/5", "/student/journals/5/edit"):
            with self.subTest(path=path):
                with mock.patch(
                    "app.student.routes.get_journal_detail", return_value=journal
                ):
                    response = self.client.get(path)

                self.assertEqual(response.status_code, 200)
                self._assert_my_journals_active(response.get_data(as_text=True))

    def test_gallery_tidak_menandai_my_journals_aktif(self):
        with mock.patch(
            "app.student.routes.get_gallery_photos", return_value=([], 0)
        ):
            response = self.client.get("/student/gallery")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self._active_hrefs(response.get_data(as_text=True)),
            ["/student/gallery"],
        )


class DashboardLinkTests(unittest.TestCase):

    def test_empty_state_tidak_lagi_menduplikasi_tautan_my_journals(self):
        client = make_app(csrf=False).test_client()
        login(client)

        cursor = FakeCursor(fetchone=[{"total": 0}, None])

        with patch_db(connection=FakeConnection(cursor)):
            response = client.get("/student/dashboard")

        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Buka My Journals", html)
        self.assertIn("Belum ada jurnal aktivitas", html)
        # sidebar, "View all", dan kartu Quick Access
        self.assertEqual(html.count('href="/student/journals"'), 3)


if __name__ == "__main__":
    unittest.main()
