-- Bật extension cần thiết
create extension if not exists "pgcrypto";

-- 1. ENUM trạng thái chuẩn theo 25.2 (+ trạng thái nội bộ kiểm soát chất lượng 25.7)
create type video_job_status as enum (
  'queued',
  'analyzing_product',      -- Đang phân tích sản phẩm
  'writing_script',         -- Đang viết kịch bản
  'generating_voice',       -- Đang tạo giọng đọc
  'generating_character',   -- Đang tạo nhân vật
  'generating_scenes',      -- Đang tạo cảnh
  'syncing_lips',           -- Đang đồng bộ khẩu hình
  'merging_video',          -- Đang ghép video
  'quality_checking',       -- Đang kiểm tra chất lượng (25.7)
  'saving_video',           -- Đang lưu video
  'completed',              -- Hoàn thành (chỉ set khi file MP4 + QC đạt)
  'needs_review',           -- Chờ kiểm tra / có cảnh cần tạo lại (25.7)
  'failed'                  -- Thất bại
);

-- 2. Bảng video_projects: Lưu cấu hình dự án để sao chép / tạo phiên bản mới (25.1, 25.3)
create table public.video_projects (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  parent_project_id uuid references public.video_projects(id) on delete set null,
  project_name text not null,
  product_url text,
  product_name text not null,
  product_image_url text not null,
  product_category text, -- 'kitchen_appliance', 'rack_furniture', 'cosmetics', etc.
  verified_product_facts jsonb not null default '{}'::jsonb,
  target_duration_sec int not null check (target_duration_sec in (15, 30, 45, 60)),
  aspect_ratio text not null default '9:16' check (aspect_ratio in ('9:16', '16:9', '1:1')),
  review_style text not null, -- 'home_kitchen', 'living_room', 'vlog', 'handheld_closeup', ...
  character_config jsonb not null, -- { id, name, reference_image_url, appearance_prompt }
  voice_config jsonb not null,     -- { provider, voice_id, voice_name, speed, locale }
  script_json jsonb,               -- Kịch bản chi tiết thoại + hành động
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- 3. Bảng video_jobs: Theo dõi tác vụ bất đồng bộ thực tế (25.2, 25.8)
create table public.video_jobs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  project_id uuid not null references public.video_projects(id) on delete cascade,
  idempotency_key text not null, -- Chống tạo trùng khi user bấm đúp hoặc retry request
  status video_job_status not null default 'queued',
  current_stage_label text not null default 'Đang trong hàng đợi',
  -- Chỉ lưu số % khi nhà cung cấp trả về thật; nếu không trả về thì để NULL (25.2)
  provider_progress_percent int check (provider_progress_percent between 0 and 100),
  scenes_completed int not null default 0,
  scenes_total int not null default 0,

  -- Quản lý chi phí & credits theo công đoạn (25.8)
  estimated_credits numeric(10,2) not null default 0,
  used_credits numeric(10,2) not null default 0,
  stage_costs_usd jsonb not null default '{}'::jsonb, -- {"llm": 0.02, "tts": 0.05, "video": 1.20, "lipsync": 0.45}

  -- Xử lý lỗi, retry & timeout (25.2, 25.8)
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
  unique(user_id, idempotency_key)
);

-- 4. Bảng video_scenes: Chi tiết từng cảnh, cho phép "Tạo lại một cảnh" (25.1, 25.6, 25.7)
create table public.video_scenes (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  job_id uuid not null references public.video_jobs(id) on delete cascade,
  scene_index int not null,
  duration_sec numeric(5,2) not null,
  dialogue_text text not null,
  action_direction text not null,  -- Hành động tay, ánh mắt, cầm/xoay/chỉ sản phẩm
  camera_framing text not null,    -- 'medium_handheld', 'closeup_product', 'over_shoulder', ...
  needs_lipsync boolean not null default false,

  -- Tham chiếu API thật & file đã backup vào Supabase Storage
  provider_name text,
  provider_request_id text,
  provider_temp_video_url text,
  audio_storage_path text,
  raw_video_storage_path text,
  synced_video_storage_path text,

  -- Kết quả kiểm soát chất lượng từng cảnh (25.7)
  status text not null default 'pending' check (status in ('pending','generating','syncing','qc_passed','qc_failed','failed')),
  qc_report jsonb not null default '{}'::jsonb,
  error_message text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(job_id, scene_index)
);

-- 5. Bảng video_assets: Quản lý toàn bộ file đầu vào/đầu ra trong Storage (25.8)
create table public.video_assets (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  project_id uuid references public.video_projects(id) on delete cascade,
  job_id uuid references public.video_jobs(id) on delete cascade,
  scene_id uuid references public.video_scenes(id) on delete cascade,
  asset_type text not null check (asset_type in (
    'product_image', 'character_ref', 'voice_audio', 'scene_raw', 'scene_lipsync', 'final_mp4', 'thumbnail', 'subtitle_srt'
  )),
  storage_bucket text not null,
  storage_path text not null,
  mime_type text not null,
  file_size_bytes bigint not null check (file_size_bytes > 0),
  duration_sec numeric(6,2),
  checksum_sha256 text,
  created_at timestamptz not null default now()
);

-- 6. Bảng generation_history: Thư viện VIDEO ĐÃ HOÀN THÀNH (25.3, 25.7)
create table public.generation_history (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  project_id uuid not null references public.video_projects(id) on delete cascade,
  job_id uuid not null unique references public.video_jobs(id) on delete cascade,
  product_name text not null,
  project_name text not null,
  thumbnail_storage_path text not null,
  video_storage_path text not null, -- Đường dẫn vĩnh viễn trên Supabase Storage
  duration_sec numeric(6,2) not null,
  aspect_ratio text not null,
  character_name text not null,
  voice_name text not null,
  script_snapshot jsonb not null,
  qc_summary jsonb not null,        -- Bằng chứng đã qua QC (playable, audio_ok, no_black_frames...)
  is_deleted boolean not null default false,
  created_at timestamptz not null default now()
);

-- Index tối ưu tìm kiếm & lọc ở trang VIDEO ĐÃ HOÀN THÀNH (25.3)
create index idx_history_user_created on public.generation_history(user_id, created_at desc) where is_deleted = false;
create index idx_history_product_search on public.generation_history using gin (to_tsvector('simple', product_name));
create index idx_jobs_user_status on public.video_jobs(user_id, status, created_at desc);

-- BẬT RLS CHO TẤT CẢ CÁC BẢNG (25.3, 25.8)
alter table public.video_projects enable row level security;
alter table public.video_jobs enable row level security;
alter table public.video_scenes enable row level security;
alter table public.video_assets enable row level security;
alter table public.generation_history enable row level security;

create policy "owner_all_projects" on public.video_projects for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "owner_all_jobs" on public.video_jobs for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "owner_all_scenes" on public.video_scenes for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "owner_all_assets" on public.video_assets for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "owner_all_history" on public.generation_history for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- Bật Supabase Realtime cho trang VIDEO ĐANG XỬ LÝ (25.2)
alter publication supabase_realtime add table public.video_jobs, public.video_scenes;
