"""
Statistik siswa yang dipakai bersama oleh beberapa fitur.

- ``get_student_stats``: statistik seluruh waktu milik satu siswa
  (Dashboard, My Profile, dan API ``student_summary``).
- ``summarize_journal_period``: ringkasan dari daftar jurnal pada satu
  periode (halaman Reports dan PDF). Fungsi murni tanpa akses database.
"""

from app.db import get_db_connection


# Satu query untuk seluruh statistik seluruh waktu. Kondisi filter
# ``j.user_id`` dipakai pada query utama dan subquery judul terakhir.
# Agregat tanpa GROUP BY selalu menghasilkan tepat satu baris, juga untuk
# siswa tanpa jurnal (hitungan 0, tanggal dan judul NULL).
_STUDENT_STATS_SQL = """
    SELECT
        COUNT(DISTINCT j.journal_id) AS total_journals,
        COUNT(DISTINCT jp.photo_id) AS total_photos,
        MAX(j.activity_date) AS latest_activity,
        (
            SELECT l.title
            FROM journals AS l
            WHERE l.user_id = %s
            ORDER BY l.activity_date DESC, l.journal_id DESC
            LIMIT 1
        ) AS latest_title
    FROM journals AS j
    LEFT JOIN journal_photos AS jp
        ON jp.journal_id = j.journal_id
    WHERE j.user_id = %s
"""


def _fetch_student_stats(cursor, user_id):
    cursor.execute(_STUDENT_STATS_SQL, (user_id, user_id))
    row = cursor.fetchone() or {}

    return {
        "total_journals": int(row.get("total_journals") or 0),
        "total_photos": int(row.get("total_photos") or 0),
        "latest_activity": row.get("latest_activity"),
        "latest_title": row.get("latest_title"),
    }


def get_student_stats(user_id, cursor=None):
    """
    Statistik seluruh waktu untuk satu siswa.

    Mengembalikan dict dengan kunci:
    - total_journals (int)
    - total_photos (int)
    - latest_activity (date atau None): tanggal aktivitas terbaru
    - latest_title (str atau None): judul jurnal terbaru
      (urut activity_date, lalu journal_id, menurun)

    ``cursor`` (opsional, cursor ``dictionary=True``): bila diberikan,
    query dijalankan lewat cursor tersebut sehingga pemanggil yang sudah
    memegang koneksi tidak perlu membuka koneksi kedua. Pemanggil tetap
    bertanggung jawab menutup cursor dan koneksinya. Tanpa ``cursor``,
    fungsi membuka dan menutup koneksinya sendiri.

    Error database tidak ditangkap di sini; pemanggil menanganinya sesuai
    konteks masing-masing (redirect, JSON, atau halaman error 500).
    """
    if cursor is not None:
        return _fetch_student_stats(cursor, user_id)

    connection = get_db_connection()
    own_cursor = None

    try:
        own_cursor = connection.cursor(dictionary=True)
        return _fetch_student_stats(own_cursor, user_id)
    finally:
        if own_cursor:
            own_cursor.close()

        connection.close()


def summarize_journal_period(journals):
    """
    Ringkasan dari daftar jurnal (hasil ``get_journals_for_report``).

    Mengembalikan dict: total_journals, total_activity_days (jumlah tanggal
    unik), dan total_photos. Jumlah foto dihitung dari daftar ``photos``;
    bila seluruhnya kosong, memakai ``photo_count``.
    """
    activity_days = {
        str(journal.get("activity_date"))[:10]
        for journal in journals
        if journal.get("activity_date") is not None
    }

    total_photos = sum(
        len(journal.get("photos") or []) for journal in journals
    )

    if not total_photos:
        total_photos = sum(
            _safe_int(journal.get("photo_count")) for journal in journals
        )

    return {
        "total_journals": len(journals),
        "total_activity_days": len(activity_days),
        "total_photos": total_photos,
    }


def _safe_int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
