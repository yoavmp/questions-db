"""Optional DB-question exclusion workbook: local preview endpoint (WP26 §2).

Local, non-provider, no persistence of the uploaded bytes: parses the
workbook in memory, resolves it against the current question database, and
returns only safe preview metadata. Actual job creation independently
revalidates every id against the DB again (see ``src.jobs.service.create_job``
/ ``src.jobs.exclusions.revalidate_ids``) -- this endpoint never itself
creates or mutates anything.
"""

from flask import Blueprint, jsonify, request

from src.jobs.exclusions import ExclusionParseError, parse_and_resolve

exclusion_bp = Blueprint('exclusion', __name__)


@exclusion_bp.route('/exam-jobs/exclusions/preview', methods=['POST'])
def preview_exclusion_file():
    if 'file' not in request.files:
        return jsonify({"error": "לא נבחר קובץ"}), 400
    file = request.files['file']
    if not file.filename:
        return jsonify({"error": "לא נבחר קובץ"}), 400

    file_bytes = file.read()
    try:
        preview = parse_and_resolve(file_bytes, file.filename)
    except ExclusionParseError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(preview.to_dict())
