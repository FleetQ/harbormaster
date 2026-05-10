"""Screenshot-diff harness (v13.0.0a1).

Closes the v9.0.0a1 deferral: every PR that touches templates can now
run `pytest tests/ui/_screenshot_diff/ -v` and get explicit failures
with diff images, so the long-pending Tailwind utility migration
becomes safe in v13.0.0a2.

Opt-in via `pytest -m browser` — same gate as the v3.0.0a10 browser
smoke suite. Skipped by default so the regular test suite doesn't need
Playwright + chromium installed.
"""
