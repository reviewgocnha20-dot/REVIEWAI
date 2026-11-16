import streamlit as st
from supabase import create_client

# ==========================================
# 1. CẤU HÌNH GIAO DIỆN & KẾT NỐI SUPABASE
# ==========================================
st.set_page_config(
    page_title="AI Review Video System",
    page_icon="🎬",
    layout="wide"
)

# Lấy thông tin kết nối từ Streamlit Secrets hoặc dùng giá trị mặc định
SUPABASE_URL = st.secrets.get("SUPABASE_URL", "https://your-project.supabase.co")
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY", "your-supabase-anon-key")

@st.cache_resource
def init_supabase():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase = init_supabase()

# ==========================================
# 2. THANH ĐIỀU HƯỚNG (SIDEBAR)
# ==========================================
st.sidebar.title("🎬 AI Review Video")
menu = st.sidebar.radio("Chọn chức năng:", ["🚀 Tạo Video Mới", "⏳ Video Đang Xử Lý", "📁 Thư Viện Hoàn Thành"])

# ==========================================
# 3. GIAO DIỆN: TẠO VIDEO MỚI
# ==========================================
if menu == "🚀 Tạo Video Mới":
    st.markdown("<h1>🚀 Tạo Video Review Sản Phẩm AI</h1>", unsafe_allow_html=True)
    
    with st.form("create_video_form"):
        project_name = st.text_input("Tên dự án", "Review sản phẩm tự động")
        product_name = st.text_input("Tên sản phẩm", "Máy xay sinh tố mini")
        product_url = st.text_input("Link sản phẩm (Tùy chọn)", "https://...")
        product_image_url = st.text_input("Link ảnh sản phẩm", "https://via.placeholder.com/300")
        
        col1, col2 = st.columns(2)
        with col1:
            target_duration = st.selectbox("Thời lượng video (giây)", [15, 30, 45, 60], index=1)
            aspect_ratio = st.selectbox("Tỷ lệ khung hình", ["9:16", "16:9", "1:1"])
        with col2:
            review_style = st.selectbox("Phong cách review", ["home_kitchen", "living_room", "vlog", "handheld_closeup"])
            category = st.text_input("Danh mục sản phẩm", "kitchen_appliance")

        submitted = st.form_submit_button("Tạo Video Ngay")
        
        if submitted:
            if not product_name or not product_image_url:
                st.warning("Vui lòng điền đầy đủ tên sản phẩm và link ảnh.")
            else:
                try:
                    dummy_user_id = "00000000-0000-0000-0000-000000000000"
                    
                    # 1. Tạo project
                    proj_res = supabase.table("video_projects").insert({
                        "user_id": dummy_user_id,
                        "project_name": project_name,
                        "product_name": product_name,
                        "product_url": product_url,
                        "product_image_url": product_image_url,
                        "product_category": category,
                        "target_duration_sec": target_duration,
                        "aspect_ratio": aspect_ratio,
                        "review_style": review_style,
                        "character_config": {"name": "Default Model"},
                        "voice_config": {"name": "Default Voice"}
                    }).execute()
                    
                    if proj_res.data:
                        project_id = proj_res.data[0]["id"]
                        
                        # 2. Tạo job trong hàng đợi
                        supabase.table("video_jobs").insert({
                            "user_id": dummy_user_id,
                            "project_id": project_id,
                            "idempotency_key": f"job-{SUPABASE_URL}",
                            "status": "queued",
                            "current_stage_label": "Đang trong hàng đợi",
                            "estimated_credits": target_duration * 0.5
                        }).execute()
                        
                        st.success("🎉 Đã đưa tác vụ vào hàng đợi thành công! Hãy chuyển sang mục 'Video Đang Xử Lý' để theo dõi.")
                    else:
                        st.error("Không thể tạo dự án.")
                except Exception as e:
                    st.error(f"Lỗi khi gửi yêu cầu: {e}")

# ==========================================
# 4. GIAO DIỆN: VIDEO ĐANG XỬ LÝ (REALTIME)
# ==========================================
elif menu == "⏳ Video Đang Xử Lý":
    st.markdown("<h1>⏳ Video Đang Xử Lý & Hàng Đợi</h1>", unsafe_allow_html=True)
    
    if st.button("🔄 Làm mới danh sách"):
        st.rerun()

    try:
        response = supabase.table("video_jobs").select("*, video_projects(*)").order("created_at", desc=True).execute()
        jobs = response.data or []

        if not jobs:
            st.info("Hiện không có video nào trong hàng đợi xử lý.")
        else:
            for job in jobs:
                proj = job.get("video_projects") or {}
                product_name = proj.get("product_name", "Dự án AI")
                status = job.get("status", "queued")
                stage_label = job.get("current_stage_label", "Đang trong hàng đợi")
                progress = job.get("provider_progress_percent")

                with st.container():
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        st.subheader(product_name)
                        st.caption(f"Trạng thái hệ thống: `{status}`")
                    with col2:
                        st.markdown(f"**{stage_label}**")

                    if progress is not None:
                        st.progress(progress / 100)
                    
                    if status == "failed":
                        st.error(f"Lỗi: {job.get('error_message', 'Lỗi không xác định')}")
                    
                    st.divider()
    except Exception as e:
        st.error(f"Lỗi kết nối cơ sở dữ liệu: {e}")

# ==========================================
# 5. GIAO DIỆN: THƯ VIỆN HOÀN THÀNH & 8 NÚT BẮT BUỘC
# ==========================================
elif menu == "📁 Thư Viện Hoàn Thành":
    st.markdown("<h1>📁 Thư Viện Video Đã Hoàn Thành</h1>", unsafe_allow_html=True)
    
    search_query = st.text_input("🔍 Tìm kiếm theo tên sản phẩm...", "")

    try:
        query = supabase.table("generation_history").select("*").eq("is_deleted", False).order("created_at", desc=True)
        response = query.execute()
        history_list = response.data or []

        # Lọc theo từ khóa tìm kiếm
        if search_query:
            history_list = [h for h in history_list if search_query.lower() in h.get("product_name", "").lower()]

        if not history_list:
            st.info("Chưa có video nào hoàn thành hoặc không tìm thấy kết quả phù hợp.")
        else:
            for item in history_list:
                with st.container():
                    st.markdown(f"### 🎬 {item.get('product_name')}")
                    st.text(f"Dự án: {item.get('project_name')} | Thời lượng: {item.get('duration_sec')}s")
                    
                    # Mô phỏng Bộ 8 nút chức năng bắt buộc
                    b1, b2, b3, b4 = st.columns(4)
                    with b1:
                        if st.button("👁️ Xem", key=f"view_{item['id']}"):
                            st.info("Mở trình phát video trực tiếp.")
                    with b2:
                        if st.button("⬇️ Tải", key=f"dl_{item['id']}"):
                            st.success("Đang chuẩn bị file MP4 để tải xuống.")
                    with b3:
                        if st.button("📜 Script", key=f"script_{item['id']}"):
                            st.json(item.get("script_snapshot", {}))
                    with b4:
                        if st.button("ℹ️ Info", key=f"info_{item['id']}"):
                            st.write(item.get("qc_summary", {}))

                    c1, c2, c3, c4 = st.columns(4)
                    with c1:
                        if st.button("🔄 Tạo lại", key=f"re_{item['id']}"):
                            st.toast("Đã nhân bản cấu hình để tạo video mới!")
                    with c2:
                        if st.button("🛠️ Sửa cảnh", key=f"scene_{item['id']}"):
                            st.toast("Mở chế độ tái tạo lại một cảnh lỗi.")
                    with c3:
                        if st.button("📋 Sao chép", key=f"clone_{item['id']}"):
                            st.toast("Đã sao chép dự án nháp mới!")
                    with c4:
                        if st.button("🗑️ Xóa", key=f"del_{item['id']}"):
                            supabase.table("generation_history").update({"is_deleted": True}).eq("id", item["id"]).execute()
                            st.rerun()

                    st.divider()
    except Exception as e:
        st.error(f"Lỗi khi tải thư viện: {e}")
