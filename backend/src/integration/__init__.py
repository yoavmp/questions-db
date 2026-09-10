"""Outer-project integration foundation for the pinned exam generator.

This package holds the OFFLINE integration contracts established in WP17. It
never imports generator code at module import time and never makes a provider
call on its own. Everything here lives in the ``questions-db`` repository, not
in the ``exam_generator`` submodule.

Modules:
    category_map      -- canonical category <-> pinned generator context binding
    owner_policy      -- owner integration policy constants (attempts, cost cap)
    request_contract  -- per-category {total, database, llm} request contract
    exam_question_dto -- backend exam-question DTO (seven public fields + meta)
    generator_adapter -- read-only adapter that composes the pinned generator's
                         published one-question primitives
"""
