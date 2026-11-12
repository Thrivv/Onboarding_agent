"""
Data-access layer.

The only place in the application that talks to Supabase directly. Everything
above this layer calls named methods instead of building query chains inline.

Why this exists
---------------
Before Stage B2 there were 107 direct `supabase.table(...)` calls spread across
20 modules, and on the `users` table alone 29 distinct query shapes. A schema
change meant hunting through route handlers, and no business rule could be
tested without a live database.

Design rule — method per QUERY SHAPE, not per table
---------------------------------------------------
`.single()`, `.limit(1)`, `count="exact"` and different column sets return
materially different structures. Collapsing them into one method per table
would silently change behaviour at some call sites. Where two callers query the
same table differently, that difference is preserved as an explicit method or
an explicit argument — never smoothed over.
"""
