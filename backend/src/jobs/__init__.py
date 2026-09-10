"""Persistent, sequential exam-generation jobs (WP18 §2-§5).

Job state is JSON under the git-ignored ``artifacts/exam_jobs/<job_id>/`` tree --
never in ``app.db`` and never in Git. One worker processes one question at a
time, categories in canonical order, with no parallel provider calls. Generated
questions are session/job data only and are never inserted into the question DB.
"""
