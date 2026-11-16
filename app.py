ai-review-video/
├── package.json
├── .env.example
├── next.config.ts
├── supabase/
│   └── migrations/
│       └── 001_init_ai_video.sql
└── src/
    ├── lib/
    │   ├── types.ts
    │   ├── env-check.ts
    │   ├── supabase-admin.ts
    │   ├── supabase-browser.ts
    │   ├── supabase-server.ts
    │   ├── director.ts
    │   ├── ffmpeg.ts
    │   └── qc.ts
    ├── worker/
    │   └── index.ts
    └── app/
        ├── layout.tsx
        ├── page.tsx                              # Tạo video review AI
        ├── processing/
        │   └── page.tsx                          # 25.2: VIDEO ĐANG XỬ LÝ
        ├── history/
        │   └── page.tsx                          # 25.3 & 25.1: VIDEO ĐÃ HOÀN THÀNH + 8 nút bắt buộc
        └── api/
            ├── system/readiness/route.ts         # 25.9: Kiểm tra API thật
            ├── videos/create/route.ts            # 25.1: Tiếp nhận + Credits + Queue
            ├── jobs/[jobId]/retry/route.ts       # 25.2: Thử lại công đoạn lỗi
            ├── scenes/[sceneId]/regenerate/route.ts # 25.1 & 25.7: Tạo lại một cảnh
            ├── projects/[projectId]/clone/route.ts  # 25.1 & 25.3: Sao chép / Phiên bản mới
            ├── projects/[projectId]/recreate/route.ts # 25.1: Tạo lại video
            ├── history/route.ts                  # 25.3: Tìm kiếm, lọc, xóa nhiều
            └── history/[historyId]/download/route.ts # 25.1: Tải file MP4 thật
