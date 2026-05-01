create table if not exists public.passcodes (
  id bigint generated always as identity primary key,
  username text not null,
  passcode text not null,
  telegram_user_id bigint,
  expires_at timestamptz not null,
  used boolean not null default false,
  created_at timestamptz not null default now()
);

create index if not exists passcodes_lookup_idx
  on public.passcodes (username, passcode, used);

alter table public.passcodes enable row level security;

create policy "Allow site to read unused passcodes"
  on public.passcodes
  for select
  to anon
  using (used = false and expires_at > now());

create policy "Allow bot to create passcodes"
  on public.passcodes
  for insert
  to anon
  with check (used = false and expires_at > now());

create policy "Allow site to mark passcodes used"
  on public.passcodes
  for update
  to anon
  using (used = false and expires_at > now())
  with check (used = true);
