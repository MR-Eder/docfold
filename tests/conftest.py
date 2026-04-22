"""Pytest plumbing for docfold tests.

M4: APIKeyMiddleware refuses to boot without keys unless
``PIPELINE_ALLOW_NO_AUTH=1`` is set. API tests boot the app without
configuring auth (they exercise routes, not the auth layer), so opt
into the dev-mode open path here. Set at import time so the env var is
present *before* any docfold module loads.
"""

from __future__ import annotations

import os

os.environ.setdefault("PIPELINE_ALLOW_NO_AUTH", "1")
