import bcrypt

from app import create_app
from app.constants import MIN_PASSWORD_LENGTH
from app.db import get_db_connection


def create_student():
    app = create_app()

    print("\n================================")
    print("       ACTRACE ACCOUNT SETUP")
    print("================================\n")

    # Student information
    student_code = input("Student Code : ").strip()
    full_name = input("Full Name    : ").strip()
    username = input("Username     : ").strip()
    email = input("Email        : ").strip()

    # Password input (visible)
    password = input("Password     : ")
    confirm = input("Confirm      : ")

    # Validate required fields
    if not all([
        student_code,
        full_name,
        username,
        email,
        password
    ]):
        print("\n[ERROR] Semua kolom wajib diisi.")
        return

    # Validate password confirmation
    if password != confirm:
        print("\n[ERROR] Password tidak cocok.")
        return

    # Validate password length
    if len(password) < MIN_PASSWORD_LENGTH:
        print(f"\n[ERROR] Password minimal {MIN_PASSWORD_LENGTH} karakter.")
        return

    # Generate bcrypt hash
    try:
        password_hash = bcrypt.hashpw(
            password.encode("utf-8"),
            bcrypt.gensalt(rounds=12)
        ).decode("utf-8")

    except Exception:
        print("\n[ERROR] Gagal memproses password.")
        return

    conn = None
    cur = None

    try:
        with app.app_context():

            conn = get_db_connection()
            cur = conn.cursor()

            cur.execute(
                """
                INSERT INTO users (
                    student_code,
                    full_name,
                    username,
                    email,
                    password_hash
                )
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    student_code,
                    full_name,
                    username,
                    email,
                    password_hash
                )
            )

            conn.commit()

        print("\n================================")
        print("[SUCCESS] AKUN BERHASIL DIBUAT")
        print("================================")
        print(f"Student Code : {student_code}")
        print(f"Full Name    : {full_name}")
        print(f"Username     : {username}")
        print(f"Email        : {email}")
        print("Password     : [TERSIMPAN SEBAGAI HASH]")
        print("================================\n")

    except Exception:
        if conn:
            conn.rollback()

        print("\n[ERROR] Gagal membuat akun.")
        print("Kemungkinan username, email, atau student code sudah digunakan.")
        print("Periksa juga koneksi database ACTRACE.")

    finally:
        if cur:
            cur.close()

        if conn:
            conn.close()


if __name__ == "__main__":
    create_student()