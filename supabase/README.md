# Database migrations

This project's schema was previously tracked as a single ad-hoc file
(`backend/db_migration_ref_no.sql`), with no record of what had already been
applied to which environment. That made it hard to reconstruct or reproduce
schema history — a fresh environment (or a teammate's local Supabase project)
had no reliable way to know it needed that file, or in what order further
schema changes should apply.

This directory adopts the standard [Supabase CLI migration
convention](https://supabase.com/docs/guides/deployment/database-migrations)
instead of inventing a custom one: every schema change is a numbered,
timestamped SQL file in `supabase/migrations/`, applied in filename order.

## Applying migrations

With the [Supabase CLI](https://supabase.com/docs/guides/cli) installed and
linked to your project (`supabase link --project-ref <ref>`):

```bash
supabase db push
```

For local development against the Supabase CLI's local stack:

```bash
supabase start
supabase db reset   # applies every migration in order, from a clean local DB
```

## Adding a new migration

```bash
supabase migration new <short_description>
```

This creates a new timestamped file in `supabase/migrations/` — put the SQL
for your change there. Do not edit a migration that has already been applied
to a shared environment; add a new one instead, the same way you would with
any other migration tool.

## What's here so far

- `20250601000000_add_ref_no_to_users.sql` — adds the `ref_no` column and
  index on `public.users` (moved from `backend/db_migration_ref_no.sql`,
  content unchanged).
