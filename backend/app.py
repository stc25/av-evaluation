import os
import logging
from flask import Flask, send_from_directory, jsonify
from flask_cors import CORS
from database import init_db
from auth import auth_bp
from admin import admin_bp
from upload import upload_bp

def _env_flag(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {'1', 'true', 'yes', 'on'}


def _get_log_level() -> int:
    raw_level = os.environ.get('APP_LOG_LEVEL', 'INFO').strip().upper()
    return getattr(logging, raw_level, logging.INFO)


logging.basicConfig(
    level=_get_log_level(),
    format='%(asctime)s %(levelname)s %(name)s: %(message)s',
)

FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'frontend'))
APP_DEBUG = _env_flag('APP_DEBUG', False)

ALLOWED_ORIGINS = os.environ.get(
    'ALLOWED_ORIGINS',
    'http://localhost:8080,http://127.0.0.1:8080'
).split(',')


def create_app():
    app = Flask(__name__)

    app.config['DEBUG'] = APP_DEBUG
    app.config['PROPAGATE_EXCEPTIONS'] = APP_DEBUG
    app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-change-in-production')
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['SESSION_COOKIE_SECURE'] = (
        os.environ.get('SESSION_COOKIE_SECURE', 'false').lower() == 'true'
    )
    # Set a reasonable session lifetime (8 hours)
    app.config['PERMANENT_SESSION_LIFETIME'] = 28800
    # Global cap — the per-type check in upload.py enforces the stricter MP3 limit
    app.config['MAX_CONTENT_LENGTH'] = 305 * 1024 * 1024  # 305 MB headroom

    CORS(app, supports_credentials=True, origins=ALLOWED_ORIGINS)

    with app.app_context():
        init_db()

    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(admin_bp, url_prefix='/api/admin')
    app.register_blueprint(upload_bp, url_prefix='/api')

    # Return JSON (not Flask's default HTML) when a file exceeds MAX_CONTENT_LENGTH.
    @app.errorhandler(413)
    def request_too_large(_e):
        return jsonify({
            'error': 'File too large. MP4 files must be under 300 MB; MP3 files under 30 MB.'
        }), 413

    # Minimal security headers for every response.
    @app.after_request
    def add_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        return response

    # Serve the frontend from the same origin as the API so that session
    # cookies work without any cross-origin restrictions.
    @app.route('/')
    def serve_index():
        return send_from_directory(FRONTEND_DIR, 'index.html')

    @app.route('/<path:filename>')
    def serve_static(filename):
        return send_from_directory(FRONTEND_DIR, filename)

    return app


if __name__ == '__main__':
    app = create_app()
    # threaded=True lets the dev server handle multiple connections concurrently
    # (e.g. loading static assets while a transcription is in progress).
    app.run(
        host='0.0.0.0',
        port=int(os.environ.get('PORT', '8080')),
        debug=APP_DEBUG,
        use_reloader=APP_DEBUG,
        threaded=True,
    )
