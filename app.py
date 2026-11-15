
# -*- coding: utf-8 -*-
"""
BẮP AI VIDEO - TIKTOK SHOP EDITION
Image: FLUX Kontext
Video: Kling 3.0
Voice: Edge TTS
Database/Auth: Supabase
Payment: VietQR
"""

import os
import base64
import asyncio
import uuid
from pathlib import Path
from urllib.parse import quote

import streamlit as st
import fal_client
import edge_tts

from supabase import create_client, Client


# =====================================================
# 1. CẤU HÌNH ỨNG DỤNG
# =====================================================

st.set_page_config(
    page_title="BẮP AI VIDEO",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded"
)


def get_env(key, default=""):
    try:
        value = st.secrets.get(key, "")
        if value:
            return str(value)
    except Exception:
        pass

    return os.getenv(key, default)


SUPABASE_URL = get_env("SUPABASE_URL")
SUPABASE_KEY = get_env("SUPABASE_KEY")
FAL_KEY = get_env("FAL_KEY")
ADMIN_EMAIL = get_env(
    "ADMIN_EMAIL",
    "admin@example.com"
).lower().strip()


COST_IMAGE_EDIT = 2
COST_VIDEO_GEN = 10


# =====================================================
# 2. THÔNG TIN THANH TOÁN
# =====================================================

BANK_INFO = {
    "bank_code": "PVCB",
    "bank_bin": "970412",
    "bank_name": "PVcomBank",
    "account_number": "107004099152",
    "account_name_ascii": "NGO VAN KHANH",
}


CREDIT_PACKAGES = [
    {
        "id": "starter",
        "name": "GÓI CƠ BẢN",
        "amount": 50000,
        "credits": 50,
        "badge": "TIẾT KIỆM",
        "description": "Dành cho người mới bắt đầu."
    },
    {
        "id": "pro",
        "name": "GÓI PRO",
        "amount": 199000,
        "credits": 250,
        "badge": "PHỔ BIẾN",
        "description": "Dành cho nhà sáng tạo nội dung."
    },
    {
        "id": "studio",
        "name": "GÓI STUDIO",
        "amount": 499000,
        "credits": 700,
        "badge": "SIÊU ƯU ĐÃI",
        "description": "Dành cho người dùng chuyên nghiệp."
    }
]


VOICES = {
    "Nữ miền Nam - Hoài My": "vi-VN-HoaiMyNeural",
    "Nam miền Bắc - Nam Minh": "vi-VN-NamMinhNeural",
}


# =====================================================
# 3. GIAO DIỆN NỀN BẢN ĐỒ VIỆT NAM
# =====================================================

def load_background():

    bg_path = Path(__file__).parent / "bap_background.png"

    if not bg_path.exists():
        st.warning(
            "Chưa tìm thấy bap_background.png. "
            "Hãy tải ảnh nền lên GitHub cùng thư mục app.py."
        )
        return

    with open(bg_path, "rb") as image_file:
        bg_base64 = base64.b64encode(
            image_file.read()
        ).decode("utf-8")

    st.markdown(
        f"""
        <style>

        .stApp {{
            background:
                linear-gradient(
                    rgba(5, 5, 15, 0.68),
                    rgba(5, 5, 15, 0.82)
                ),
                url("data:image/png;base64,{bg_base64}");

            background-size: cover;
            background-position: center center;
            background-repeat: no-repeat;
            background-attachment: fixed;
        }}

        [data-testid="stHeader"] {{
            background: rgba(0,0,0,0.10);
        }}

        [data-testid="stSidebar"] {{
            background: rgba(10, 10, 22, 0.94);
            border-right: 1px solid rgba(255,215,0,0.25);
        }}

        [data-testid="stSidebar"] * {{
            color: white !important;
        }}

        h1, h2, h3, h4, p, label {{
            color: white !important;
        }}

        [data-testid="stMetric"] {{
            background: rgba(20,20,35,0.85);
            border: 1px solid rgba(255,215,0,0.35);
            border-radius: 15px;
            padding: 15px;
        }}

        [data-testid="stMetricValue"] {{
            color: #FFD700 !important;
        }}

        [data-testid="stMetricLabel"] {{
            color: white !important;
        }}

        [data-testid="stForm"] {{
            background: rgba(15,15,30,0.86);
            padding: 20px;
            border-radius: 18px;
            border: 1px solid rgba(255,215,0,0.30);
        }}

        div.stButton > button {{
            border-radius: 12px;
            font-weight: bold;
            min-height: 45px;
        }}

        div.stButton > button[kind="primary"] {{
            background: linear-gradient(90deg,#b8860b,#ffd700);
            color: #111 !important;
            border: none;
        }}

        div.stButton > button[kind="primary"]:hover {{
            background: #ffe45c;
            color: #111 !important;
        }}

        [data-testid="stTextInput"] input,
        [data-testid="stTextArea"] textarea {{
            border-radius: 10px;
        }}

        [data-testid="stFileUploader"] {{
            background: rgba(20,20,35,0.75);
            border-radius: 12px;
            padding: 10px;
        }}

        [data-testid="stTabs"] button {{
            color: white !important;
        }}

        hr {{
            border-color: rgba(255,215,0,0.3);
        }}

        </style>
        """,
        unsafe_allow_html=True
    )


# =====================================================
# 4. KẾT NỐI SUPABASE
# =====================================================

@st.cache_resource(show_spinner=False)
def get_supabase() -> Client:

    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError(
            "Thiếu SUPABASE_URL hoặc SUPABASE_KEY trong Secrets."
        )

    return create_client(
        SUPABASE_URL,
        SUPABASE_KEY
    )


def current_user():
    return st.session_state.get("user")


def rpc(name, params):
    return get_supabase().rpc(
        name,
        params
    ).execute().data


def refresh_profile():

    user = current_user()

    if not user:
        return None

    rows = (
        get_supabase()
        .table("profiles")
        .select("*")
        .eq("id", user.id)
        .limit(1)
        .execute()
        .data
    )

    return rows[0] if rows else None


def sign_out():

    try:
        get_supabase().auth.sign_out()
    except Exception:
        pass

    st.session_state.pop("user", None)
    st.session_state.pop("profile", None)
    st.session_state.pop("show_admin", None)

    st.rerun()


# =====================================================
# 5. ĐĂNG NHẬP - ĐĂNG KÝ - QUÊN MẬT KHẨU
# =====================================================

def auth_panel():

    st.title("🎬 BẮP AI VIDEO")

    st.caption(
        "SÁNG TẠO HÌNH ẢNH - VIDEO - GIỌNG ĐỌC BẰNG AI"
    )

    st.markdown(
        "🇻🇳 **HOÀNG SA, TRƯỜNG SA LÀ CỦA VIỆT NAM**"
    )

    sb = get_supabase()

    login_tab, signup_tab, forgot_tab = st.tabs([
        "🔐 ĐĂNG NHẬP",
        "✨ TẠO TÀI KHOẢN",
        "🔑 QUÊN MẬT KHẨU"
    ])

    # -----------------------------
    # ĐĂNG NHẬP
    # -----------------------------

    with login_tab:

        st.subheader("Chào mừng bạn quay lại!")

        with st.form("login_form"):

            email = st.text_input(
                "Email",
                placeholder="Nhập email"
            ).strip().lower()

            password = st.text_input(
                "Mật khẩu",
                type="password",
                placeholder="Nhập mật khẩu"
            )

            submitted = st.form_submit_button(
                "ĐĂNG NHẬP",
                use_container_width=True,
                type="primary"
            )

        if submitted:

            if not email or not password:
                st.warning("Vui lòng nhập email và mật khẩu.")

            else:

                try:

                    result = sb.auth.sign_in_with_password({
                        "email": email,
                        "password": password
                    })

                    if result.user:

                        st.session_state.user = result.user

                        st.session_state.pop(
                            "profile",
                            None
                        )

                        st.success("Đăng nhập thành công!")

                        st.rerun()

                except Exception as exc:

                    error = str(exc).lower()

                    if "invalid login credentials" in error:

                        st.error(
                            "Email hoặc mật khẩu không chính xác. "
                            "Hãy kiểm tra lại."
                        )

                    elif "email not confirmed" in error:

                        st.warning(
                            "Email chưa được xác nhận. "
                            "Hãy kiểm tra hộp thư."
                        )

                    elif "too many requests" in error:

                        st.warning(
                            "Bạn đã thử quá nhiều lần. "
                            "Hãy đợi một lúc."
                        )

                    else:

                        st.error(
                            f"Đăng nhập thất bại: {exc}"
                        )

    # -----------------------------
    # ĐĂNG KÝ
    # -----------------------------

    with signup_tab:

        st.subheader("Tạo tài khoản mới")

        with st.form("signup_form"):

            new_email = st.text_input(
                "Email",
                placeholder="Nhập email"
            ).strip().lower()

            new_password = st.text_input(
                "Mật khẩu",
                type="password",
                placeholder="Tối thiểu 8 ký tự"
            )

            confirm_password = st.text_input(
                "Xác nhận mật khẩu",
                type="password"
            )

            signup = st.form_submit_button(
                "TẠO TÀI KHOẢN",
                use_container_width=True,
                type="primary"
            )

        if signup:

            if not new_email or not new_password:

                st.warning("Vui lòng điền đầy đủ thông tin.")

            elif len(new_password) < 8:

                st.warning("Mật khẩu phải có ít nhất 8 ký tự.")

            elif new_password != confirm_password:

                st.error("Mật khẩu xác nhận không khớp.")

            else:

                try:

                    result = sb.auth.sign_up({
                        "email": new_email,
                        "password": new_password
                    })

                    if result.session and result.user:

                        st.session_state.user = result.user

                        st.success("Tạo tài khoản thành công!")

                        st.rerun()

                    else:

                        st.success(
                            "Đăng ký thành công! "
                            "Hãy xác nhận email trước khi đăng nhập."
                        )

                except Exception as exc:

                    st.error(
                        f"Không thể tạo tài khoản: {exc}"
                    )

    # -----------------------------
    # QUÊN MẬT KHẨU
    # -----------------------------

    with forgot_tab:

        st.subheader("Khôi phục mật khẩu")

        with st.form("forgot_form"):

            reset_email = st.text_input(
                "Email đăng ký",
                placeholder="Nhập email"
            ).strip().lower()

            reset = st.form_submit_button(
                "GỬI EMAIL KHÔI PHỤC",
                use_container_width=True,
                type="primary"
            )

        if reset:

            if not reset_email:

                st.warning("Vui lòng nhập email.")

            else:

                try:

                    sb.auth.reset_password_email(
                        reset_email
                    )

                    st.success(
                        "Đã gửi yêu cầu khôi phục. "
                        "Hãy kiểm tra email và thư mục Spam."
                    )

                except Exception as exc:

                    st.error(
                        f"Không gửi được email: {exc}"
                    )


# =====================================================
# 6. FAL AI
# =====================================================

def require_fal():

    if not FAL_KEY:

        st.error(
            "Chưa cấu hình FAL_KEY trong Streamlit Secrets."
        )

        return False

    os.environ["FAL_KEY"] = FAL_KEY

    return True


def upload_to_fal(uploaded_file):

    return fal_client.upload(
        uploaded_file.getvalue(),
        content_type=uploaded_file.type
    )


# =====================================================
# 7. CHỈNH SỬA ẢNH FLUX KONTEXT
# =====================================================

def image_workspace():

    st.header("🖼️ CHỈNH SỬA ẢNH AI")

    st.caption(
        f"FLUX Kontext | Chi phí: {COST_IMAGE_EDIT} Credits/lượt"
    )

    source = st.file_uploader(
        "Tải ảnh sản phẩm hoặc ảnh cần chỉnh sửa",
        type=["png", "jpg", "jpeg", "webp"],
        key="edit_image"
    )

    if source:

        st.image(
            source,
            caption="Ảnh gốc",
            use_container_width=True
        )

    prompt = st.text_area(
        "Mô tả chỉnh sửa",
        height=130,
        placeholder=(
            "Ví dụ: Đổi nền thành studio sang trọng, "
            "giữ nguyên hình dáng và màu sắc sản phẩm."
        )
    )

    if st.button(
        "✨ CHỈNH SỬA ẢNH",
        type="primary",
        use_container_width=True,
        disabled=not (source and prompt.strip())
    ):

        if not require_fal():
            return

        charged = False

        try:

            with st.spinner("Đang kiểm tra Credits..."):

                rpc(
                    "spend_credits",
                    {
                        "p_amount": COST_IMAGE_EDIT,
                        "p_reason": "FLUX Kontext"
                    }
                )

                charged = True

            with st.spinner("AI đang chỉnh sửa ảnh..."):

                image_url = upload_to_fal(source)

                result = fal_client.subscribe(
                    "fal-ai/flux-pro/kontext",
                    arguments={
                        "prompt": prompt.strip(),
                        "image_url": image_url,
                        "num_images": 1
                    }
                )

            images = result.get("images", [])

            if not images:

                raise RuntimeError(
                    "fal.ai không trả về ảnh kết quả."
                )

            result_url = images[0]["url"]

            st.success("Chỉnh sửa ảnh thành công!")

            st.image(
                result_url,
                caption="Ảnh AI đã tạo",
                use_container_width=True
            )

            st.markdown(
                f"[⬇️ Mở ảnh kết quả]({result_url})"
            )

        except Exception as exc:

            st.error(f"Chỉnh sửa ảnh thất bại: {exc}")

            if charged:

                st.warning(
                    "Yêu cầu đã được tính Credits trước khi xử lý. "
                    "Nếu API lỗi, hãy liên hệ quản trị viên để đối soát."
                )


# =====================================================
# 8. TẠO VIDEO KLING 3.0
# =====================================================

def video_workspace():

    st.header("🎥 TẠO VIDEO AI")

    st.caption(
        f"Kling 3.0 Standard | Chi phí: {COST_VIDEO_GEN} Credits/lượt"
    )

    source = st.file_uploader(
        "Tải ảnh bắt đầu video",
        type=["png", "jpg", "jpeg", "webp"],
        key="video_image"
    )

    if source:

        st.image(
            source,
            caption="Ảnh đầu vào",
            use_container_width=True
        )

    prompt = st.text_area(
        "Mô tả chuyển động video",
        height=150,
        placeholder=(
            "Ví dụ: Máy quay tiến chậm về phía sản phẩm, "
            "ánh sáng điện ảnh, chuyển động tự nhiên, "
            "giữ nguyên thiết kế sản phẩm."
        )
    )

    duration = st.selectbox(
        "Thời lượng video",
        ["5", "10", "15"],
        index=0
    )

    if st.button(
        "🎬 TẠO VIDEO KLING 3.0",
        type="primary",
        use_container_width=True,
        disabled=not (source and prompt.strip())
    ):

        if not require_fal():
            return

        charged = False

        try:

            with st.spinner("Đang kiểm tra Credits..."):

                rpc(
                    "spend_credits",
                    {
                        "p_amount": COST_VIDEO_GEN,
                        "p_reason": "Kling 3.0"
                    }
                )

                charged = True

            with st.spinner(
                "Kling đang tạo video. Vui lòng chờ..."
            ):

                image_url = upload_to_fal(source)

                result = fal_client.subscribe(
                    "fal-ai/kling-video/v3/standard/image-to-video",
                    arguments={
                        "image_url": image_url,
                        "prompt": prompt.strip(),
                        "duration": duration
                    }
                )

            video_url = result.get(
                "video",
                {}
            ).get("url")

            if not video_url:

                raise RuntimeError(
                    "Không nhận được video từ Kling."
                )

            st.success("Tạo video thành công!")

            st.video(video_url)

            st.markdown(
                f"[⬇️ Mở video kết quả]({video_url})"
            )

        except Exception as exc:

            st.error(f"Tạo video thất bại: {exc}")

            if charged:

                st.warning(
                    "Credits đã được ghi nhận khi bắt đầu xử lý. "
                    "Nếu API gặp lỗi, hãy liên hệ admin để đối soát."
                )


# =====================================================
# 9. GIỌNG ĐỌC AI TIẾNG VIỆT
# =====================================================

def tts_workspace():

    st.header("🎙️ GIỌNG ĐỌC AI")

    st.caption(
        "Tạo giọng đọc tiếng Việt bằng Microsoft Edge TTS."
    )

    text_content = st.text_area(
        "Nội dung cần đọc",
        height=200,
        placeholder="Nhập lời thoại quảng cáo của bạn..."
    )

    voice_label = st.selectbox(
        "Chọn giọng đọc",
        list(VOICES.keys())
    )

    rate = st.select_slider(
        "Tốc độ đọc",
        options=[
            "-20%",
            "-10%",
            "+0%",
            "+10%",
            "+20%"
        ],
        value="+0%"
    )

    if st.button(
        "🎙️ TẠO GIỌNG ĐỌC",
        type="primary",
        use_container_width=True,
        disabled=not text_content.strip()
    ):

        try:

            async def make_audio():

                communicate = edge_tts.Communicate(
                    text_content.strip(),
                    VOICES[voice_label],
                    rate=rate
                )

                chunks = []

                async for chunk in communicate.stream():

                    if chunk["type"] == "audio":

                        chunks.append(chunk["data"])

                return b"".join(chunks)

            with st.spinner("Đang tạo giọng đọc..."):

                audio = asyncio.run(make_audio())

            if audio:

                st.success("Tạo giọng đọc thành công!")

                st.audio(
                    audio,
                    format="audio/mpeg"
                )

                st.download_button(
                    "⬇️ TẢI FILE MP3",
                    data=audio,
                    file_name="bap_ai_voice.mp3",
                    mime="audio/mpeg",
                    use_container_width=True
                )

            else:

                st.error("Không nhận được dữ liệu âm thanh.")

        except Exception as exc:

            st.error(f"Lỗi tạo giọng đọc: {exc}")


# =====================================================
# 10. VIETQR
# =====================================================

def build_transfer_content(user_id, tx_id):

    return (
        f"BAPAI "
        f"{user_id.replace('-', '')[:4].upper()} "
        f"{tx_id.replace('-', '')[:4].upper()}"
    )


def build_vietqr_url(amount, add_info):

    bank = BANK_INFO["bank_code"]
    stk = BANK_INFO["account_number"]

    name = quote(
        BANK_INFO["account_name_ascii"]
    )

    info = quote(add_info)

    return (
        f"https://img.vietqr.io/image/"
        f"{bank}-{stk}-compact2.png"
        f"?amount={amount}"
        f"&addInfo={info}"
        f"&accountName={name}"
    )


# =====================================================
# 11. NẠP CREDITS
# =====================================================

def topup_workspace(user):

    st.header("💳 NẠP CREDITS")

    st.warning(
        "Chuyển khoản đúng số tiền và nội dung. "
        "Credits chỉ được cộng sau khi admin xác nhận."
    )

    for package in CREDIT_PACKAGES:

        with st.container(border=True):

            c1, c2, c3 = st.columns([2, 1, 1])

            c1.markdown(
                f"### {package['name']}"
            )

            c1.caption(
                package["description"]
            )

            c1.caption(
                package["badge"]
            )

            c2.markdown(
                f"**{package['amount']:,}đ**"
            )

            c2.write(
                f"{package['credits']} Credits"
            )

            if c3.button(
                "CHỌN GÓI",
                key=f"buy_{package['id']}"
            ):

                try:

                    tx_id = str(uuid.uuid4())

                    content = build_transfer_content(
                        user.id,
                        tx_id
                    )

                    get_supabase().table(
                        "topups"
                    ).insert({
                        "id": tx_id,
                        "user_id": user.id,
                        "package_id": package["id"],
                        "amount_vnd": package["amount"],
                        "credits": package["credits"],
                        "transfer_content": content,
                        "status": "pending"
                    }).execute()

                    st.session_state["active_topup"] = {
                        "id": tx_id,
                        "amount": package["amount"],
                        "content": content
                    }

                    st.success("Đã tạo yêu cầu nạp Credits.")

                except Exception as exc:

                    st.error(
                        f"Không tạo được yêu cầu: {exc}"
                    )

    pending = st.session_state.get("active_topup")

    if pending:

        st.divider()

        st.subheader("📱 THÔNG TIN CHUYỂN KHOẢN")

        st.image(
            build_vietqr_url(
                pending["amount"],
                pending["content"]
            ),
            width=300
        )

        st.write(
            f"Ngân hàng: {BANK_INFO['bank_name']}"
        )

        st.write(
            f"Số tài khoản: {BANK_INFO['account_number']}"
        )

        st.write(
            f"Chủ tài khoản: {BANK_INFO['account_name_ascii']}"
        )

        st.markdown("**Nội dung chuyển khoản:**")

        st.code(pending["content"])

        st.caption(
            "Không sửa nội dung chuyển khoản. "
            "Sau khi chuyển tiền, chờ admin xác nhận."
        )


# =====================================================
# 12. LỊCH SỬ GIAO DỊCH
# =====================================================

def history_workspace(user):

    st.header("📜 LỊCH SỬ GIAO DỊCH")

    try:

        rows = (
            get_supabase()
            .table("topups")
            .select(
                "created_at,amount_vnd,credits,status,transfer_content"
            )
            .eq("user_id", user.id)
            .order("created_at", desc=True)
            .limit(30)
            .execute()
            .data
        )

        if rows:

            st.dataframe(
                rows,
                use_container_width=True,
                hide_index=True
            )

        else:

            st.info("Bạn chưa có giao dịch.")

    except Exception as exc:

        st.error(
            f"Không tải được lịch sử: {exc}"
        )


# =====================================================
# 13. QUẢN TRỊ VIÊN
# =====================================================

def admin_workspace():

    st.header("🛡️ QUẢN TRỊ BẮP AI VIDEO")

    st.caption(
        "Chỉ tài khoản ADMIN_EMAIL mới có quyền truy cập."
    )

    try:

        rows = (
            get_supabase()
            .table("topups")
            .select("*")
            .eq("status", "pending")
            .order("created_at", desc=False)
            .limit(100)
            .execute()
            .data
        )

        if not rows:

            st.success(
                "Không có yêu cầu nạp Credits đang chờ."
            )

        for item in rows:

            with st.container(border=True):

                st.subheader(
                    f"{item['amount_vnd']:,}đ"
                )

                st.write(
                    f"Credits: {item['credits']}"
                )

                st.write(
                    f"User ID: {item['user_id']}"
                )

                st.code(
                    item["transfer_content"]
                )

                if st.button(
                    "✅ XÁC NHẬN ĐÃ NHẬN TIỀN",
                    key=f"approve_{item['id']}"
                ):

                    try:

                        rpc(
                            "admin_approve_topup",
                            {
                                "p_topup_id": item["id"]
                            }
                        )

                        st.success(
                            "Đã xác nhận và cộng Credits."
                        )

                        st.rerun()

                    except Exception as exc:

                        st.error(
                            f"Không xác nhận được: {exc}"
                        )

    except Exception as exc:

        st.error(
            f"Không tải được yêu cầu nạp tiền: {exc}"
        )


# =====================================================
# 14. TRANG CHỦ
# =====================================================

def main():

    load_background()

    # Kiểm tra cấu hình Supabase

    if not SUPABASE_URL or not SUPABASE_KEY:

        st.title("🎬 BẮP AI VIDEO")

        st.error(
            "Chưa cấu hình Supabase. "
            "Hãy kiểm tra Streamlit Secrets."
        )

        st.stop()

    # Chưa đăng nhập

    if not current_user():

        auth_panel()

        return

    user = current_user()

    # Lấy hồ sơ

    try:

        profile = refresh_profile()

        if not profile:

            st.error(
                "Không tìm thấy hồ sơ người dùng. "
                "Hãy kiểm tra bảng profiles và trigger tạo hồ sơ "
                "trong Supabase."
            )

            if st.button("ĐĂNG XUẤT"):

                sign_out()

            return

        st.session_state.profile = profile

    except Exception as exc:

        st.error(
            f"Không tải được hồ sơ: {exc}"
        )

        st.stop()

    # Sidebar

    with st.sidebar:

        st.title("🎬 BẮP AI VIDEO")

        st.caption(
            "🇻🇳 SÁNG TẠO CÙNG AI"
        )

        st.divider()

        st.write(
            f"👤 {user.email}"
        )

        st.metric(
            "SỐ DƯ CREDITS",
            profile.get("credits", 0)
        )

        st.caption(
            "Ảnh: 2 Credits | Video: 10 Credits"
        )

        if st.button(
            "🚪 ĐĂNG XUẤT",
            use_container_width=True
        ):

            sign_out()

        st.divider()

        page = st.radio(
            "MENU CHỨC NĂNG",
            [
                "🏠 Tổng quan",
                "🖼️ Chỉnh sửa ảnh",
                "🎥 Tạo video",
                "🎙️ Giọng đọc AI",
                "💳 Nạp Credits",
                "📜 Lịch sử giao dịch"
            ]
        )

        # Chỉ admin được mở quản trị

        is_admin = (
            (user.email or "").lower() == ADMIN_EMAIL
        )

        if is_admin:

            st.divider()

            if st.button(
                "🛡️ MỞ QUẢN TRỊ",
                use_container_width=True
            ):

                st.session_state["show_admin"] = True

            if st.button(
                "Đóng quản trị",
                use_container_width=True
            ):

                st.session_state["show_admin"] = False

    # Nội dung chính

    st.title("CHÀO MỪNG ĐẾN VỚI BẮP AI VIDEO 🇻🇳")

    st.caption(
        "Không gian sáng tạo nội dung bằng trí tuệ nhân tạo."
    )

    if page == "🏠 Tổng quan":

        st.subheader("TỔNG QUAN TÀI KHOẢN")

        c1, c2, c3 = st.columns(3)

        c1.metric(
            "Credits hiện có",
            profile.get("credits", 0)
        )

        c2.metric(
            "Chỉnh sửa ảnh",
            f"{COST_IMAGE_EDIT} Credits"
        )

        c3.metric(
            "Tạo video",
            f"{COST_VIDEO_GEN} Credits"
        )

        st.divider()

        st.subheader("CÔNG CỤ AI")

        c1, c2 = st.columns(2)

        with c1:

            st.markdown("### 🖼️ FLUX KONTEXT")

            st.write(
                "Chỉnh sửa ảnh sản phẩm, thay đổi bối cảnh "
                "và sáng tạo hình ảnh bằng AI."
            )

        with c2:

            st.markdown("### 🎥 KLING 3.0")

            st.write(
                "Biến hình ảnh thành video AI "
                "với chuyển động điện ảnh."
            )

        c3, c4 = st.columns(2)

        with c3:

            st.markdown("### 🎙️ EDGE TTS")

            st.write(
                "Tạo giọng đọc tiếng Việt "
                "cho video quảng cáo."
            )

        with c4:

            st.markdown("### 💳 CREDITS")

            st.write(
                "Nạp Credits và theo dõi giao dịch "
                "ngay trong ứng dụng."
            )

        st.divider()

        st.markdown(
            "**BẮP AI VIDEO** · FLUX KONTEXT · KLING 3.0 · EDGE TTS"
        )

        st.markdown(
            "🇻🇳 **HOÀNG SA, TRƯỜNG SA LÀ CỦA VIỆT NAM**"
        )

    elif page == "🖼️ Chỉnh sửa ảnh":

        image_workspace()

    elif page == "🎥 Tạo video":

        video_workspace()

    elif page == "🎙️ Giọng đọc AI":

        tts_workspace()

    elif page == "💳 Nạp Credits":

        topup_workspace(user)

    elif page == "📜 Lịch sử giao dịch":

        history_workspace(user)

    # Khu vực quản trị

    if (
        st.session_state.get("show_admin")
        and (user.email or "").lower() == ADMIN_EMAIL
    ):

        st.divider()

        admin_workspace()


# =====================================================
# 15. CHẠY ỨNG DỤNG
# =====================================================

if __name__ == "__main__":

    try:

        main()

    except Exception as error:

        st.error(
            f"Ứng dụng gặp lỗi: {error}"
        )

        st.info(
            "Hãy kiểm tra Streamlit Logs để xem chi tiết."
        )
