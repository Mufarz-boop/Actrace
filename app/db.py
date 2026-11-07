
import mysql.connector
from flask import current_app


def get_db_connection():
    try:
        return mysql.connector.connect(
            host=current_app.config["DB_HOST"],
            port=current_app.config["DB_PORT"],
            user=current_app.config["DB_USER"],
            password=current_app.config["DB_PASSWORD"],
            database=current_app.config["DB_NAME"],
            charset="utf8",
            connection_timeout=8,
        )

    except mysql.connector.Error as exc:
        current_app.logger.exception(
            "Koneksi MySQL ACTRACE gagal"
        )

        raise RuntimeError(
            "Database ACTRACE tidak tersedia."
        ) from exc