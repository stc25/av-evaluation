import os
import sqlite3
from urllib.parse import unquote, urlparse

DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), 'instance', 'app.db')
DATABASE_URL = os.environ.get('DATABASE_URL', '').strip()
DB_PATH = os.environ.get('APP_DB_PATH', DEFAULT_DB_PATH)


class DBConnection:
    def __init__(self, backend, conn):
        self.backend = backend
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, _tb):
        try:
            if exc_type is None:
                self.conn.commit()
            else:
                self.conn.rollback()
        finally:
            self.conn.close()

    def execute(self, query, params=()):
        if self.backend == 'mariadb':
            query = _translate_query(query)
            cursor = self.conn.cursor()
            cursor.execute(query, params or ())
            return cursor

        cursor = self.conn.execute(query, params or ())
        return cursor


def _is_mariadb_url():
    return DATABASE_URL.startswith('mariadb://') or DATABASE_URL.startswith('mysql://')


def _translate_query(query):
    return query.replace('?', '%s')


def _get_sqlite_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return DBConnection('sqlite', conn)


def _get_mariadb_db():
    try:
        import pymysql
    except ImportError as exc:
        raise RuntimeError('PyMySQL is required for MariaDB support') from exc

    parsed = urlparse(DATABASE_URL)
    db_name = parsed.path.lstrip('/')
    conn = pymysql.connect(
        host=parsed.hostname or 'mariadb',
        port=parsed.port or 3306,
        user=unquote(parsed.username or ''),
        password=unquote(parsed.password or ''),
        database=db_name,
        charset='utf8mb4',
        autocommit=False,
        cursorclass=pymysql.cursors.DictCursor,
    )
    return DBConnection('mariadb', conn)


def get_db():
    if _is_mariadb_url():
        return _get_mariadb_db()
    return _get_sqlite_db()


def init_db():
    if _is_mariadb_url():
        _init_mariadb()
    else:
        _init_sqlite()


def _init_sqlite():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_db() as conn:
        conn.execute(
            '''CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                cohort_id TEXT NOT NULL DEFAULT '',
                is_admin INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )'''
        )
        conn.execute(
            '''CREATE TABLE IF NOT EXISTS submissions (
                submission_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                original_filename TEXT NOT NULL DEFAULT '',
                stored_filename TEXT NOT NULL DEFAULT '',
                duration_seconds REAL NOT NULL DEFAULT 0,
                submission_source TEXT NOT NULL DEFAULT 'upload',
                transcript TEXT,
                feedback TEXT,
                submitted_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )'''
        )
        _ensure_submission_columns_sqlite(conn)


def _init_mariadb():
    with get_db() as conn:
        conn.execute(
            '''CREATE TABLE IF NOT EXISTS users (
                user_id VARCHAR(36) PRIMARY KEY,
                username VARCHAR(255) NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                cohort_id VARCHAR(255) NOT NULL DEFAULT '',
                is_admin TINYINT(1) NOT NULL DEFAULT 0,
                created_at VARCHAR(64) NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4'''
        )
        conn.execute(
            '''CREATE TABLE IF NOT EXISTS submissions (
                submission_id VARCHAR(36) PRIMARY KEY,
                user_id VARCHAR(36) NOT NULL,
                original_filename VARCHAR(255) NOT NULL DEFAULT '',
                stored_filename VARCHAR(255) NOT NULL DEFAULT '',
                duration_seconds DOUBLE NOT NULL DEFAULT 0,
                submission_source VARCHAR(32) NOT NULL DEFAULT 'upload',
                transcript LONGTEXT NULL,
                feedback LONGTEXT NULL,
                submitted_at VARCHAR(64) NOT NULL,
                CONSTRAINT fk_submissions_user
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4'''
        )
        _ensure_submission_columns_mariadb(conn)


def _ensure_submission_columns_sqlite(conn):
    columns = {
        row['name']
        for row in conn.execute('PRAGMA table_info(submissions)').fetchall()
    }
    if 'original_filename' not in columns:
        conn.execute(
            "ALTER TABLE submissions ADD COLUMN original_filename TEXT NOT NULL DEFAULT ''"
        )
    if 'stored_filename' not in columns:
        conn.execute(
            "ALTER TABLE submissions ADD COLUMN stored_filename TEXT NOT NULL DEFAULT ''"
        )
    if 'duration_seconds' not in columns:
        conn.execute(
            'ALTER TABLE submissions ADD COLUMN duration_seconds REAL NOT NULL DEFAULT 0'
        )
    if 'submission_source' not in columns:
        conn.execute(
            "ALTER TABLE submissions ADD COLUMN submission_source TEXT NOT NULL DEFAULT 'upload'"
        )


def _ensure_submission_columns_mariadb(conn):
    rows = conn.execute(
        '''SELECT COLUMN_NAME
           FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE()
             AND TABLE_NAME = 'submissions' '''
    ).fetchall()
    columns = {row['COLUMN_NAME'] for row in rows}

    if 'original_filename' not in columns:
        conn.execute(
            "ALTER TABLE submissions ADD COLUMN original_filename VARCHAR(255) NOT NULL DEFAULT ''"
        )
    if 'stored_filename' not in columns:
        conn.execute(
            "ALTER TABLE submissions ADD COLUMN stored_filename VARCHAR(255) NOT NULL DEFAULT ''"
        )
    if 'duration_seconds' not in columns:
        conn.execute(
            'ALTER TABLE submissions ADD COLUMN duration_seconds DOUBLE NOT NULL DEFAULT 0'
        )
    if 'submission_source' not in columns:
        conn.execute(
            "ALTER TABLE submissions ADD COLUMN submission_source VARCHAR(32) NOT NULL DEFAULT 'upload'"
        )


def is_unique_constraint_error(exc):
    message = str(exc)
    return (
        'UNIQUE constraint failed' in message
        or 'Duplicate entry' in message
        or 'IntegrityError' in message and 'username' in message.lower()
    )
