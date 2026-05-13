import uuid
import os
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, session, send_from_directory
from werkzeug.security import generate_password_hash
from database import get_db, is_unique_constraint_error
from auth import admin_required

admin_bp = Blueprint('admin', __name__)
UPLOADS_DIR = os.environ.get(
    'UPLOADS_DIR',
    os.path.join(os.path.dirname(__file__), 'instance', 'uploads'),
)


def _remove_submission_files(file_names):
    for file_name in file_names:
        if not file_name:
            continue
        try:
            os.unlink(os.path.join(UPLOADS_DIR, file_name))
        except FileNotFoundError:
            continue
        except OSError:
            continue


@admin_bp.route('/users', methods=['GET'])
@admin_required
def list_users():
    with get_db() as conn:
        users = conn.execute(
            '''SELECT user_id, username, cohort_id, is_admin, created_at
               FROM users
               ORDER BY created_at DESC'''
        ).fetchall()
    return jsonify([dict(u) for u in users])


@admin_bp.route('/users', methods=['POST'])
@admin_required
def create_user():
    data = request.get_json()
    if not data or not data.get('username') or not data.get('password'):
        return jsonify({'error': 'Username and password are required'}), 400

    username = data['username'].strip()
    if not username:
        return jsonify({'error': 'Username cannot be blank'}), 400

    user_id = str(uuid.uuid4())
    password_hash = generate_password_hash(data['password'])
    cohort_id = data.get('cohort_id', '').strip()
    is_admin = 1 if data.get('is_admin') else 0
    created_at = datetime.now(timezone.utc).isoformat()

    try:
        with get_db() as conn:
            conn.execute(
                '''INSERT INTO users
                   (user_id, username, password_hash, cohort_id, is_admin, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                (user_id, username, password_hash, cohort_id, is_admin, created_at)
            )
        return jsonify({
            'user_id': user_id,
            'username': username,
            'cohort_id': cohort_id,
            'is_admin': bool(is_admin),
            'created_at': created_at,
        }), 201
    except Exception as e:
        if is_unique_constraint_error(e):
            return jsonify({'error': f"Username '{username}' already exists"}), 409
        return jsonify({'error': 'Failed to create user'}), 500


@admin_bp.route('/users/<user_id>', methods=['DELETE'])
@admin_required
def delete_user(user_id):
    # Prevent admins from deleting their own account
    if user_id == session.get('user_id'):
        return jsonify({'error': 'You cannot delete your own account'}), 400

    with get_db() as conn:
        user = conn.execute(
            'SELECT user_id, username FROM users WHERE user_id = ?', (user_id,)
        ).fetchone()

        if not user:
            return jsonify({'error': 'User not found'}), 404

        stored_files = [
            row['stored_filename']
            for row in conn.execute(
                'SELECT stored_filename FROM submissions WHERE user_id = ?',
                (user_id,)
            ).fetchall()
        ]

        # CASCADE in the schema handles deleting submissions automatically
        conn.execute('DELETE FROM users WHERE user_id = ?', (user_id,))

    _remove_submission_files(stored_files)

    return jsonify({'message': f"User '{user['username']}' and all associated data deleted"})


@admin_bp.route('/users/cohort/<cohort_id>', methods=['DELETE'])
@admin_required
def delete_cohort(cohort_id):
    """Delete all users in a cohort (and their submissions via CASCADE)."""
    cohort_id = cohort_id.strip()
    if not cohort_id:
        return jsonify({'error': 'Cohort ID is required'}), 400

    # Never delete the current admin's own account even if in the target cohort
    current_user_id = session.get('user_id')

    with get_db() as conn:
        users = conn.execute(
            'SELECT user_id FROM users WHERE cohort_id = ? AND user_id != ?',
            (cohort_id, current_user_id)
        ).fetchall()

        if not users:
            return jsonify({'error': f"No users found in cohort '{cohort_id}'"}), 404

        count = len(users)
        user_ids = [user['user_id'] for user in users]
        placeholders = ','.join('?' for _ in user_ids)
        stored_files = [
            row['stored_filename']
            for row in conn.execute(
                f'SELECT stored_filename FROM submissions WHERE user_id IN ({placeholders})',
                user_ids
            ).fetchall()
        ]
        conn.execute(
            'DELETE FROM users WHERE cohort_id = ? AND user_id != ?',
            (cohort_id, current_user_id)
        )

    _remove_submission_files(stored_files)

    return jsonify({'message': f"Deleted {count} user(s) from cohort '{cohort_id}'"})


@admin_bp.route('/users/<user_id>/submissions', methods=['GET'])
@admin_required
def list_user_submissions(user_id):
    with get_db() as conn:
        user = conn.execute(
            'SELECT user_id, username FROM users WHERE user_id = ?',
            (user_id,)
        ).fetchone()
        if not user:
            return jsonify({'error': 'User not found'}), 404

        rows = conn.execute(
            '''SELECT submission_id, original_filename, stored_filename,
                      duration_seconds, submission_source, status, error_message,
                      submitted_at
               FROM submissions
               WHERE user_id = ?
               ORDER BY submitted_at DESC''',
            (user_id,)
        ).fetchall()

    return jsonify({
        'user_id': user['user_id'],
        'username': user['username'],
        'submissions': [
            {
                'submission_id': row['submission_id'],
                'original_filename': row['original_filename'],
                'submitted_at': row['submitted_at'],
                'has_media': bool(row['stored_filename']),
                'duration_seconds': row['duration_seconds'],
                'submission_source': row['submission_source'],
                'status': row['status'],
                'error_message': row['error_message'],
            }
            for row in rows
        ],
    })


@admin_bp.route('/submissions/<submission_id>', methods=['GET'])
@admin_required
def get_submission(submission_id):
    with get_db() as conn:
        row = conn.execute(
            '''SELECT s.submission_id, s.original_filename, s.stored_filename,
                      s.duration_seconds, s.submission_source, s.status,
                      s.error_message,
                      s.transcript, s.feedback, s.submitted_at,
                      u.user_id, u.username
               FROM submissions s
               JOIN users u ON u.user_id = s.user_id
               WHERE s.submission_id = ?''',
            (submission_id,)
        ).fetchone()

    if not row:
        return jsonify({'error': 'Submission not found'}), 404

    return jsonify({
        'submission_id': row['submission_id'],
        'user_id': row['user_id'],
        'username': row['username'],
        'original_filename': row['original_filename'],
        'has_media': bool(row['stored_filename']),
        'duration_seconds': row['duration_seconds'],
        'submission_source': row['submission_source'],
        'status': row['status'],
        'error_message': row['error_message'],
        'transcript': row['transcript'],
        'feedback': row['feedback'],
        'submitted_at': row['submitted_at'],
    })


@admin_bp.route('/submissions/<submission_id>/media', methods=['GET'])
@admin_required
def get_submission_media(submission_id):
    with get_db() as conn:
        row = conn.execute(
            '''SELECT stored_filename, original_filename
               FROM submissions
               WHERE submission_id = ?''',
            (submission_id,)
        ).fetchone()

    if not row:
        return jsonify({'error': 'Submission not found'}), 404
    if not row['stored_filename']:
        return jsonify({'error': 'No stored media is available for this submission'}), 404

    file_path = os.path.join(UPLOADS_DIR, row['stored_filename'])
    if not os.path.exists(file_path):
        return jsonify({'error': 'Stored media file not found'}), 404

    return send_from_directory(
        UPLOADS_DIR,
        row['stored_filename'],
        as_attachment=False,
        download_name=row['original_filename'] or row['stored_filename'],
    )
