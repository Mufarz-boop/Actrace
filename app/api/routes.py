from flask import jsonify
from app.api import api_bp
from app.api.authentication import shared_key_required
from app.db import get_db_connection
from app.services.stats_service import get_student_stats

@api_bp.get("/health")
def health():
    try:
        conn = get_db_connection()
        conn.close()
        return jsonify({"success": True, "service": "ACTRACE", "database": "connected"})
    except RuntimeError:
        return jsonify({"success": False, "service": "ACTRACE", "database": "unavailable"}), 503

@api_bp.get("/students/<string:student_code>/summary")
@shared_key_required
def student_summary(student_code):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT user_id, student_code, full_name FROM users WHERE student_code=%s", (student_code,))
        student = cur.fetchone()
        if not student:
            return jsonify({"success": False, "message": "Siswa tidak ditemukan."}), 404
        stats = get_student_stats(student["user_id"], cursor=cur)
        latest = None
        if stats["latest_activity"] is not None:
            latest = {
                "activity_date": stats["latest_activity"].isoformat(),
                "title": stats["latest_title"],
            }
        return jsonify({"success": True, "student": student, "total_journals": stats["total_journals"], "latest_activity": latest})
    finally:
        cur.close()
        conn.close()

@api_bp.get("/students/<string:student_code>/journals")
@shared_key_required
def student_journals(student_code):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT user_id FROM users WHERE student_code=%s", (student_code,))
        student = cur.fetchone()
        if not student:
            return jsonify({"success": False, "message": "Siswa tidak ditemukan."}), 404
        cur.execute(
            "SELECT journal_id, activity_date, title, description FROM journals WHERE user_id=%s ORDER BY activity_date DESC",
            (student["user_id"],),
        )
        rows = cur.fetchall()
        for row in rows:
            row["activity_date"] = row["activity_date"].isoformat()
        return jsonify({"success": True, "student_code": student_code, "journals": rows})
    finally:
        cur.close()
        conn.close()