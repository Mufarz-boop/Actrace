# ACTRACE - Journal Detail & Edit Journal

## Implementasi
- Menambahkan route GET/POST `/journals/<journal_id>/edit`.
- Menggunakan kembali `get_journal_detail()` untuk mengambil jurnal dan foto dengan validasi kepemilikan.
- Menambahkan `update_journal()` pada journal service dengan transaksi MySQL, penguncian baris jurnal/foto, validasi data, dan pembaruan metadata.
- Pengelolaan foto: mempertahankan foto lama secara default, menghapus foto yang dipilih, dan menambahkan foto baru. Batas gabungan tetap 5 foto, maksimal 5 MB per foto, format aktual JPEG/PNG/WEBP diverifikasi dengan Pillow.
- File foto lama baru dihapus secara fisik setelah transaksi database berhasil. Path dibatasi ke direktori upload.
- Menambahkan halaman edit dan JavaScript preview/interaksi.
- Menambahkan tautan detail yang jelas pada daftar jurnal.
- Tidak ada perubahan skema database.

## File yang diubah
- `app/services/photo_service.py`
- `app/services/journal_service.py`
- `app/student/routes.py`
- `templates/student/edit_journal.html` (baru)
- `templates/student/detail_journal.html`
- `templates/student/journals.html`
- `static/js/edit_journal.js` (baru)
- `static/css/student.css`

## Pengujian yang dilakukan
- Pemeriksaan sintaks Python dengan `py_compile`: berhasil.
- Pemeriksaan sintaks JavaScript dengan `node --check`: berhasil.
- Parsing template Jinja untuk halaman edit, detail, dan daftar jurnal: berhasil.
- Pengujian integrasi MySQL dan alur browser tidak dapat dijalankan pada lingkungan ini karena dependensi Flask/MySQL dan server database aplikasi tidak tersedia. Karena itu, hasil integrasi runtime belum dinyatakan lulus.

## Menjalankan
1. Ekstrak arsip.
2. Buat/aktifkan virtual environment dan pasang dependensi: `pip install -r requirements.txt`.
3. Salin `.env.example` menjadi `.env`, lalu isi konfigurasi database, `SECRET_KEY`, dan `SHARED_API_KEY` sesuai lingkungan lokal.
4. Pastikan database ACTRACE dan tabel pada `database/schema.sql` sudah tersedia.
5. Jalankan `python run.py`.

Catatan keamanan: file `.env`, direktori `.git`, dan virtual environment tidak disertakan dalam arsip hasil. Buat `.env` lokal dari `.env.example`; jangan membagikan kredensial.
