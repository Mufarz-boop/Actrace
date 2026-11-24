# ACTRACE — Step 1: Application Inventory & Duplication Audit

**Mode:** analisis saja. Tidak ada file repositori yang diubah, dibuat, dihapus, atau di-commit oleh audit ini.
**Basis:** working tree `Mufarz-boop/Actrace` pada HEAD `cc75397`. Dua file di working tree membawa perubahan *belum di-commit* dari fase sebelumnya (`templates/student/reports.html` — Phase 3, `app/services/journal_service.py` — Phase 4). Audit membaca kondisi working tree tersebut.
**Konvensi bukti:** `file:baris` adalah baris pada working tree. **[F]** = fakta yang dibaca langsung dari kode. **[H]** = hipotesis/inferensi.

---

## 1. Application Overview

ACTRACE adalah aplikasi Flask server-rendered (Jinja2) bernama "Digital Activity Journal" untuk siswa PKL, dengan MySQL sebagai penyimpanan dan file foto di disk.

- **Pola:** application factory (`app/__init__.py:create_app`), tiga blueprint: `auth` (tanpa prefix), `student` (tanpa prefix), `api` (`/api`). CSRF lewat Flask-WTF; blueprint `api` dikecualikan dari CSRF dan memakai API key sendiri. [F]
- **Peran pengguna:** hanya satu, *student*. Tidak ada kata "admin" maupun kolom/logika `role` di `app/`, `templates/`, `static/`, `config.py`, `database/`. [F] Gerbang akses = `session["user_id"]` lewat dekorator `student_required`. [F]
- **Integrasi eksternal:** blueprint `api` (header `X-API-Key`, `hmac.compare_digest`) berfungsi sebagai pintu bagi aplikasi pendamping. Dokumen `catatan/Proposal_FIELDLINK_Integrasi_ACTRACE.pdf` menyebut FIELDLINK sebagai aplikasi pendamping ACTRACE; hubungan ini [H] karena hanya halaman awal dokumen yang dibaca.
- **Lapisan:** route tipis hanya untuk CRUD jurnal (lewat `journal_service`) dan PDF (lewat `pdf_service`). Sebagian besar route lain (profil, settings, dashboard, history, journals, foto, API) menjalankan SQL langsung di route. [F] Ini penting untuk bagian duplikasi.
- **Ukuran:** `app/student/routes.py` 2.090 baris (15 route siswa), `static/css/student.css` 7.080 baris (748 blok selector), `pdf_service.py` ±1.000 baris, `journal_service.py` ±1.090 baris.

## 2. Directory & File Map

| Path | Tanggung jawab |
|---|---|
| `run.py` | Entry point; `create_app()` dan `app.run`. |
| `config.py` | `Config` dari `.env`; `Config.validate()` (SECRET_KEY ≥32, SHARED_API_KEY ≥32/berbeda, DB, upload) dan membuat folder upload. |
| `app/__init__.py` | Factory, CSRF, registrasi blueprint, header keamanan, `GET /`, handler 403/404/500, route `/test-error/*` hanya saat `DEBUG`. |
| `app/db.py` | `get_db_connection()` (koneksi baru per pemanggilan; `charset="utf8"`; error → `RuntimeError`). |
| `app/auth/routes.py` | `GET/POST /login`, `POST /logout`. |
| `app/student/routes.py` | Semua route siswa + helper `_parse_report_period`, `_get_report_student`, `_save_profile_photo`. |
| `app/api/` | `GET /api/health`, dua endpoint `/api/students/<code>/…`; `authentication.py` (`shared_key_required`). |
| `app/services/journal_service.py` | Validasi, create/get/update/delete jurnal, data laporan, galeri. |
| `app/services/photo_service.py` | Validasi & simpan foto jurnal, hapus file (batas path). |
| `app/services/pdf_service.py` | Pembangun PDF ReportLab (`build_journal_report_pdf`). |
| `app/utils/decorators.py` | `student_required`. `app/utils/helpers.py` — **0 byte**. [F] |
| `create_student.py` | Skrip CLI pembuat akun (satu-satunya cara membuat akun yang ditemukan; tidak ada route registrasi). [F] |
| `database/schema.sql` | `users`, `journals`, `journal_photos`. `database/migrations/001_student_profiles.sql` — `student_profiles` (**tidak ada di schema.sql**). [F] |
| `templates/auth`, `errors`, `student` | 1 login, 3 halaman error, 10 halaman siswa + `base_student.html`. |
| `static/css/` | `style.css` (130, variabel), `student.css` (7.080), `auth.css`, `errors.css`. |
| `static/js/` | `main.js`, `nav-indicator.js`, `login-animation.js`, `logout-animation.js`, `dashboard-reveal.js`, `journal.js`, `edit_journal.js`, `gallery.js`, `reports-motion.js`, `errors.js`. |
| `tests/` | `support.py`, `test_phase1_baseline.py` (34 tes, DB ditiru). |
| `catatan/` | 3 PDF + 1 PPTX dokumen proyek (bukan kode). |
| `IMPLEMENTATION_NOTES.md` | Catatan implementasi & batas klaim pengujian. |

## 3. Feature Inventory

| # | Fitur | Tujuan | Peran | Akses (menu/halaman) | Route | Template | Service / fungsi | Tabel | Tumpang tindih? |
|---|---|---|---|---|---|---|---|---|---|
| F1 | Login/Logout | Autentikasi sesi | Siswa | `/login`; tombol logout (sidebar bawah) | `auth.login`, `auth.logout` | `auth/login.html` | SQL langsung di route; bcrypt | users | Rule bcrypt/password lihat D-10 |
| F2 | Dashboard | Ringkasan: total jurnal + aktivitas terbaru | Siswa | Sidebar *Dashboard*; brand | `student.dashboard` | `dashboard.html` | SQL langsung | journals | Statistik: D-04 |
| F3 | My Journals | Daftar semua jurnal + hapus | Siswa | Sidebar *My Journals* | `student.journals` | `journals.html` | SQL langsung | journals | **D-03** (dengan History) |
| F4 | Journal History | Cari/filter tanggal/paginasi jurnal | Siswa | Sidebar *Journal History* | `student.history` | `history.html` | SQL langsung (+ subquery foto) | journals, journal_photos | **D-03** |
| F5 | Tambah Jurnal | Buat jurnal + ≤5 foto | Siswa | Hanya dari `history.html` (2 tautan) | `student.add_journal` | `add_journal.html`, `journal.js` | `create_journal`, `validate_journal_data`, `photo_service` | journals, journal_photos | Validasi klien/server: D-06 |
| F6 | Detail Jurnal | Lihat jurnal + foto, tautan edit/hapus | Siswa | Dari journals/history/reports | `student.detail_journal` | `detail_journal.html` | `get_journal_detail` | journals, journal_photos | — |
| F7 | Edit Jurnal | Ubah data, tambah/hapus foto | Siswa | Dari detail | `student.edit_journal` | `edit_journal.html`, `edit_journal.js` | `update_journal` | journals, journal_photos | D-06 |
| F8 | Hapus Jurnal | Hapus jurnal + file foto | Siswa | Form di `journals.html` dan `detail_journal.html` | `student.delete_journal_route` (POST) | — | `delete_journal` | journals, journal_photos | Dua titik masuk, satu route |
| F9 | Journal Gallery | Seluruh foto (24/halaman) + lightbox | Siswa | Sidebar *Journal Gallery* | `student.gallery` | `gallery.html`, `gallery.js` | `get_gallery_photos` | journal_photos, journals | Foto juga tampil di detail/edit/PDF |
| F10 | Foto jurnal privat | Menyajikan file foto bila milik siswa | Siswa | Dipakai `<img>` di detail/edit/gallery | `student.journal_photo` | — | SQL langsung + cek path | journal_photos, journals | D-07 |
| F11 | Activity Reports (pratinjau) | Rekap per periode + metrik | Siswa | Sidebar *Activity Reports*; kartu di dashboard | `student.reports` | `reports.html`, `reports-motion.js` | `get_journals_for_report`, `_parse_report_period` | journals, journal_photos | D-04, D-05 |
| F12 | Unduh PDF | Laporan PDF periode | Siswa | Tombol di `reports.html` | `student.download_journal_report` | — | `build_journal_report_pdf`, `_get_report_student` | journals, journal_photos, users | D-04 |
| F13 | Profil | Data akun + akademik + PKL + foto profil | Siswa | Sidebar *My Profile*; kartu dashboard | `student.profile` (GET/POST) | `profile.html` | SQL langsung, `_save_profile_photo` | users, student_profiles, journals (statistik) | **D-01, D-02, D-04** |
| F14 | Detail profil (POST terpisah) | Simpan hanya data akademik/PKL | Siswa | **Tidak ada tautan/form yang merujuknya** | `student.profile_details` | — | SQL langsung | student_profiles | **D-01** |
| F15 | Foto profil privat | Sajikan foto profil | Siswa | `<img>` di profil/sidebar | `student.profile_photo` | — | SQL langsung | users | D-07 |
| F16 | Settings | Ubah kata sandi | Siswa | Sidebar *Settings* | `student.settings` (GET/POST) | `settings.html` | SQL langsung, bcrypt | users | D-10 |
| F17 | API integrasi | Health, ringkasan, daftar jurnal per `student_code` | Sistem eksternal | `/api/...` (header API key) | `api.health`, `api.student_summary`, `api.student_journals` | — | SQL langsung | users, journals | **D-04, D-09** |
| F18 | Pembuatan akun | Provisioning akun | Operator | CLI `create_student.py` | — | — | SQL langsung, bcrypt | users | D-10 |
| F19 | Halaman error | 403/404/500 | Semua | otomatis | handler di factory | `errors/*.html` | — | — | D-12 |

## 4. Navigation Inventory

**Sidebar (`base_student.html:158–300`)**

| Grup | Item | Endpoint | Kondisi aktif |
|---|---|---|---|
| WORKSPACE | Dashboard | `student.dashboard` | `== student.dashboard` |
| | My Journals | `student.journals` | **hanya** `== student.journals` |
| | Journal History | `student.history` | `== student.history` |
| | Journal Gallery | `student.gallery` | `== student.gallery` |
| | Activity Reports | `student.reports` | `in (reports, download_journal_report)` |
| Grup kedua (label baris 246) | My Profile | `student.profile` | `in (profile, profile_photo)` |
| | Settings | `student.settings` | `== student.settings` |
| Bawah | Blok pengguna + form `POST auth.logout` | | |
| Brand | Logo → `student.dashboard` | | |

Tidak ada submenu bertingkat. Topbar tidak berisi tautan (tombol menu mobile, penanda "Personal Workspace", avatar inisial). `skip-link` ke `#main-content`.

**Tautan dalam halaman (dihitung dari template)**

| Halaman | Tautan keluar |
|---|---|
| dashboard | `journals` ×3 (baris 183, 249, 283), `reports`, `profile` |
| journals | `dashboard`, `detail_journal` ×2, form hapus |
| history | `add_journal` ×2, `history` (reset/paginasi), `detail_journal` |
| detail | `journals` ×3, `dashboard`, `edit_journal` ×2, form hapus, `journal_photo` |
| edit | `detail_journal` ×2, `journal_photo`, `edit_journal` |
| gallery | `gallery` (paginasi), `journal_photo` ×2 |
| reports | `dashboard`, `reports`, `download_journal_report`, `detail_journal` |
| profile | `dashboard`, `profile`, `profile_photo` |
| settings | hanya `settings` |
| add_journal | `journals` ×2, `add_journal` |

**Pengamatan navigasi [F]**
- **N-1** Dua item menu menampilkan data yang sama: *My Journals* dan *Journal History* (D-03).
- **N-2** `add_journal` **tidak ada di sidebar, dashboard, maupun `journals.html`**; hanya `history.html` (baris 23 dan 344) yang menautkannya. Keadaan kosong di `journals.html` tidak punya tombol/tautan ajakan (hanya ikon `<use>`).
- **N-3** Dashboard menautkan ke `student.journals` tiga kali; tujuan yang sama.
- **N-4** Item aktif *My Journals* tidak menyala pada `detail_journal`, `edit_journal`, `add_journal` (kondisi hanya `== student.journals`); sidebar tidak menandai halaman-halaman itu.
- **N-5** Tombol "Kembali ke Dashboard" muncul di journals, profile, reports, detail — jalur kedua ke tujuan yang sama dengan sidebar.
- **N-6** *My Journals* dan *Journal Gallery* memakai ikon sprite yang sama (`#icon-journal`).
- **N-7** Pengalihan setelah aksi: tambah/hapus → `journals`; gagal muat detail → `journals`.

## 5. Route Inventory

**Aplikasi**: `GET /` (redirect dashboard/login); `GET /test-error/{403,404,500}` hanya jika `DEBUG`.
**Auth**: `GET|POST /login`, `POST /logout`.

**Student (semua `@student_required`; 15 route)**

| Kategori | Route |
|---|---|
| Ringkasan | `GET /dashboard` (1320) |
| Jurnal – baca | `GET /journals` (1540), `GET /history` (1366), `GET /journals/<int:id>` (1578), `GET /gallery` (1684) |
| Jurnal – tulis | `GET|POST /journals/add` (1855), `GET|POST /journals/<id>/edit` (1619), `POST /journals/<id>/delete` (2018) |
| Berkas | `GET /journals/<id>/photos/<photo_id>` (1748), `GET /profile/photo` (1019) |
| Laporan | `GET /reports` (83), `GET /reports/pdf` (125) |
| Akun | `GET|POST /profile` (301), `POST /profile/details` (875), `GET|POST /settings` (1092) |

**API (`/api`)**: `GET /health` (publik), `GET /students/<code>/summary`, `GET /students/<code>/journals` (keduanya `shared_key_required`).

**Catatan [F]:** `student.profile_details` tidak dirujuk oleh `url_for`, form, atau JS mana pun di repo. `/journals/add` dan `/journals/<int:id>` tidak bentrok (converter `int`).

## 6. Service & Business Logic Inventory

| Modul | Fungsi | Tanggung jawab | Dependensi |
|---|---|---|---|
| `journal_service` | `validate_journal_data` | Wajib isi, judul ≤150, deskripsi ≤65.535 byte, tanggal valid & tidak di masa depan | — |
| | `create_journal` | Transaksi insert jurnal + simpan foto + insert metadata, rollback + bersihkan file | `photo_service` |
| | `get_journal_detail` | Jurnal milik user + foto | — |
| | `update_journal` | Transaksi; kunci baris; tambah/hapus foto; batas 5 foto | `photo_service` |
| | `get_journals_for_report` | Jurnal periode + foto (2 query), `photo_count` | konsumen: route reports/pdf, `pdf_service` |
| | `get_gallery_photos` | Foto paginasi + total | route gallery |
| | `delete_journal` | Hapus jurnal, lalu file foto | `photo_service` |
| `photo_service` | `validate_photo`, `save_journal_photos`, `delete_saved_photos`, `delete_photo_files` | Validasi (5 MB, JPEG/PNG/WEBP via Pillow), simpan, bersihkan | Pillow, `Config.UPLOAD_FOLDER` |
| `pdf_service` | `build_journal_report_pdf` + ±30 helper `_…` | Sampul, ringkasan, detail jurnal + galeri foto, penutup, nomor halaman | ReportLab, Pillow |

**Logika yang berada di route, bukan service [F]:** autentikasi (bcrypt), perubahan kata sandi, seluruh profil (validasi + upsert), foto profil (`_save_profile_photo`), statistik dashboard/profil, daftar `journals`, `history` (query dinamis), pengiriman foto, API. Layering tidak konsisten: jurnal CRUD + laporan di service, sisanya di route.

## 7. Data & Database Interaction Map

Tabel: `users` (PK `user_id`; `student_code`, `username`, `email` UNIK; `photo`), `journals` (FK→users, `activity_date DATE`, indeks `idx_journals_user_date(user_id, activity_date)`), `journal_photos` (FK→journals, `ON DELETE CASCADE`), `student_profiles` (FK→users, UNIQUE `user_id`; hanya di migrasi).

| Fitur | Tabel | Pola |
|---|---|---|
| Login | users | `WHERE username=%s OR email=%s LIMIT 1` |
| Dashboard | journals | `COUNT(*)` + 1 baris terbaru |
| Journals | journals | semua baris user, tanpa paginasi |
| History | journals, journal_photos | `COUNT(*)` + halaman 10, `LIKE` judul/deskripsi, rentang tanggal, subquery `COUNT` foto |
| Detail/Edit | journals, journal_photos | 2 query; edit memakai `FOR UPDATE` |
| Create/Delete | journals, journal_photos | transaksi |
| Gallery | journal_photos ⋈ journals | `COUNT` + halaman |
| Reports/PDF | journals, journal_photos, users | 2 query (jurnal, lalu foto per daftar ID); `users` untuk nama/kode |
| Profil GET | users ⟕ student_profiles, journals ⟕ journal_photos | 1 query profil + statistik `COUNT(DISTINCT)` **dijalankan dua kali** (D-02) |
| Profil POST | users, student_profiles | `UPDATE users` + `INSERT … (upsert)` |
| Settings | users | baca/ubah `password_hash` |
| API | users, journals | 2–3 query per request |

Koneksi: satu koneksi baru per fungsi/route (tanpa pool). [F]

## 8. Duplication Findings

Skala jenis: **Confirmed** · **Partial overlap** · **Similar appearance, distinct responsibility** · **Needs investigation**.

**D-01 — `profile_details` menduplikasi bagian akademik/PKL dari `profile` POST** — *Confirmed duplication*; kepercayaan: tinggi
- File: `routes.py:profile` (301–700) dan `profile_details` (875–1016).
- Bukti: kedua blok membaca 9 field yang sama, memvalidasi panjang yang sama (150/50/100/20/150/100/255/100/100 — di `profile` sebagai dict `profile_fields`, di `profile_details` sebagai `limits`), memvalidasi `date.fromisoformat` + `start > end` dengan pesan identik ("Tanggal mulai PKL tidak boleh melewati tanggal selesai."), dan menjalankan `INSERT INTO student_profiles … ON DUPLICATE KEY UPDATE` yang sama. `profile.html` hanya mengirim ke `student.profile`; tidak ada rujukan ke `profile_details` di template/JS/Python lain. [F] Apakah ada klien luar yang memanggil endpoint ini tidak dapat diketahui dari repo.

**D-02 — Statistik profil dijalankan dua kali dalam satu request** — *Confirmed duplication* (dalam satu fungsi); tinggi
- `routes.py` ±708–720 (di dalam `if user:`) dan ±770–783 menjalankan SQL identik (`COUNT(DISTINCT j.journal_id)`, `COUNT(DISTINCT jp.photo_id)`, `MAX(j.activity_date)`); hasil kedua menimpa `activity_stats` pertama. [F]

**D-03 — My Journals vs Journal History** — *Partial overlap*; tinggi
- `journals()` (1540): `SELECT journal_id, activity_date, title, description FROM journals WHERE user_id ORDER BY activity_date DESC, journal_id DESC` (tanpa batas). `history()` (1366): tabel, kolom, dan urutan yang sama, ditambah pencarian, filter tanggal, paginasi 10, `photo_count`, hari dalam minggu.
- Perbedaan fungsi yang nyata: hanya `journals.html` menyediakan tombol Hapus; hanya `history.html` menyediakan tautan Tambah Jurnal (N-2). Jadi keduanya bukan tiruan murni; data `journals` adalah himpunan bagian dari `history` tanpa filter.

**D-04 — Statistik/ringkasan dihitung di banyak tempat** — *Partial overlap*; sedang–tinggi
- Dashboard (`routes.py:1320`) dan `api.student_summary` menjalankan dua query yang sama persis (`COUNT(*)` jurnal user; jurnal terbaru `ORDER BY activity_date DESC, journal_id DESC LIMIT 1`). *Confirmed* untuk SQL ini.
- Profil menghitung total jurnal/foto/aktivitas terakhir dengan query berbeda (`COUNT(DISTINCT)` + join).
- Laporan: route `reports()` menghitung `total_photos` dan `total_activity_days` di Python; `pdf_service._summary_story` menghitung ulang hari unik dan total foto dari data yang sama dengan definisi yang sama. [F] Risiko inkonsistensi bila salah satu berubah.

**D-05 — Validasi rentang/tanggal diimplementasi berulang dengan semantik berbeda** — *Partial overlap*; sedang
- `validate_journal_data` (tanggal aktivitas, tidak boleh di masa depan), `_parse_report_period` (awal ≤ akhir, akhir ≤ hari ini, wajib), `history()` inline (opsional; rentang tidak valid → pesan + filter diabaikan), profil ×2 (tanggal PKL), dan JS `reports-motion.js` (awal ≤ akhir di klien). Pesan dan perlakuan "kosong/invalid" berbeda-beda; tidak ada fungsi bersama. [F]

**D-06 — Validasi gambar dan batas klien/server** — *Partial overlap*; tinggi untuk pola, sedang untuk kebijakan
- Server: `photo_service.validate_photo` (maks 5 MB, JPEG/PNG/WEBP via `Image.open` + `verify`) vs `routes._save_profile_photo` (maks 2 MB, format sama, batas resolusi, tolak animasi, EXIF, thumbnail, simpan ulang WebP). Pola sama, kebijakan berbeda. 
- Klien: `journal.js` (`MAX_PHOTOS=5`, `MAX_FILE_SIZE=5*1024*1024`, hitung judul `/150`) dan `edit_journal.js` (`5 * 1024 * 1024` inline) menduplikasi konstanta server (`MAX_PHOTOS`, `MAX_PHOTO_SIZE`, 150) tanpa sumber bersama. [F]

**D-07 — Penyelesaian path file privat + cegah traversal ×4** — *Partial overlap*; sedang
- `routes.journal_photo` (`resolve` + `relative_to`), `routes.profile_photo` (nama berkas + `parent == folder`), `pdf_service._resolve_photo` (`relative_to` + `is_file` + verifikasi Pillow), `photo_service.delete_photo_files` (batas root + tolak symlink). Tujuan berbeda (sajikan, sajikan, sematkan, hapus), tetapi inti pengamanan path diulang.

**D-08 — Boilerplate koneksi/kursor/penutupan dan penanganan error tidak seragam** — *Similar appearance* (pola, bukan logika bisnis ganda); tinggi
- Hampir setiap route/fungsi mengulang `get_db_connection → cursor → try/finally close`. Penanganan `RuntimeError` dari `get_db_connection`: `login`, `settings`, `profile` menangkapnya; `dashboard`, `journals`, `history`, `journal_photo`, `profile_photo`, dan seluruh API tidak (kecuali `/api/health`). [F]

**D-09 — Daftar jurnal ada di 5 query** — *Partial overlap* / *Similar appearance*; sedang
- `journals()` ≈ `api.student_journals`: kolom `journal_id, activity_date, title, description`, urutan `activity_date DESC` (API tanpa `journal_id DESC`). *Partial overlap tinggi*.
- `history()`, `get_journals_for_report`, `get_gallery_photos`: filter/kolom berbeda sesuai tujuan — *distinct responsibility*.

**D-10 — Aturan kata sandi/bcrypt tersebar** — *Partial overlap*; sedang
- `auth.login` (`checkpw`), `settings` (`checkpw`, `hashpw(gensalt())`, min 12, maks 72 byte), `create_student.py` (`hashpw(gensalt(rounds=12))`, min 12). Aturan "min 12" ditulis dua kali; batas 72 byte hanya di `settings`. [F]

**D-11 — Template daftar jurnal: tiga markup serupa** — *Similar appearance*; sedang
- `journals.html`, `history.html`, `reports.html` masing-masing merender blok tanggal (`strftime('%d')` + `'%b %Y'`), judul, kutipan deskripsi terpotong, dan tautan ke detail, dengan keluarga CSS terpisah (`.journals-*` 23, `.history-*` 46, `.report-journal*`). Apakah ini komponen yang sama secara fungsi masih perlu diselidiki.

**D-12 — Halaman error 403/404/500** — *Partial overlap*; sedang
- Tiga file ±72 baris yang berbeda hanya 18 (403↔404) dan 22 (404↔500) baris pada `diff`. [F]

**D-13 — CSS** — *Needs investigation*
- `student.css`: 748 blok selector, 698 unik; **50 selector didefinisikan lebih dari sekali** (mis. `.nav-link`, `.quick-link`, `.report-page`, `.report-export`, `.journal-photo-item`). Sebagian adalah lapisan override yang disengaja (bagian "ACTIVITY REPORTS - MOTION SYSTEM"), sebagian belum jelas. Juga teal: `style.css` (`--color-teal #247C83`, 56 pemakaian di student.css) vs `#0D9488` di `reports.html` dan `pdf_service` (0 di student.css) — dua warna aksen "teal". [F]
- Kelas CSS tanpa rujukan statis di template/JS/Python (23, setelah mengabaikan kelas dinamis seperti `dashboard-alert--*` dan `internship-status--*` yang dibangun dari variabel Jinja): `report-journal__description/__link/__metadata/__no-photos/__photos`, `report-photo-card`, `report-photo-gallery`, `coming-soon`, `nav-soon`, `nav-link--disabled`, `quick-link--disabled`, `edit-journal-alert(s)`. Ini [H] sampai diverifikasi di browser.

**D-14 — Referensi aset hilang** — *Defect factual (bukan duplikasi)*; tinggi
- `base_student.html:546–550`: blok `scripts` default memuat `js/settings.js`, namun `static/js/settings.js` **tidak ada** di repo (`git ls-files` dan `ls`). Halaman yang tidak menimpa blok itu — `history`, `journals`, `detail_journal`, `profile`, `settings` — memintanya. Kemungkinan 404 di browser [H], tidak diuji runtime.

**D-15 — Hal kecil terkait** *(Confirmed, rendah)*
- `pdf_service.py:40–42` mendefinisikan alias `CYAN`, `BLUE`, `PALE`; masing-masing hanya muncul sekali (definisinya).
- `app/utils/helpers.py` kosong (0 byte).
- Kategori flash `"warning"` (dipakai `delete_journal_route`) dipetakan ke kelas `info` oleh `base_student.html` (hanya `success`/`error` dikenali).
- Foto `gallery` dan statistik profil tidak disajikan oleh service yang sama dengan halaman lain (lihat D-04, D-09).

## 9. Dependency & Functional Relationship Map

```
Browser ──► auth.login ──► session[user_id, student_code, full_name]
        └─► student.* (student_required)
              dashboard ─────────► SQL langsung ─► journals
              journals / history ► SQL langsung ─► journals (+photos)
              add/edit/delete ───► journal_service ─► photo_service ─► disk (instance/uploads/journal_photos)
              detail/gallery ────► journal_service ─► journals, journal_photos
              journal_photo ─────► SQL langsung + disk
              reports ───────────► journal_service.get_journals_for_report
              reports/pdf ───────► journal_service + _get_report_student(users) ─► pdf_service ─► (foto dari disk)
              profile/settings ──► SQL langsung ─► users, student_profiles   (foto profil: disk instance/uploads/profile_photos)
API klien ─► api.* (X-API-Key) ─► SQL langsung ─► users, journals
Template: base_student.html ◄─ semua halaman siswa  (sidebar, flash, scripts block)
```

Ketergantungan fitur:
- Laporan (F11/F12) bergantung pada `get_journals_for_report` (kontrak field: `journal_id, activity_date, title, description, created_at, updated_at, photos[], photo_count`) yang dibaca oleh `reports.html` dan `pdf_service`.
- Edit/Create/Delete jurnal bergantung pada `photo_service` (batas 5 foto, ukuran, path) dan disk.
- Semua halaman bergantung pada `base_student.html` (navigasi, pesan flash, blok `scripts`, `main.js`, `nav-indicator.js`).
- Dashboard → Journals/Reports/Profile hanya tautan; tidak ada pemanggilan fungsi bersama.

## 10. Potential Simplification Areas

*(Hanya area untuk penyelidikan lanjutan; tidak ada rekomendasi penghapusan pada langkah ini.)*

1. **Jalur ganda profil** (D-01, D-02): jelaskan apakah `profile_details` dipakai di luar repo; validasi/upsert profil bisa disatukan, dan satu query statistik jelas berlebih.
2. **My Journals vs History** (D-03, N-1, N-2): tentukan kebutuhan fungsional masing-masing (hapus vs tambah/cari) sebelum menilai penyatuan; periksa dampak ke navigasi dan titik masuk "Tambah Jurnal".
3. **Statistik terpusat** (D-04): satu definisi "total jurnal / hari kegiatan / foto" untuk dashboard, profil, laporan, PDF, dan API.
4. **Lapisan service** (D-08, §6): SQL di route versus service; penanganan `RuntimeError` DB yang tidak seragam.
5. **Validasi bersama** (D-05, D-06, D-10): sumber tunggal untuk batas (5 foto/5 MB/150 karakter), aturan kata sandi, dan pemeriksaan rentang tanggal.
6. **Aset dan CSS** (D-13, D-14): referensi `settings.js` yang hilang; selector ganda dan kelas tanpa rujukan; dua warna teal; komponen daftar jurnal (D-11).
7. **Navigasi** (N-3, N-4, N-5, N-6): tautan berulang, status aktif untuk halaman turunan, ikon sama.
8. **Dokumentasi/tes**: tes hanya mencakup konfigurasi, error, header, gerbang login, login/logout, API; tidak ada tes untuk jurnal, laporan/PDF, profil, settings, galeri (lihat §11).

## 11. Audit Limitations

- **Tidak ada eksekusi terhadap MySQL sungguhan atau browser.** Semua temuan runtime (404 `settings.js`, perilaku halaman, hasil SQL) berasal dari pembacaan kode. Tes yang ada (34, lulus pada sandbox) memakai DB tiruan dan, menurut `IMPLEMENTATION_NOTES.md`, tidak membuktikan SQL, upload, PDF, atau alur browser.
- **Pembacaan tidak seluruhnya baris-per-baris:** `student.css` (7.080 baris) hanya dianalisis dengan skrip statistik selector/kelas; `profile.html` (637), `detail_journal.html` (603), `add_journal.html` (351), `login.html` (425), dan JS selain header/konstanta hanya di-grep, bukan dibaca penuh. `pdf_service.py` dibaca pada struktur, fungsi ringkasan, dan penggunaan field.
- **Deteksi CSS tak terpakai bersifat statis** (pencocokan nama di template/JS/Python); kelas dinamis dan aturan pewarisan bisa menyebabkan salah-positif/negatif.
- **Dokumen `catatan/`:** hanya tiga halaman pertama satu PDF (proposal FIELDLINK) yang diekstrak; PPTX dan PDF lain tidak dibaca. Hubungan ACTRACE–FIELDLINK adalah [H].
- **Teks label grup menu kedua** (`base_student.html:246`) dan isi `login.html`/`auth.css` tidak diperiksa mendalam.
- **Pemakai endpoint luar** (mis. FIELDLINK memanggil `/api/*`, atau klien memanggil `/profile/details`) tidak dapat diverifikasi dari repo.
- **Kondisi repo:** audit ini tidak mengubah repo. `git status` hanya menampilkan dua modifikasi *sebelumnya* (reports.html, journal_service.py). Folder `__pycache__` (diabaikan `.gitignore`) berasal dari eksekusi tes pada sandbox. Dependensi pengujian dipasang hanya di sandbox, bukan di proyek.

---

## Ringkasan Eksekutif

ACTRACE adalah aplikasi Flask monolitik server-rendered dengan satu peran (siswa), 15 route siswa, 2 route auth, 3 route API, dan 4 tabel MySQL. Alur inti jurnal (tambah/ubah/hapus, laporan PDF) sudah terstruktur di lapisan service; sisanya (profil, settings, dashboard, history, daftar jurnal, API) menulis SQL langsung di route.

Temuan paling kuat: (1) `profile_details` menduplikasi bagian dari `profile` POST dan tidak dirujuk template mana pun; (2) statistik profil dijalankan dua kali dengan SQL yang sama; (3) *My Journals* dan *Journal History* menampilkan data yang sama dengan fungsi berbeda (hapus vs cari/tambah), dan "Tambah Jurnal" hanya dapat dicapai dari History; (4) statistik ringkasan didefinisikan ulang di dashboard, API, profil, laporan, dan PDF; (5) `js/settings.js` direferensikan tetapi tidak ada di repo.

Perlu penyelidikan lanjutan: kebutuhan fungsional tiap halaman daftar jurnal, siapa yang memanggil `/profile/details` dan `/api/*`, struktur lapisan CSS (50 selector ganda, dua warna teal), serta cakupan tes yang belum menyentuh jurnal/laporan/profil. Tidak ada penghapusan yang direkomendasikan pada langkah ini.