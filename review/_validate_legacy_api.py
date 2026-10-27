"""Obsolete (superseded by the pytest suite).

The legacy ``/cases`` API was removed together with the case/triage domain
(migration 0003).  Current API coverage lives in:

    tests/integration/test_api_case_flow.py   (batch/comments/jobs/UI)
    tests/unit/test_ingestion.py              (CSV parsing / validation)
    review/_validate_demo_api.py              (seed data -> read endpoints)
"""
