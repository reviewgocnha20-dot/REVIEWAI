import os
import requests
import streamlit as st

import config
from services.ai_service import (
    edit_image_flux_kontext,
    generate_video_kling,
    merge_audio_into_video,
    text_to_speech_vietnamese,
)
from services.supabase_service import (
    approve_transaction,
    create_transaction,
    deduct_credits,
    get_pending_transactions,
    get_user_credits,
    get_user_transactions,
    get_user_video_history,
    refund_credits,
    save_video_history,
    sign_in_user,
    sign_out_user,
    sign_up_user,
)

# ==============================================================================
# CẤU HÌNH TRANG & GIAO DIỆN DARK MODE (#0E1117 + #F59E0B)
# ==============================================================================
st.set_page_config(
    page_title="BẮP AI VIDEO - Studio Tạo Video AI",
    page_icon="🌽",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    /* Nền chính Dark Mode */
    .stApp {
        background-color: #0E1117;
        color: #F8FAFC;
    }
    section[data-testid="stSidebar"] {
        background-color: #131722;
        border-right: 1px solid #262B3D;
    }
    /* Tiêu đề & điểm nhấn màu Vàng Bắp #F59E0B */
    .bap-brand {
        font-size: 26px;
        font-weight: 800;
        color: #F59E0B;
        letter-spacing: 0.5px;
        margin-bottom: 4px;
    }
    .bap-subtitle {
        font-size: 13px;
        color: #94A3B8;
        margin-bottom: 18px;
    }
    .credit-badge {
        background: linear-gradient(135deg, rgba(245, 158, 11, 0.18), rgba(217, 119, 6, 0.08));
        border: 1px solid #F59E0B;
        border-radius: 12px;
        padding: 12px 14px;
        margin: 10px 0 16px 0;
    }
    .bap-card {
        background-color: #161B26;
        border: 1px solid #2A3142;
        border-radius: 14px;
        padding: 18px;
        margin-bottom: 16px;
    }
    .pkg-card {
        background-color: #161B26;
        border: 1px solid #2A3142;
        border-radius: 16px;
        padding: 20px;
        height: 100%;
    }
    .pkg-card-highlight {
        background-color: #1A1F2E;
        border: 2px solid #F59E0B;
        border-radius: 16px;
        padding: 20px;
        height: 100%;
    }
    /* Nút bấm chính màu vàng bắp */
    .stButton > button[kind="primary"] {
        background-color: #F59E0B !important;
        color: #0E1117 !important;
        font-weight: 700 !important;
        border: none !important;
        border-radius: 10px !important;
    }
    .stButton > button[kind="primary"]:hover {
        background-color: #D97706 !important;
        color: #FFFFFF !important;
    }
    /* Input & TextArea Dark Mode */
    .stTextInput input, .stTextArea textarea, .stSelectbox div[data-baseweb="select"] > div {
        background-color: #161B26 !important;
        color: #F8FAFC !important;
        border-color: #2E364A !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def is_admin_user(email: str) -> bool:
    """Kiểm tra email hiện tại có khớp với ADMIN_EMAIL không."""
    if not config.ADMIN_EMAIL or not email:
        return False
    return email.strip().lower() == config.ADMIN_EMAIL.strip().lower()


# ==============================================================================
# XỬ LÝ SIDEBAR: ĐĂNG NHẬP / THÔNG TIN USER / MENU TAB
# ==============================================================================
with st.sidebar:
    st.markdown("<div class='bap-brand'>🌽 BẮP AI VIDEO</div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='bap-subtitle'>FLUX Kontext · Kling 3.0 · Edge-TTS</div>",
        unsafe_allow_html=True,
    )

    user = st.session_state.get("user")

    if not user:
        st.info("Vui lòng đăng nhập hoặc đăng ký để sử dụng Studio AI.")
        auth_mode = st.radio(
            "Tài khoản",
            ["Đăng nhập", "Đăng ký mới (+10 Credits)"],
            horizontal=True,
        )
        with st.form("auth_form"):
            email_input = st.text_input("Email", placeholder="email@example.com")
            password_input = st.text_input("Mật khẩu", type="password", placeholder="Tối thiểu 6 ký tự")
            submitted = st.form_submit_button(
                "Đăng nhập" if auth_mode == "Đăng nhập" else "Tạo tài khoản ngay",
                type="primary",
                use_container_width=True,
            )

        if submitted:
            if not email_input or not password_input:
                st.warning("Vui lòng nhập đầy đủ Email và Mật khẩu.")
            elif auth_mode == "Đăng nhập":
                ok, msg = sign_in_user(email_input, password_input)
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
            else:
                ok, msg = sign_up_user(email_input, password_input)
                if ok:
                    st.success(msg)
                    if st.session_state.get("user"):
                        st.rerun()
                else:
                    st.error(msg)

        selected_tab = None
    else:
        user_id = user["id"]
        user_email = user["email"]

        try:
            current_credits = get_user_credits(user_id)
        except Exception as exc:
            current_credits = 0
            st.error(f"Không thể tải Credits: {exc}")

        st.markdown(
            f"""
            <div class="credit-badge">
                <div style="font-size:12px; color:#CBD5E1;">Tài khoản: <b>{user_email}</b></div>
                <div style="font-size:22px; font-weight:800; color:#F59E0B; margin-top:6px;">
                    ⚡ {current_credits} Credits
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # Menu chuyển Tab
        menu_options = [
            "🎨 Studio AI",
            "💳 Nạp Credits (VietQR)",
            "🎬 Lịch sử",
        ]
        if is_admin_user(user_email):
            menu_options.append("🛡️ Quản trị Admin")

        selected_tab = st.radio("Điều hướng chức năng", menu_options, label_visibility="collapsed")

        st.divider()
        if st.button("🚪 Đăng xuất", use_container_width=True):
            sign_out_user()
            st.rerun()


# ==============================================================================
# MÀN HÌNH CHÀO KHI CHƯA ĐĂNG NHẬP
# ==============================================================================
if not st.session_state.get("user"):
    st.markdown(
        """
        <div class="bap-card">
            <h1 style="color:#F59E0B; margin-top:0;">Chào mừng đến với BẮP AI VIDEO</h1>
            <p style="font-size:16px; color:#CBD5E1; line-height:1.6;">
                Nền tảng SaaS tự động hóa sản xuất video quảng cáo chất lượng cao từ hình ảnh sản phẩm:
            </p>
            <ul style="color:#E2E8F0; line-height:1.8;">
                <li><b>Chỉnh sửa & Sáng tạo ảnh sản phẩm (FLUX Kontext):</b> Chỉ 2 Credits / ảnh.</li>
                <li><b>Chuyển ảnh thành Video chuyển động (Kling 3.0):</b> Chỉ 10 Credits / video.</li>
                <li><b>Lồng tiếng Việt tự nhiên (Edge-TTS + MoviePy):</b> Tích hợp giọng Nam/Nữ miễn phí kèm video.</li>
                <li><b>Tặng ngay 10 Credits</b> khi đăng ký tài khoản mới!</li>
            </ul>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.stop()


user = st.session_state["user"]
user_id = user["id"]
user_email = user["email"]


# ==============================================================================
# TAB 1: STUDIO AI
# ==============================================================================
if selected_tab == "🎨 Studio AI":
    st.markdown("<h2 style='color:#F59E0B;'>🎨 Studio AI — Sáng tạo Ảnh & Video Lồng Tiếng</h2>", unsafe_allow_html=True)

    col_img_step, col_vid_step = st.columns([1, 1], gap="large")

    # --------------------------------------------------------------------------
    # BƯỚC 1: CHỈNH SỬA / TẠO ẢNH VỚI FLUX KONTEXT (2 CREDITS)
    # --------------------------------------------------------------------------
    with col_img_step:
        st.markdown(
            """
            <div class="bap-card">
                <h4 style="color:#F59E0B; margin-top:0;">Bước 1: Tạo / Chỉnh sửa ảnh (FLUX Kontext)</h4>
                <span style="color:#94A3B8; font-size:13px;">Chi phí: <b>2 Credits</b> / lần tạo</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        uploaded_image = st.file_uploader(
            "Tải lên ảnh sản phẩm / nhân vật gốc (.jpg, .png, .webp)",
            type=["jpg", "jpeg", "png", "webp"],
        )
        if uploaded_image is not None:
            st.image(uploaded_image, caption="Ảnh gốc đã tải lên", use_container_width=True)

        img_aspect = st.selectbox(
            "Tỷ lệ khung hình ảnh (tùy chọn)",
            ["Tự động theo ảnh gốc", "9:16", "16:9", "1:1"],
        )
        img_prompt = st.text_area(
            "Mô tả chỉnh sửa ảnh (Tiếng Việt hoặc Tiếng Anh)",
            placeholder="Ví dụ: Đặt chai nước hoa lên bàn đá cẩm thạch sang trọng dưới ánh nắng hoàng hôn, phong cách quảng cáo cao cấp...",
            height=100,
        )

        if st.button("✨ Chỉnh sửa ảnh với FLUX Kontext (-2 Credits)", type="primary", use_container_width=True):
            if uploaded_image is None:
                st.warning("Vui lòng tải lên 1 ảnh gốc trước.")
            elif not img_prompt.strip():
                st.warning("Vui lòng nhập mô tả chỉnh sửa ảnh.")
            else:
                ok_deduct, balance, msg_deduct = deduct_credits(user_id, config.COST_IMAGE_EDIT)
                if not ok_deduct:
                    st.error(f"{msg_deduct} Số dư hiện tại: {balance} Credits. Vui lòng nạp thêm ở Tab Nạp Credits.")
                else:
                    with st.status("Đang xử lý ảnh bằng FLUX Kontext...", expanded=True) as status:
                        try:
                            st.write("1. Đã tạm trừ 2 Credits. Đang gửi ảnh lên fal.ai...")
                            chosen_ratio = None if img_aspect == "Tự động theo ảnh gốc" else img_aspect
                            result_img_url = edit_image_flux_kontext(
                                image_bytes=uploaded_image.getvalue(),
                                prompt=img_prompt,
                                aspect_ratio=chosen_ratio,
                            )
                            st.session_state["current_image_url"] = result_img_url
                            st.write("2. Đã nhận URL ảnh chất lượng cao từ FLUX Kontext!")
                            status.update(label="✅ Tạo ảnh thành công!", state="complete", expanded=False)
                        except Exception as exc:
                            refund_credits(user_id, config.COST_IMAGE_EDIT)
                            status.update(label="❌ Lỗi tạo ảnh (Đã hoàn lại 2 Credits)", state="error")
                            st.error(f"Chi tiết lỗi: {exc}")

        if st.session_state.get("current_image_url"):
            st.success("Ảnh kết quả đã sẵn sàng để đưa sang Bước 2 (Tạo Video)!")
            st.image(
                st.session_state["current_image_url"],
                caption="Ảnh tạo bởi FLUX Kontext",
                use_container_width=True,
            )

    # --------------------------------------------------------------------------
    # BƯỚC 2: TẠO VIDEO KLING 3.0 (10 CREDITS) + LỒNG TIẾNG EDGE-TTS & MOVIEPY
    # --------------------------------------------------------------------------
    with col_vid_step:
        st.markdown(
            """
            <div class="bap-card">
                <h4 style="color:#F59E0B; margin-top:0;">Bước 2: Tạo Video Kling 3.0 & Lồng tiếng</h4>
                <span style="color:#94A3B8; font-size:13px;">Chi phí: <b>10 Credits</b> / video (Lồng tiếng Việt miễn phí)</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        default_img_url = st.session_state.get("current_image_url", "")
        source_img_url = st.text_input(
            "URL ảnh đầu vào cho Kling 3.0",
            value=default_img_url,
            placeholder="Tự động điền sau Bước 1 hoặc dán URL ảnh trực tiếp tại đây...",
        )

        c_ratio, c_dur = st.columns(2)
        with c_ratio:
            vid_aspect = st.selectbox("Tỷ lệ khung hình Video", ["9:16", "16:9", "1:1"])
        with c_dur:
            vid_duration = st.selectbox("Thời lượng Kling (giây)", [5, 10], index=0)

        motion_prompt = st.text_area(
            "Prompt chuyển động cho Video",
            placeholder="Ví dụ: Camera quay chậm tiến lại gần sản phẩm, ánh sáng lung linh phản chiếu trên mặt bàn, chuyển động điện ảnh mượt mà...",
            height=90,
        )

        st.markdown("---")
        enable_dubbing = st.checkbox("🎙️ Bật lồng tiếng Tiếng Việt tự động (Edge-TTS + MoviePy)", value=True)

        voice_label = list(config.VIETNAMESE_VOICES.keys())[0]
        voiceover_text = ""
        if enable_dubbing:
            voice_label = st.selectbox("Chọn giọng đọc Tiếng Việt", list(config.VIETNAMESE_VOICES.keys()))
            voiceover_text = st.text_area(
                "Nội dung lời thoại lồng tiếng",
                placeholder="Ví dụ: Chỉ với một bước đơn giản mỗi sáng, làn da của bạn sẽ rạng rỡ suốt cả ngày dài. Bấm ngay giỏ hàng góc trái nhé!",
                height=85,
            )

        if st.button("🚀 Tạo Video Quảng Cáo (-10 Credits)", type="primary", use_container_width=True):
            if not source_img_url.strip():
                st.warning("Vui lòng tạo ảnh ở Bước 1 hoặc nhập URL ảnh đầu vào.")
            elif not motion_prompt.strip():
                st.warning("Vui lòng nhập mô tả chuyển động cho video.")
            elif enable_dubbing and not voiceover_text.strip():
                st.warning("Bạn đã bật lồng tiếng, vui lòng nhập nội dung lời thoại.")
            else:
                ok_deduct, balance, msg_deduct = deduct_credits(user_id, config.COST_VIDEO_GEN)
                if not ok_deduct:
                    st.error(f"{msg_deduct} Số dư hiện tại: {balance} Credits. Vui lòng nạp thêm ở Tab Nạp Credits.")
                else:
                    audio_path = None
                    merged_mp4_path = None
                    with st.status("Đang khởi chạy dây chuyền sản xuất BẮP AI VIDEO...", expanded=True) as status:
                        try:
                            st.write("⏳ Bước 1/4: Đã trừ 10 Credits. Đang gửi yêu cầu tới Kling 3.0 Image-to-Video...")
                            kling_video_url = generate_video_kling(
                                image_url=source_img_url.strip(),
                                motion_prompt=motion_prompt.strip(),
                                aspect_ratio=vid_aspect,
                                duration=int(vid_duration),
                            )
                            st.session_state["last_kling_video_url"] = kling_video_url
                            st.write("✅ Bước 2/4: Kling 3.0 đã tạo xong video chuyển động!")

                            if enable_dubbing:
                                st.write("🎙️ Bước 3/4: Đang tạo giọng đọc Tiếng Việt bằng Edge-TTS...")
                                selected_voice_id = config.VIETNAMESE_VOICES[voice_label]
                                audio_path = text_to_speech_vietnamese(
                                    text=voiceover_text,
                                    voice=selected_voice_id,
                                )

                                st.write("🎞️ Bước 4/4: Đang ghép Audio vào Video bằng MoviePy...")
                                merged_mp4_path = merge_audio_into_video(
                                    video_url=kling_video_url,
                                    audio_mp3_path=audio_path,
                                )
                                with open(merged_mp4_path, "rb") as f:
                                    st.session_state["final_video_bytes"] = f.read()
                            else:
                                st.write("📥 Bước 3/4: Đang tải video hoàn chỉnh từ Kling 3.0...")
                                resp_vid = requests.get(kling_video_url, timeout=180)
                                resp_vid.raise_for_status()
                                st.session_state["final_video_bytes"] = resp_vid.content

                            save_video_history(
                                user_id=user_id,
                                prompt=motion_prompt.strip(),
                                video_url=kling_video_url,
                            )
                            status.update(label="🎉 Hoàn tất! Video đã sẵn sàng để xem và tải về.", state="complete", expanded=False)
                        except Exception as exc:
                            refund_credits(user_id, config.COST_VIDEO_GEN)
                            status.update(label="❌ Tạo video thất bại (Đã hoàn lại 10 Credits)", state="error")
                            st.error(f"Chi tiết lỗi: {exc}")
                        finally:
                            for tmp_file in (audio_path, merged_mp4_path):
                                if tmp_file and os.path.exists(tmp_file):
                                    try:
                                        os.remove(tmp_file)
                                    except Exception:
                                        pass

        # Hiển thị video kết quả & nút tải về
        if st.session_state.get("final_video_bytes"):
            st.markdown("#### 🎬 Thành phẩm Video của bạn")
            st.video(st.session_state["final_video_bytes"])
            st.download_button(
                label="⬇️ Tải Video MP4 Hoàn Chỉnh",
                data=st.session_state["final_video_bytes"],
                file_name="bap_ai_video_output.mp4",
                mime="video/mp4",
                type="primary",
                use_container_width=True,
            )


# ==============================================================================
# TAB 2: NẠP CREDITS (VIETQR)
# ==============================================================================
elif selected_tab == "💳 Nạp Credits (VietQR)":
    st.markdown("<h2 style='color:#F59E0B;'>💳 Nạp Credits qua VietQR (PVcomBank)</h2>", unsafe_allow_html=True)
    st.write("Chọn gói Credits phù hợp. Hệ thống tự động tạo mã QR chính xác số tiền và nội dung chuyển khoản.")

    pkg_cols = st.columns(3, gap="medium")
    for idx, pkg in enumerate(config.CREDIT_PACKAGES):
        with pkg_cols[idx]:
            card_class = "pkg-card-highlight" if pkg["id"] == "pro" else "pkg-card"
            st.markdown(
                f"""
                <div class="{card_class}">
                    <span style="background:#F59E0B; color:#0E1117; padding:3px 10px; border-radius:20px; font-size:11px; font-weight:800;">
                        {pkg['badge']}
                    </span>
                    <h3 style="color:#F8FAFC; margin:12px 0 4px 0;">{pkg['name']}</h3>
                    <div style="font-size:26px; font-weight:800; color:#F59E0B;">
                        {pkg['amount']:,} VNĐ
                    </div>
                    <div style="font-size:16px; font-weight:700; color:#34D399; margin:6px 0 10px 0;">
                        + {pkg['credits']} Credits
                    </div>
                    <p style="font-size:13px; color:#94A3B8;">{pkg['description']}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if st.button(f"Chọn {pkg['name']}", key=f"buy_{pkg['id']}", type="primary", use_container_width=True):
                try:
                    tx = create_transaction(
                        user_id=user_id,
                        amount=pkg["amount"],
                        credits=pkg["credits"],
                    )
                    transfer_code = config.build_transfer_content(user_id, tx["id"])
                    qr_url = config.build_vietqr_url(pkg["amount"], transfer_code)
                    st.session_state["active_tx"] = {
                        "tx_id": tx["id"],
                        "package_name": pkg["name"],
                        "amount": pkg["amount"],
                        "credits": pkg["credits"],
                        "transfer_content": transfer_code,
                        "qr_url": qr_url,
                        "confirmed_clicked": False,
                    }
                except Exception as exc:
                    st.error(f"Không thể khởi tạo đơn nạp tiền: {exc}")

    active_tx = st.session_state.get("active_tx")
    if active_tx:
        st.markdown("---")
        st.markdown(f"<h3 style='color:#F59E0B;'>📲 Quét mã VietQR để thanh toán — {active_tx['package_name']}</h3>", unsafe_allow_html=True)

        qr_col, info_col = st.columns([1, 1.3], gap="large")
        with qr_col:
            st.image(active_tx["qr_url"], caption="Mã VietQR tự động PVcomBank", width=320)

        with info_col:
            st.markdown(
                f"""
                <div class="bap-card">
                    <p><b>Ngân hàng:</b> {config.BANK_INFO['bank_name']} ({config.BANK_INFO['bank_code']} / BIN {config.BANK_INFO['bank_bin']})</p>
                    <p><b>Số tài khoản:</b> <span style="color:#F59E0B; font-size:18px; font-weight:800;">{config.BANK_INFO['account_number']}</span></p>
                    <p><b>Chủ tài khoản:</b> {config.BANK_INFO['account_name_vi']} ({config.BANK_INFO['account_name_ascii']})</p>
                    <p><b>Số tiền cần chuyển:</b> <span style="color:#34D399; font-size:18px; font-weight:800;">{active_tx['amount']:,} VNĐ</span></p>
                    <p><b>Số điểm nhận được:</b> {active_tx['credits']} Credits</p>
                    <p><b>Nội dung chuyển khoản bắt buộc:</b></p>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.code(active_tx["transfer_content"], language=None)

            if st.button("✅ Tôi đã chuyển khoản", type="primary", use_container_width=True):
                st.session_state["active_tx"]["confirmed_clicked"] = True
                st.success(
                    f"Đã ghi nhận thông báo chuyển khoản cho đơn `{active_tx['tx_id'][:8].upper()}`! "
                    "Admin sẽ kiểm tra và cộng Credits vào tài khoản của bạn trong ít phút."
                )

    st.markdown("---")
    st.markdown("### 🧾 Lịch sử giao dịch nạp Credits của bạn")
    try:
        my_txs = get_user_transactions(user_id)
        if not my_txs:
            st.info("Bạn chưa có giao dịch nạp Credits nào.")
        else:
            for item in my_txs:
                code = config.build_transfer_content(user_id, item["id"])
                status_badge = "🟢 Đã duyệt" if item["status"] == "completed" else "🟡 Chờ Admin duyệt"
                st.markdown(
                    f"""
                    <div class="bap-card" style="padding:12px 16px;">
                        <div style="display:flex; justify-content:space-between; align-items:center;">
                            <div>
                                <b>{item['amount']:,} VNĐ</b> (+{item['credits']} Credits) · Nội dung: <code>{code}</code>
                            </div>
                            <div>{status_badge}</div>
                        </div>
                        <div style="font-size:12px; color:#94A3B8; margin-top:4px;">Thời gian: {item['created_at']}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
    except Exception as exc:
        st.error(f"Lỗi tải lịch sử giao dịch: {exc}")


# ==============================================================================
# TAB 3: LỊCH SỬ VIDEO
# ==============================================================================
elif selected_tab == "🎬 Lịch sử":
    st.markdown("<h2 style='color:#F59E0B;'>🎬 Lịch sử Video đã tạo</h2>", unsafe_allow_html=True)

    try:
        histories = get_user_video_history(user_id)
        if not histories:
            st.info("Bạn chưa tạo video nào. Hãy sang Tab Studio AI để bắt đầu!")
        else:
            for idx, record in enumerate(histories):
                with st.container():
                    st.markdown(
                        f"""
                        <div class="bap-card">
                            <div style="font-size:12px; color:#94A3B8;">🕒 Tạo lúc: {record['created_at']}</div>
                            <div style="margin-top:6px; color:#F8FAFC;"><b>Prompt:</b> {record['prompt']}</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                    c_vid, c_act = st.columns([2, 1])
                    with c_vid:
                        st.video(record["video_url"])
                    with c_act:
                        st.link_button(
                            "🔗 Mở link video gốc",
                            record["video_url"],
                            use_container_width=True,
                        )
                        if st.button("⬇️ Chuẩn bị file tải về", key=f"prep_dl_{idx}", use_container_width=True):
                            try:
                                r = requests.get(record["video_url"], timeout=90)
                                r.raise_for_status()
                                st.download_button(
                                    label="💾 Lưu file MP4",
                                    data=r.content,
                                    file_name=f"bap_ai_video_{idx + 1}.mp4",
                                    mime="video/mp4",
                                    key=f"dl_btn_{idx}",
                                    type="primary",
                                    use_container_width=True,
                                )
                            except Exception as dl_err:
                                st.error(f"Không tải được video: {dl_err}")
                    st.markdown("<br>", unsafe_allow_html=True)
    except Exception as exc:
        st.error(f"Không thể tải lịch sử video: {exc}")


# ==============================================================================
# TAB 4: QUẢN TRỊ ADMIN (CHỈ HIỂN THỊ KHI KHỚP ADMIN_EMAIL)
# ==============================================================================
elif selected_tab == "🛡️ Quản trị Admin" and is_admin_user(user_email):
    st.markdown("<h2 style='color:#F59E0B;'>🛡️ Quản trị Admin — Duyệt đơn chuyển khoản VietQR</h2>", unsafe_allow_html=True)

    if st.button("🔄 Làm mới danh sách đơn chờ duyệt"):
        st.rerun()

    try:
        pending_orders = get_pending_transactions()
        if not pending_orders:
            st.success("Hiện không có đơn chuyển khoản nào đang chờ duyệt.")
        else:
            st.warning(f"Đang có {len(pending_orders)} đơn hàng chờ duyệt.")
            for order in pending_orders:
                profile_data = order.get("profiles") or {}
                customer_email = profile_data.get("email", "Không rõ email")
                transfer_note = config.build_transfer_content(order["user_id"], order["id"])

                col_info, col_btn = st.columns([3, 1], vertical_alignment="center")
                with col_info:
                    st.markdown(
                        f"""
                        <div class="bap-card">
                            <div><b>Khách hàng:</b> {customer_email}</div>
                            <div><b>Số tiền:</b> <span style="color:#34D399;">{order['amount']:,} VNĐ</span> → <b>+{order['credits']} Credits</b></div>
                            <div><b>Nội dung chuyển khoản:</b> <code>{transfer_note}</code></div>
                            <div style="font-size:12px; color:#94A3B8;">Mã đơn: {order['id']} · Tạo lúc: {order['created_at']}</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                with col_btn:
                    if st.button(
                        "✅ Duyệt đơn & Cộng điểm",
                        key=f"approve_{order['id']}",
                        type="primary",
                        use_container_width=True,
                    ):
                        ok, msg = approve_transaction(order["id"])
                        if ok:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)
    except Exception as exc:
        st.error(f"Lỗi tải danh sách đơn chờ duyệt: {exc}")
