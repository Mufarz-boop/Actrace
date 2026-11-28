"""
Konstanta batasan aplikasi ACTRACE.

Satu-satunya tempat nilai batas ini didefinisikan. Backend (service dan
route) mengimpornya langsung; template dan JavaScript menerimanya melalui
context processor ``app_limits`` di ``app/__init__.py`` (atribut ``data-*``
pada form), sehingga tidak ada angka batas yang ditulis ulang.

Validasi di frontend hanya kemudahan bagi pengguna. Validasi backend tetap
menjadi penentu.
"""

# Foto jurnal
MAX_PHOTOS_PER_JOURNAL = 5
MAX_PHOTO_SIZE_MB = 5
MAX_PHOTO_SIZE_BYTES = MAX_PHOTO_SIZE_MB * 1024 * 1024

# Judul jurnal (karakter)
MAX_JOURNAL_TITLE_LENGTH = 150

# Kata sandi
MIN_PASSWORD_LENGTH = 12  # karakter

# bcrypt hanya memproses 72 byte pertama. Batas ini dihitung pada byte
# UTF-8 (len(password.encode("utf-8"))), bukan jumlah karakter.
BCRYPT_MAX_PASSWORD_BYTES = 72
