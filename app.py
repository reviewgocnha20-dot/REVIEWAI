
-- =========================================================
-- BAP AI VIDEO - SUPABASE DATABASE SCHEMA
-- Phiên bản đã chỉnh sửa: hỗ trợ chạy lại và thời lượng 10/20/30/40s
-- =========================================================

-- 1. BẬT EXTENSION
create extension if not exists "pgcrypto";

-- =========================================================
-- 2. ENUM TRẠNG THÁI VIDEO JOB
-- =========================================================

do $$
begin
    create type public.video_job_status as enum (
        'queued',
        'analyzing_product',
        'writing_script',
        'generating_voice',
        'generating_character',
        'generating_scenes',
        'syncing_lips',
        'merging_video',
        'quality_checking',
        'saving_video',
        'completed',
        'needs_review',
        'failed'
    );
exception
    when duplicate_object then null;
end
$$;

-- Bổ sung các trạng thái còn thiếu nếu enum đã tồn tại
alter type public.video_job_status add value if not exists 'queued';
alter type public.video_job_status add value if not exists 'analyzing_product';
alter type public.video_job_status add value if not exists 'writing_script';
alter type public.video_job_status add value if not exists 'generating_voice';
alter type public.video_job_status add value if not exists 'generating_character';
alter type public.video_job_status add value if not exists 'generating_scenes';
alter type public.video_job_status add value if not exists 'syncing_lips';
alter type public.video_job_status add value if not exists 'merging_video';
alter type public.video_job_status add value if not exists 'quality_checking';
alter type public.video_job_status add value if not exists 'saving_video';
alter type public.video_job_status add value if not exists 'completed';
alter type public.video_job_status add value if not exists 'needs_review';
alter type public.video_job_status add value if not exists 'failed';

-- =========================================================
-- 3. VIDEO PROJECTS
-- =========================================================

create table if not exists public.video_projects (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    parent_project_id uuid references public.video_projects(id) on delete set null,

    project_name text not null,
    product_url text,
    product_name text not null,
    product_image_url text not null,
    product_category text,

    verified_product_facts jsonb not null default '{}'::jsonb,

    target_duration_sec int not null,
    aspect_ratio text not null default '9:16',

    review_style text not null,

    character_config jsonb not null default '{}'::jsonb,
    voice_config jsonb not null default '{}'::jsonb,
    script_json jsonb,

    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- Chuẩn hóa giới hạn thời lượng kể cả khi bảng đã tồn tại
alter table public.video_projects
    drop constraint if exists video_projects_target_duration_sec_check;

alter table public.video_projects
    add constraint video_projects_target_duration_sec_check
    check (target_duration_sec in (10, 20, 30, 40));

alter table public.video_projects
    drop constraint if exists video_projects_aspect_ratio_check;

alter table public.video_projects
    add constraint video_projects_aspect_ratio_check
    check (aspect_ratio in ('9:16', '16:9', '1:1'));

-- =========================================================
-- 4. VIDEO JOBS
-- =========================================================

create table if not exists public.video_jobs (
    id uuid primary key default gen_random_uuid(),

    user_id uuid not null references auth.users(id) on delete cascade,
    project_id uuid not null references public.video_projects(id) on delete cascade,

    idempotency_key text not null,

    status public.video_job_status not null default 'queued',
    current_stage_label text not null default 'Đang trong hàng đợi',

    provider_progress_percent int
        check (provider_progress_percent between 0 and 100),

    scenes_completed int not null default 0,
    scenes_total int not null default 0,

    estimated_credits numeric(10,2) not null default 0,
    used_credits numeric(10,2) not null default 0,
    stage_costs_usd jsonb not null default '{}'::jsonb,

    failed_stage text,
    error_code text,
    error_message text,

    retry_count int not null default 0,
    max_retries int not null default 3,

    locked_by_worker text,
    locked_at timestamptz,
    timeout_at timestamptz,

    started_at timestamptz not null default now(),
    completed_at timestamptz,

    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),

    constraint video_jobs_user_idempotency_unique
        unique(user_id, idempotency_key)
);

-- =========================================================
-- 5. VIDEO SCENES
-- =========================================================

create table if not exists public.video_scenes (
    id uuid primary key default gen_random_uuid(),

    user_id uuid not null references auth.users(id) on delete cascade,
    job_id uuid not null references public.video_jobs(id) on delete cascade,

    scene_index int not null,
    duration_sec numeric(5,2) not null,

    dialogue_text text not null,
    action_direction text not null,
    camera_framing text not null,

    needs_lipsync boolean not null default false,

    provider_name text,
    provider_request_id text,
    provider_temp_video_url text,

    audio_storage_path text,
    raw_video_storage_path text,
    synced_video_storage_path text,

    status text not null default 'pending'
        check (
            status in (
                'pending',
                'generating',
                'syncing',
                'qc_passed',
                'qc_failed',
                'failed'
            )
        ),

    qc_report jsonb not null default '{}'::jsonb,
    error_message text,

    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),

    constraint video_scenes_job_scene_unique
        unique(job_id, scene_index)
);

-- =========================================================
-- 6. VIDEO ASSETS
-- =========================================================

create table if not exists public.video_assets (
    id uuid primary key default gen_random_uuid(),

    user_id uuid not null references auth.users(id) on delete cascade,

    project_id uuid references public.video_projects(id) on delete cascade,
    job_id uuid references public.video_jobs(id) on delete cascade,
    scene_id uuid references public.video_scenes(id) on delete cascade,

    asset_type text not null
        check (
            asset_type in (
                'product_image',
                'character_ref',
                'voice_audio',
                'scene_raw',
                'scene_lipsync',
                'final_mp4',
                'thumbnail',
                'subtitle_srt'
            )
        ),

    storage_bucket text not null,
    storage_path text not null,
    mime_type text not null,

    file_size_bytes bigint not null check (file_size_bytes > 0),

    duration_sec numeric(6,2),
    checksum_sha256 text,

    created_at timestamptz not null default now()
);

-- =========================================================
-- 7. GENERATION HISTORY
-- =========================================================

create table if not exists public.generation_history (
    id uuid primary key default gen_random_uuid(),

    user_id uuid not null references auth.users(id) on delete cascade,

    project_id uuid not null references public.video_projects(id) on delete cascade,
    job_id uuid not null unique references public.video_jobs(id) on delete cascade,

    product_name text not null,
    project_name text not null,

    thumbnail_storage_path text not null,
    video_storage_path text not null,

    duration_sec numeric(6,2) not null,
    aspect_ratio text not null,

    character_name text not null,
    voice_name text not null,

    script_snapshot jsonb not null,
    qc_summary jsonb not null,

    is_deleted boolean not null default false,

    created_at timestamptz not null default now()
);

-- =========================================================
-- 8. INDEX TỐI ƯU TRUY VẤN
-- =========================================================

create index if not exists idx_history_user_created
on public.generation_history(user_id, created_at desc)
where is_deleted = false;

create index if not exists idx_history_product_search
on public.generation_history
using gin (to_tsvector('simple', product_name));

create index if not exists idx_jobs_user_status
on public.video_jobs(user_id, status, created_at desc);

create index if not exists idx_scenes_job
on public.video_scenes(job_id, scene_index);

create index if not exists idx_assets_user
on public.video_assets(user_id, created_at desc);

-- =========================================================
-- 9. BẬT ROW LEVEL SECURITY
-- =========================================================

alter table public.video_projects enable row level security;
alter table public.video_jobs enable row level security;
alter table public.video_scenes enable row level security;
alter table public.video_assets enable row level security;
alter table public.generation_history enable row level security;

-- =========================================================
-- 10. TẠO LẠI POLICY AN TOÀN, TRÁNH TRÙNG TÊN
-- =========================================================

drop policy if exists owner_all_projects on public.video_projects;
create policy owner_all_projects
on public.video_projects
for all
to authenticated
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists owner_all_jobs on public.video_jobs;
create policy owner_all_jobs
on public.video_jobs
for all
to authenticated
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists owner_all_scenes on public.video_scenes;
create policy owner_all_scenes
on public.video_scenes
for all
to authenticated
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists owner_all_assets on public.video_assets;
create policy owner_all_assets
on public.video_assets
for all
to authenticated
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists owner_all_history on public.generation_history;
create policy owner_all_history
on public.generation_history
for all
to authenticated
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

-- =========================================================
-- 11. SUPABASE REALTIME
-- Chỉ thêm bảng nếu chưa có trong publication
-- =========================================================

do $$
declare
    table_name text;
begin
    if exists (
        select 1
        from pg_publication
        where pubname = 'supabase_realtime'
    ) then

        foreach table_name in array array[
            'video_jobs',
            'video_scenes'
        ]
        loop
            if not exists (
                select 1
                from pg_publication_tables
                where pubname = 'supabase_realtime'
                  and schemaname = 'public'
                  and tablename = table_name
            ) then
                execute format(
                    'alter publication supabase_realtime add table public.%I',
                    table_name
                );
            end if;
        end loop;

    else
        raise notice 'Publication supabase_realtime chưa tồn tại.';
    end if;
end
$$;

-- =========================================================
-- 12. HOÀN TẤT
-- =========================================================

select 'BAP AI VIDEO DATABASE SETUP COMPLETED' as result;
