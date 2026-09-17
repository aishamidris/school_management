"""Shared helper for saving user-uploaded profile photos.

Photos are written to app/static/uploads/profile_photos/ and referenced
on the model by their path relative to the static folder (e.g.
"uploads/profile_photos/xyz.jpg"), the same convention Student.photo_path
already used before this feature existed.

Note for deployers: on a free-tier host with no persistent disk (see
DEMO_DEPLOYMENT.md), anything saved here is wiped on the next restart or
redeploy, same as the SQLite database. For a real school's data, deploy
with persistent storage (DEPLOYMENT.md) or point this at object storage.
"""
import os
import uuid
from flask import current_app
from werkzeug.utils import secure_filename

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
MAX_PHOTO_BYTES = 3 * 1024 * 1024  # 3 MB — generous for a headshot, small enough to keep pages fast


def _allowed(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_profile_photo(file_storage, old_relative_path=None):
    """Validate and save an uploaded photo. Returns the new relative path
    (to store on the model) or raises ValueError with a user-facing message.

    Deletes the previous photo file (if any) once the new one is saved,
    so we don't accumulate orphaned files across repeated re-uploads.
    """
    if not file_storage or not file_storage.filename:
        raise ValueError("Choose an image file first.")

    filename = secure_filename(file_storage.filename)
    if not _allowed(filename):
        raise ValueError("Please upload a PNG, JPG, GIF, or WEBP image.")

    file_storage.seek(0, os.SEEK_END)
    size = file_storage.tell()
    file_storage.seek(0)
    if size > MAX_PHOTO_BYTES:
        raise ValueError("Image is too large — please use one under 3 MB.")

    ext = filename.rsplit(".", 1)[1].lower()
    unique_name = f"{uuid.uuid4().hex}.{ext}"

    upload_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], "profile_photos")
    os.makedirs(upload_dir, exist_ok=True)

    dest_path = os.path.join(upload_dir, unique_name)
    file_storage.save(dest_path)

    relative_path = f"uploads/profile_photos/{unique_name}"

    if old_relative_path:
        _delete_photo(old_relative_path)

    return relative_path


def _delete_photo(relative_path):
    """relative_path looks like 'uploads/profile_photos/xxx.jpg'; UPLOAD_FOLDER
    already points at .../app/static/uploads, so strip the leading 'uploads/'."""
    try:
        full_path = os.path.join(current_app.config["UPLOAD_FOLDER"], os.path.relpath(relative_path, "uploads"))
        if os.path.isfile(full_path):
            os.remove(full_path)
    except OSError:
        pass  # best-effort cleanup only — never block the request on this
