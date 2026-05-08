from functools import wraps
from flask import Blueprint, request, jsonify, session
from werkzeug.security import check_password_hash
from database import get_db

auth_bp = Blueprint('auth', __name__)


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Authentication required'}), 401
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Authentication required'}), 401
        if not session.get('is_admin'):
            return jsonify({'error': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated


@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    if not data or not data.get('username') or not data.get('password'):
        return jsonify({'error': 'Username and password are required'}), 400

    with get_db() as conn:
        user = conn.execute(
            'SELECT * FROM users WHERE username = ?', (data['username'],)
        ).fetchone()

    if not user or not check_password_hash(user['password_hash'], data['password']):
        return jsonify({'error': 'Invalid username or password'}), 401

    session.clear()
    session.permanent = True  # Honour PERMANENT_SESSION_LIFETIME (8 hours).
    session['user_id'] = user['user_id']
    session['username'] = user['username']
    session['is_admin'] = bool(user['is_admin'])

    return jsonify({
        'user_id': user['user_id'],
        'username': user['username'],
        'is_admin': bool(user['is_admin']),
    })


@auth_bp.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'message': 'Logged out successfully'})


@auth_bp.route('/me', methods=['GET'])
def me():
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    return jsonify({
        'user_id': session['user_id'],
        'username': session['username'],
        'is_admin': session.get('is_admin', False),
    })
