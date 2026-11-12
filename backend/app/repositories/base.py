# backend/app/repositories/base.py
"""
Supabase client construction — the bottom of the data-access layer.

Why the clients live here and not in `services/supabase_client.py`
------------------------------------------------------------------
They used to be created in `app/services/supabase_client.py`, which also holds
~15 query helper functions. As repositories were introduced in B2 that created
a cycle:

    services/supabase_client  ->  repositories/conversation_repository
    repositories/conversation_repository  ->  services/supabase_client

Python can sometimes survive a cycle like that, but only if the modules happen
to be imported in one particular order — and the order here depends on which
route module FastAPI loads first. That is not a property worth betting a
container boot on.

Moving *client construction* (and only that) to the bottom of the layer removes
the cycle outright: repositories import from here, and `supabase_client`
re-exports these same objects so that the ~30 modules doing
`from app.services.supabase_client import supabase` keep working untouched.

The objects are identical — same constructor, same arguments, same order. This
is a relocation, not a change in how the clients are configured.

Import-order note
-----------------
`app.config` performs its own `load_dotenv()` at import, so the environment is
populated before `create_client` runs, exactly as it was when this code sat
below `supabase_client`'s own `load_dotenv()` call.
"""

from __future__ import annotations

import logging

from supabase import Client, create_client

from app import config
from app.config import SUPABASE_API_KEY, SUPABASE_URL

logger = logging.getLogger(__name__)

# Service-role key bypasses row-level security. Falls back to the anon key when
# it is not configured, which is the pre-existing behaviour — several services
# (fatca, pep, key_individuals, product_package, reference) import
# `supabase_service` unconditionally and would fail at import otherwise.
SUPABASE_SERVICE_KEY = config.SUPABASE_SERVICE_ROLE_KEY or SUPABASE_API_KEY

supabase: Client = create_client(SUPABASE_URL, SUPABASE_API_KEY)
supabase_service: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

__all__ = ["supabase", "supabase_service", "SUPABASE_SERVICE_KEY"]
