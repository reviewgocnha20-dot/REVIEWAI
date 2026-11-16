# -*- coding: utf-8 -*-
"""
VidForge — Xưởng Tạo Video Bán Hàng Tự Động (bản chạy thật)
Chạy:  streamlit run app.py
"""

import os

import streamlit as st

import vidforge_core as core

# --------------------------------------------------------------------------- #
# Cấu hình trang & CSS (tông gradient cam-vàng ấm áp)
# --------------------------------------------------------------------------- #

st.set_page_config(
    page_title="VidForge - TikTok Shop Edition",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
  .stApp {
    background: linear-gradient(135deg, #FFB703 0%, #FB8500 50%, #FF5400 100%) !important;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  }
  div.block-container {
    background: rgba(255, 255, 255, 0.95);
    border-radius: 24px;
    padding: 2.5rem;
    box-shadow: 0 15px 35px rgba(0, 0, 0, 0.2);
    margin-top: 2rem;
    margin-bottom: 2rem;
  }
  .stButton>button {
    background: linear-gradient(90deg, #FF5400 0%, #FFB703 100%) !important;
    color: white !important;
    border: none !important;
    border-radius: 14px !important;
    font-weight: 700;
    padding: 0.75rem 1.5rem;
    box-shadow: 0 4px 15px rgba(255, 84, 0, 0.4);
    transition: all 0.3s ease;
  }
  .stButton>button:hover {
    transform: translateY(-2px);
    box-shadow: 0 6px 20px rgba(255, 84, 0, 0.6);
  }
  h1, h2, h3 { color: #1a1a1a !important; font-weight: 800; }
</style>
""", unsafe_allow_html=True)

# --------------------------------------------------------------------------- #
# Khởi tạo session_state
# --------------------------------------------------------------------------- #

for key, default in (
    ("product", None),        # core.ProductInfo
    ("segments", None),       # list[core.ScriptSegment]
    ("video_path", None),
    ("current_project_id", None),
):
    if key not in st.session_state:
        st.session_state[key] = default

# --------------------------------------------------------------------------- #
# Sidebar — cấu hình API
# --------------------------------------------------------------------------- #

with st.sidebar:
    st.header("⚙️ Cài đặt & API Key")

    st.subheader("1. AI Phân tích & Kịch bản")
    groq_key = st.text_input("Groq API Key (gsk_...)", type="password",
                             value=os.environ.get("GROQ_API_KEY", ""))
    llm_model = st.selectbox("Model AI",
                             ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"])

    st.subheader("2. Giọng đọc AI (TTS)")
    tts_provider = st.selectbox(
        "Nhà cung cấp",
        ["ElevenLabs", "OpenAI TTS", "edge-tts (miễn phí)", "Tắt"],
    )
    eleven_key = st.text_input("ElevenLabs API key", type="password", value="")
    openai_key = st.text_input("OpenAI API key", type="password", value="")
    eleven_voice_id = st.text_input(
        "ElevenLabs Voice ID (tùy chọn, để trống = dùng preset)", value="")

    st.markdown("---")
    st.markdown("### 📊 Trạng thái hệ thống")
    ai_status = "🟢 Bật" if groq_key else "🔴 Tắt"
    if tts_provider == "ElevenLabs":
        tts_status = "🟢 Bật" if eleven_key else "🔴 Thiếu key"
    elif tts_provider == "OpenAI TTS":
        tts_status = "🟢 Bật" if openai_key else "🔴 Thiếu key"
    elif tts_provider == "edge-tts (miễn phí)":
        tts_status = "🟢 Bật (không cần key)"
    else:
        tts_status = "🔴 Tắt (video sẽ câm)"
    st.text(f"AI (LLM): {ai_status}")
    st.text(f"TTS: {tts_status}")
    st.text(f"Dựng video: MP4 9:16 (MoviePy + FFmpeg)")

# --------------------------------------------------------------------------- #
# Tiêu đề
# --------------------------------------------------------------------------- #

st.title("🎬 VidForge — Xưởng Tạo Video Bán Hàng Tự Động")
st.markdown("Biến đường dẫn sản phẩm (TikTok Shop, Shopee, Lazada) thành video "
            "bán hàng chuẩn 9:16 trong vài phút.")

tab1, tab2, tab3 = st.tabs(["🚀 Tạo video mới", "📂 Dự án của tôi",
                            "⚙️ Hướng dẫn & Cấu hình"])

# --------------------------------------------------------------------------- #
# TAB 1 — Tạo video mới
# --------------------------------------------------------------------------- #

with tab1:
    st.subheader("Bước 1: Nhập liên kết sản phẩm")
    product_url = st.text_input(
        "Dán link TikTok Shop, Shopee, Lazada hoặc Website sản phẩm:",
        placeholder="https://shop.tiktok.com/view/product/...")

    with st.expander("✍️ Hoặc nhập thông tin sản phẩm thủ công (nếu link không truy cập được)"):
        manual_title = st.text_input("Tên sản phẩm", value="")
        manual_desc = st.text_area("Mô tả ngắn", value="", height=80)
        manual_price = st.text_input("Giá", value="")
        manual_image = st.text_input("Link ảnh sản phẩm (tùy chọn)", value="")

    extra_notes = st.text_input("Ghi chú cho AI (tùy chọn)",
                                placeholder="VD: nhấn mạnh freeship, đang sale 50%...")

    col1, _ = st.columns([1, 2])
    with col1:
        analysis_btn = st.button("🔍 Phân tích sản phẩm")

    if analysis_btn:
        if not product_url and not manual_title:
            st.error("Vui lòng nhập đường dẫn sản phẩm hoặc thông tin thủ công!")
        elif not groq_key:
            st.error("Vui lòng nhập Groq API Key ở sidebar trước!")
        else:
            with st.spinner("Đang tải thông tin sản phẩm..."):
                try:
                    if product_url:
                        try:
                            info = core.fetch_product(product_url)
                        except Exception as e:
                            st.warning(f"Không tải được trang ({e}). "
                                       "Hãy dùng nhập thủ công ở trên.")
                            info = core.ProductInfo(url=product_url)
                    else:
                        info = core.ProductInfo()
                    # Gộp dữ liệu thủ công nếu có
                    info.title = info.title or manual_title
                    info.description = info.description or manual_desc
                    info.price = info.price or manual_price
                    info.image_url = info.image_url or manual_image
                    if not info.title:
                        st.error("Không lấy được tên sản phẩm. Hãy nhập thủ công.")
                        st.stop()
                except Exception as e:
                    st.error(f"Lỗi: {e}")
                    st.stop()

            with st.spinner("AI đang viết kịch bản..."):
                try:
                    segments = core.generate_script(
                        groq_key, llm_model, info,
                        target_seconds=30, extra_notes=extra_notes)
                except Exception as e:
                    st.error(f"Lỗi khi gọi Groq: {e}")
                    st.stop()

            st.session_state.product = info
            st.session_state.segments = segments
            st.session_state.video_path = None
            st.success("Phân tích sản phẩm thành công!")

    # --- Hiển thị & chỉnh sửa kịch bản ---
    if st.session_state.segments:
        product = st.session_state.product
        st.markdown(f"**Sản phẩm:** {product.title}"
                    + (f"  |  **Giá:** {product.price}" if product.price else ""))
        if product.image_url:
            st.image(product.image_url, width=160)

        st.markdown("### 📝 Kịch bản video (có thể chỉnh sửa trực tiếp):")
        edited = st.data_editor(
            [{"label": s.label, "text": s.text}
             for s in st.session_state.segments],
            num_rows="dynamic", use_container_width=True,
            column_config={
                "label": st.column_config.TextColumn("Đoạn", width="small"),
                "text": st.column_config.TextColumn("Lừa thoại", width="large"),
            },
            key="script_editor",
        )
        st.session_state.segments = [
            core.ScriptSegment(label=str(r.get("label", "")).strip() or f"Đoạn {i+1}",
                               text=str(r.get("text", "")).strip())
            for i, r in enumerate(edited) if str(r.get("text", "")).strip()
        ]

        st.subheader("Bước 2: Tùy chọn dựng video")
        voice_labels = list(core.EDGE_VOICES.keys())
        c1, c2 = st.columns(2)
        with c1:
            selected_voice = st.selectbox("Chọn giọng đọc AI:", voice_labels)
        with c2:
            selected_duration = st.selectbox(
                "ThờI lượng mục tiêu:",
                ["30 giây", "15 giây", "45 giây", "60 giây"])

        generate_btn = st.button("🎬 Tiến hành dựng video hoàn chỉnh")

        if generate_btn:
            segments = st.session_state.segments
            if not segments:
                st.error("Kịch bản đang trống!")
            else:
                project = core.new_project(product.title or "VidForge Video")
                core.save_project(project)
                proj_dir = core.project_file_path(project.project_id, "")
                audio_path = os.path.join(proj_dir, "voice.mp3")
                video_path = os.path.join(
                    proj_dir, f"{core.slugify(product.title)}.mp4")
                image_path = os.path.join(proj_dir, "product.jpg")

                progress = st.progress(0.0, text="Khởi tạo...")
                try:
                    # 1. Tải ảnh sản phẩm
                    if product.image_url:
                        progress.progress(0.05, "Đang tải ảnh sản phẩm...")
                        try:
                            core.download_image(product.image_url, image_path)
                        except Exception:
                            image_path = ""

                    # 2. TTS
                    full_text = " ".join(s.text for s in segments)
                    if tts_provider != "Tắt":
                        progress.progress(0.1, f"Đang tạo giọng đọc "
                                               f"({tts_provider})...")
                        core.synthesize(
                            tts_provider, full_text, audio_path,
                            selected_voice, eleven_key=eleven_key,
                            openai_key=openai_key,
                            voice_id_override=eleven_voice_id)
                    else:
                        audio_path = ""

                    def _cb(frac, msg):
                        progress.progress(min(frac, 0.95), text=msg)

                    # 3. Dựng video
                    core.build_video(product, segments, audio_path,
                                     image_path, video_path,
                                     progress_cb=_cb)
                    thumb = core.save_thumbnail(product, image_path,
                                                project.project_id)

                    # 4. Lưu dự án
                    project.status = "done"
                    project.product = product.to_dict()
                    project.segments = [s.to_dict() for s in segments]
                    project.voice = selected_voice
                    project.provider = tts_provider
                    project.video_path = video_path
                    project.audio_path = audio_path
                    project.thumb_path = thumb
                    core.save_project(project)

                    progress.progress(1.0, "Hoàn tất!")
                    st.session_state.video_path = video_path
                    st.session_state.current_project_id = project.project_id
                    st.success("🎉 Dựng video thành công! Dự án đã được lưu.")
                except Exception as e:
                    project.status = "failed"
                    project.error = str(e)
                    core.save_project(project)
                    progress.progress(1.0, "Thất bại")
                    st.error(f"Lỗi khi dựng video: {e}")

    # --- Xem trước video vừa tạo ---
    if st.session_state.video_path and os.path.exists(st.session_state.video_path):
        st.markdown("### 👀 Xem trước video")
        st.video(st.session_state.video_path)
        with open(st.session_state.video_path, "rb") as f:
            st.download_button("📥 Tải xuống video MP4", data=f.read(),
                               file_name=os.path.basename(
                                   st.session_state.video_path),
                               mime="video/mp4")

# --------------------------------------------------------------------------- #
# TAB 2 — Dự án của tôi
# --------------------------------------------------------------------------- #

with tab2:
    st.subheader("📂 Danh sách dự án")
    projects = core.list_projects()
    if not projects:
        st.info("Chưa có dự án nào. Hãy tạo video đầu tiên ở tab 🚀 Tạo video mới.")
    for p in projects:
        status_icon = {"done": "✅", "rendering": "⏳", "failed": "❌"}.get(
            p.get("status", ""), "•")
        with st.expander(f"{status_icon} **{p.get('name', 'Dự án')}** — "
                               f"{p.get('created_at', '')}"):
            if p.get("status") == "done":
                segs = p.get("segments", [])
                total = sum(s.get("end", 0) - s.get("start", 0) for s in segs)
                st.markdown(f"⏱️ ThờI lượng: ~{total:.0f}s  |  "
                            f"🎙️ {p.get('voice', '')} ({p.get('provider', '')})")
                vp = p.get("video_path", "")
                if vp and os.path.exists(vp):
                    st.video(vp)
                    with open(vp, "rb") as f:
                        st.download_button("📥 Tải xuống MP4", data=f.read(),
                                           file_name=os.path.basename(vp),
                                           mime="video/mp4",
                                           key=f"dl_{p.get('project_id')}")
                st.markdown("**Kịch bản:**")
                for s in segs:
                    st.markdown(f"- **{s.get('label', '')}:** {s.get('text', '')}")
            elif p.get("status") == "failed":
                st.error(f"Dự án thất bại: {p.get('error', 'lỗi không xác định')}")
            else:
                st.info("Dự án đang dựng... (hãy mở lại tab này sau.)")

# --------------------------------------------------------------------------- #
# TAB 3 — Hướng dẫn
# --------------------------------------------------------------------------- #

with tab3:
    st.subheader("⚙️ Hướng dẫn vận hành cục bộ")
    st.markdown("""
    1. Cài đặt các thư viện cần thiết:
       ```bash
       pip install -r requirements.txt
       ```
    2. (Tùy chọn) Lấy API key:
       - **Groq** (miễn phí): https://console.groq.com — dùng cho AI viết kịch bản.
       - **ElevenLabs**: https://elevenlabs.io — giọng đọc chất lượng cao.
       - **edge-tts**: miễn phí 100%, không cần key, chỉ cần mạng.
    3. Chạy ứng dụng:
       ```bash
       streamlit run app.py
       ```
    4. Video xuất ra ở định dạng **MP4 9:16 (1080x1920)**, lưu trong thư mục
       `vidforge_projects/<mã dự án>/`.

    **Lưu ý kỹ thuật:**
    - TikTok Shop / Shopee / Lazada có thể chặn truy cập tự động; nếu link không
      tải được, hãy dùng ô *nhập thủ công* ở Bước 1.
    - Lần dựng video đầu tiên có thể chậm do MoviePy/FFmpeg khởi tạo.
    - Cần FFmpeg trong PATH (Windows: tải tại https://www.gyan.dev/ffmpeg/builds/
      hoặc dùng `imageio-ffmpeg` đã nằm trong requirements).
    """)
