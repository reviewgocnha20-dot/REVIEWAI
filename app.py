
# -*- coding: utf-8 -*-
"""
BẮP AI VIDEO — FULL APP
Streamlit + Supabase + fal.ai + Edge TTS

Secrets:
SUPABASE_URL
SUPABASE_KEY
FAL_KEY
ADMIN_EMAIL

Không đưa Service Role Key lên GitHub công khai.
"""

import os
import asyncio
import uuid
from datetime import datetime
from urllib.parse import quote

import streamlit as st
from dotenv import load_dotenv
from supabase import create_client, Client
import fal_client
import edge_tts

load_dotenv()

# =========================================================
# 1. CẤU HÌNH
# =========================================================

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


SUPABASE_URL = get_env("SUPABASE_URL").strip()
SUPABASE_KEY = get_env("SUPABASE_KEY").strip()
FAL_KEY = get_env("FAL_KEY").strip()

ADMIN_EMAIL = get_env(
    "ADMIN_EMAIL",
    "ngok12030@gmail.com"
).strip().lower()

COST_IMAGE_EDIT = 2
COST_VIDEO_GEN = 10

BANK_INFO = {
    "bank_code": "PVCB",
    "bank_name": "PVcomBank",
    "account_number": "107004099152",
    "account_name_ascii": "NGO VAN KHANH",
}

CREDIT_PACKAGES = [
    {
        "id": "starter",
        "name": "Gói Cơ Bản",
        "amount": 50000,
        "credits": 50,
        "badge": "TIẾT KIỆM",
        "description": "Dành cho trải nghiệm AI."
    },
    {
        "id": "pro",
        "name": "Gói Pro",
        "amount": 199000,
        "credits": 250,
        "badge": "PHỔ BIẾN",
        "description": "Dành cho người bán hàng."
    },
    {
        "id": "studio",
        "name": "Gói Studio",
        "amount": 499000,
        "credits": 700,
        "badge": "ƯU ĐÃI",
        "description": "Dành cho sản xuất hàng loạt."
    },
]

VOICES = {
    "Nữ miền Nam — Hoài My": "vi-VN-HoaiMyNeural",
    "Nam miền Bắc — Nam Minh": "vi-VN-NamMinhNeural",
}


# =========================================================
# 2. KHỞI TẠO SESSION
# =========================================================

if "creation_history" not in st.session_state:
    st.session_state.creation_history = []

if "show_admin" not in st.session_state:
    st.session_state.show_admin = False

if "active_topup" not in st.session_state:
    st.session_state.active_topup = None


def add_history(kind, description, result_url=""):
    item = {
        "time": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "type": kind,
        "description": description,
        "url": result_url,
    }

    st.session_state.creation_history.insert(0, item)


# =========================================================
# 3. GIAO DIỆN
# =========================================================

st.markdown("""
<style>

.stApp {
    background: linear-gradient(
        135deg,
        #8f5a00 0%,
        #c58a13 45%,
        #704300 100%
    );
}

header[data-testid="stHeader"] {
    background: transparent;
}

section[data-testid="stSidebar"] {
    background: #4c2d00;
}

section[data-testid="stSidebar"] * {
    color: #fff4d0 !important;
}

h1, h2, h3, h4, p, label,
.stMarkdown, .stCaption {
    color: #fff8e5;
}

[data-testid="stMetric"] {
    background: rgba(255,255,255,0.13);
    border: 1px solid rgba(255,255,255,0.3);
    padding: 16px;
    border-radius: 14px;
}

[data-testid="stMetricValue"] {
    color: #fff4bd;
}

.stButton > button {
    background: #ffd34e;
    color: #422900;
    border: none;
    border-radius: 12px;
    font-weight: bold;
    min-height: 45px;
}

.stButton > button:hover {
    background: #ffe58a;
    color: #422900;
}

.stTextInput input,
.stTextArea textarea,
.stSelectbox div[data-baseweb="select"] {
    background: #fffdf5;
    color: #222;
    border-radius: 10px;
}

div[data-testid="stForm"] {
    background: rgba(255,255,255,0.10);
    padding: 18px;
    border-radius: 15px;
    border: 1px solid rgba(255,255,255,0.3);
}

div[data-testid="stVerticalBlockBorderWrapper"] {
    background: rgba(255,255,255,0.10);
    border-radius: 14px;
}

hr {
    border-color: rgba(255,255,255,0.3);
}

</style>
""", unsafe_allow_html=True)


# =========================================================
# 4. SUPABASE
# =========================================================

@st.cache_resource(show_spinner=False)
def get_supabase() -> Client:

    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError(
            "Thiếu SUPABASE_URL hoặc SUPABASE_KEY."
        )

    if not SUPABASE_URL.isascii():
        raise RuntimeError(
            "SUPABASE_URL chứa ký tự ngoài ASCII. "
            "Hãy kiểm tra Streamlit Secrets."
        )

    if not SUPABASE_KEY.isascii():
        raise RuntimeError(
            "SUPABASE_KEY chứa ký tự ngoài ASCII. "
            "Hãy kiểm tra Streamlit Secrets."
        )

    return create_client(
        SUPABASE_URL,
        SUPABASE_KEY
    )


def current_user():
    return st.session_state.get("user")


def rpc(name, params):
    return (
        get_supabase()
        .rpc(name, params)
        .execute()
        .data
    )


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


# =========================================================
# 5. KIỂM TRA ADMIN
# =========================================================

def is_admin(user):

    if not user:
        return False

    email = (user.email or "").strip().lower()

    # Kiểm tra email quản trị
    if email and email == ADMIN_EMAIL:
        return True

    # Kiểm tra bảng admin_users
    try:

        result = (
            get_supabase()
            .table("admin_users")
            .select("user_id")
            .eq("user_id", user.id)
            .limit(1)
            .execute()
        )

        return bool(result.data)

    except Exception:
        return False


# =========================================================
# 6. ĐĂNG XUẤT
# =========================================================

def sign_out():

    try:
        get_supabase().auth.sign_out()
    except Exception:
        pass

    st.session_state.pop("user", None)
    st.session_state.pop("profile", None)
    st.session_state.pop("show_admin", None)
    st.session_state.pop("active_topup", None)

    st.rerun()


# =========================================================
# 7. ĐĂNG NHẬP / ĐĂNG KÝ
# =========================================================

def auth_panel():

    st.title("🎬 BẮP AI VIDEO")
    st.caption("Sáng tạo hình ảnh, video và giọng đọc bằng AI")

    login_tab, signup_tab = st.tabs([
        "Đăng nhập",
        "Tạo tài khoản"
    ])

    sb = get_supabase()

    with login_tab:

        with st.form("login_form"):

            email = st.text_input(
                "Email",
                key="login_email"
            )

            password = st.text_input(
                "Mật khẩu",
                type="password",
                key="login_password"
            )

            submitted = st.form_submit_button(
                "Đăng nhập",
                use_container_width=True
            )

        if submitted:

            try:

                if not email.strip() or not password:
                    st.warning("Vui lòng nhập email và mật khẩu.")
                else:

                    result = sb.auth.sign_in_with_password({
                        "email": email.strip(),
                        "password": password
                    })

                    if not result.user:
                        st.error("Không tìm thấy tài khoản.")
                    else:
                        st.session_state.user = result.user
                        st.session_state.show_admin = False
                        st.success("Đăng nhập thành công!")
                        st.rerun()

            except UnicodeEncodeError:
                st.error(
                    "Lỗi mã hóa ASCII. "
                    "Hãy kiểm tra SUPABASE_URL và SUPABASE_KEY "
                    "trong Streamlit Secrets."
                )

            except Exception as exc:
                st.error(
                    f"Đăng nhập không thành công: {str(exc)}"
                )

    with signup_tab:

        with st.form("signup_form"):

            email = st.text_input(
                "Email",
                key="signup_email"
            )

            password = st.text_input(
                "Mật khẩu (ít nhất 8 ký tự)",
                type="password",
                key="signup_password"
            )

            submitted = st.form_submit_button(
                "Tạo tài khoản",
                use_container_width=True
            )

        if submitted:

            if len(password) < 8:
                st.warning("Mật khẩu cần ít nhất 8 ký tự.")

            else:

                try:

                    result = sb.auth.sign_up({
                        "email": email.strip(),
                        "password": password
                    })

                    if result.session:

                        st.session_state.user = result.user
                        st.success("Tạo tài khoản thành công.")
                        st.rerun()

                    else:

                        st.success(
                            "Đã gửi email xác nhận. "
                            "Hãy xác nhận email rồi đăng nhập."
                        )

                except Exception as exc:
                    st.error(f"Không thể tạo tài khoản: {str(exc)}")


# =========================================================
# 8. FAL AI
# =========================================================

def require_fal():

    if not FAL_KEY:
        st.error("Chưa cấu hình FAL_KEY trong Secrets.")
        return False

    os.environ["FAL_KEY"] = FAL_KEY

    return True


def upload_to_fal(uploaded_file):

    return fal_client.upload(
        uploaded_file.getvalue(),
        content_type=uploaded_file.type
    )


# =========================================================
# 9. TẠO ẢNH
# =========================================================

def image_workspace():

    st.subheader("🖼️ TẠO / CHỈNH SỬA ẢNH")
    st.caption("FLUX Kontext · 2 Credits / lượt")

    source = st.file_uploader(
        "Chọn ảnh sản phẩm",
        type=["png", "jpg", "jpeg", "webp"],
        key="edit_image"
    )

    prompt = st.text_area(
        "Mô tả hình ảnh muốn tạo",
        placeholder="Ví dụ: Đổi bối cảnh thành studio cao cấp, giữ nguyên sản phẩm và màu sắc."
    )

    if st.button(
        "✨ CHỈNH SỬA ẢNH",
        type="primary",
        disabled=not (source and prompt.strip())
    ):

        if not require_fal():
            return

        try:

            with st.spinner("Đang kiểm tra Credits..."):

                rpc(
                    "spend_credits",
                    {
                        "p_amount": COST_IMAGE_EDIT,
                        "p_reason": "FLUX Kontext"
                    }
                )

            with st.spinner("AI đang xử lý hình ảnh..."):

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
                raise RuntimeError("Không nhận được ảnh từ fal.ai.")

            output_url = images[0]["url"]

            st.image(
                output_url,
                caption="Ảnh đã hoàn thành",
                use_container_width=True
            )

            st.markdown(f"[⬇️ Mở ảnh kết quả]({output_url})")

            add_history(
                "Ảnh AI",
                prompt.strip(),
                output_url
            )

            st.success("Tạo ảnh thành công!")

        except Exception as exc:

            st.error(f"Tạo ảnh thất bại: {str(exc)}")

            st.info(
                "Nếu Credits đã bị trừ nhưng API gặp lỗi, "
                "hãy liên hệ quản trị viên để đối soát."
            )


# =========================================================
# 10. TẠO VIDEO
# =========================================================

def video_workspace():

    st.subheader("🎥 TẠO VIDEO AI")
    st.caption("Kling 3.0 · 10 Credits / lượt")

    source = st.file_uploader(
        "Chọn ảnh bắt đầu video",
        type=["png", "jpg", "jpeg", "webp"],
        key="video_image"
    )

    prompt = st.text_area(
        "Mô tả chuyển động",
        placeholder="Ví dụ: Người mẫu giới thiệu sản phẩm tự nhiên, máy quay tiến chậm, chuyển động chân thật."
    )

    duration = st.selectbox(
        "Thời lượng video",
        ["5", "10", "15"]
    )

    if st.button(
        "🎬 TẠO VIDEO NGAY",
        type="primary",
        disabled=not (source and prompt.strip())
    ):

        if not require_fal():
            return

        try:

            with st.spinner("Đang kiểm tra Credits..."):

                rpc(
                    "spend_credits",
                    {
                        "p_amount": COST_VIDEO_GEN,
                        "p_reason": "Kling 3.0"
                    }
                )

            with st.spinner(
                "🎬 Kling đang tạo video. "
                "Vui lòng chờ trong vài phút..."
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

            video_url = (
                result.get("video", {}).get("url")
            )

            if not video_url:
                raise RuntimeError(
                    f"Không nhận được video từ fal.ai: {result}"
                )

            st.video(video_url)

            st.markdown(
                f"[⬇️ MỞ VIDEO KẾT QUẢ]({video_url})"
            )

            add_history(
                "Video AI",
                prompt.strip(),
                video_url
            )

            st.success("🎉 VIDEO ĐÃ TẠO THÀNH CÔNG!")

        except Exception as exc:

            st.error(f"Tạo video thất bại: {str(exc)}")

            st.info(
                "Nếu Credits đã bị trừ nhưng API gặp lỗi, "
                "hãy liên hệ quản trị viên để đối soát."
            )


# =========================================================
# 11. GIỌNG ĐỌC AI
# =========================================================

def tts_workspace():

    st.subheader("🎙️ GIỌNG ĐỌC AI")
    st.caption("Tạo giọng đọc tiếng Việt bằng Edge TTS.")

    text = st.text_area(
        "Nội dung cần đọc",
        height=160
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
        disabled=not text.strip()
    ):

        try:

            async def make_audio():

                communicate = edge_tts.Communicate(
                    text.strip(),
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

                st.audio(
                    audio,
                    format="audio/mpeg"
                )

                st.download_button(
                    "⬇️ TẢI MP3",
                    audio,
                    "bap_ai_voice.mp3",
                    "audio/mpeg"
                )

                add_history(
                    "Giọng đọc AI",
                    text.strip()
                )

                st.success("Đã tạo giọng đọc thành công.")

            else:
                st.error("Không nhận được dữ liệu âm thanh.")

        except Exception as exc:

            st.error(
                f"Không tạo được giọng đọc: {str(exc)}"
            )


# =========================================================
# 12. NẠP CREDITS
# =========================================================

def build_transfer_content(user_id, tx_id):

    return (
        f"BAPAI "
        f"{user_id.replace('-', '')[:4].upper()} "
        f"{tx_id.replace('-', '')[:4].upper()}"
    )


def build_vietqr_url(amount, add_info):

    bank = BANK_INFO["bank_code"]
    stk = BANK_INFO["account_number"]

    name = quote(BANK_INFO["account_name_ascii"])
    info = quote(add_info)

    return (
        f"https://img.vietqr.io/image/"
        f"{bank}-{stk}-compact2.png"
        f"?amount={amount}"
        f"&addInfo={info}"
        f"&accountName={name}"
    )


def topup_workspace(user):

    st.subheader("💳 NẠP CREDITS QUA VIETQR")

    st.warning(
        "Credits chỉ được cộng sau khi Admin xác nhận chuyển khoản."
    )

    for package in CREDIT_PACKAGES:

        with st.container(border=True):

            c1, c2, c3 = st.columns([2, 2, 1])

            c1.markdown(
                f"**{package['name']}** · {package['badge']}"
            )

            c1.caption(package["description"])

            c2.markdown(
                f"**{package['amount']:,}đ**"
            )

            c2.write(
                f"{package['credits']} Credits"
            )

            if c3.button(
                "Chọn gói",
                key=f"buy_{package['id']}"
            ):

                try:

                    tx_id = str(uuid.uuid4())

                    content = build_transfer_content(
                        user.id,
                        tx_id
                    )

                    get_supabase().table("topups").insert({

                        "id": tx_id,
                        "user_id": user.id,
                        "package_id": package["id"],
                        "amount_vnd": package["amount"],
                        "credits": package["credits"],
                        "transfer_content": content,
                        "status": "pending"

                    }).execute()

                    st.session_state.active_topup = {
                        "id": tx_id,
                        "amount": package["amount"],
                        "content": content
                    }

                    st.rerun()

                except Exception as exc:

                    st.error(
                        f"Không tạo được yêu cầu nạp: {str(exc)}"
                    )

    pending = st.session_state.active_topup

    if pending:

        st.divider()

        st.markdown("### THÔNG TIN CHUYỂN KHOẢN")

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

        st.code(pending["content"])

        st.caption(
            "Không sửa nội dung chuyển khoản. "
            "Chờ Admin xác nhận sau khi thanh toán."
        )


# =========================================================
# 13. LỊCH SỬ GIAO DỊCH
# =========================================================

def history_workspace(user):

    st.subheader("📜 LỊCH SỬ NẠP CREDITS")

    try:

        rows = (
            get_supabase()
            .table("topups")
            .select(
                "created_at,amount_vnd,credits,status,transfer_content"
            )
            .eq("user_id", user.id)
            .order("created_at", desc=True)
            .limit(50)
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

            st.info("Chưa có giao dịch.")

    except Exception as exc:

        st.error(
            f"Không tải được lịch sử: {str(exc)}"
        )


# =========================================================
# 14. LỊCH SỬ SẢN PHẨM ĐÃ TẠO
# =========================================================

def creation_history_workspace():

    st.subheader("📁 LỊCH SỬ SẢN PHẨM ĐÃ TẠO")

    st.caption(
        "Lịch sử trong phiên làm việc hiện tại. "
        "Các kết quả có đường dẫn có thể mở lại."
    )

    history = st.session_state.creation_history

    if not history:

        st.info("Bạn chưa tạo ảnh, video hoặc giọng đọc nào.")

        return

    if st.button("🗑️ Xóa lịch sử phiên hiện tại"):

        st.session_state.creation_history = []

        st.rerun()

    for index, item in enumerate(history):

        with st.container(border=True):

            st.markdown(
                f"**{item['type']}**"
            )

            st.caption(item["time"])

            st.write(item["description"])

            if item["url"]:

                if item["type"] == "Video AI":

                    st.video(item["url"])

                elif item["type"] == "Ảnh AI":

                    st.image(
                        item["url"],
                        use_container_width=True
                    )

                st.markdown(
                    f"[Mở kết quả]({item['url']})"
                )


# =========================================================
# 15. ADMIN
# =========================================================

def admin_workspace():

    st.subheader("🛡️ QUẢN TRỊ BẮP AI VIDEO")

    st.caption(
        "Quản lý yêu cầu nạp Credits và xác nhận thanh toán."
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

                st.markdown(
                    f"### {item['amount_vnd']:,}đ"
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
                            f"Không xác nhận được: {str(exc)}"
                        )

    except Exception as exc:

        st.error(
            f"Không tải được yêu cầu nạp: {str(exc)}"
        )


# =========================================================
# 16. MAIN APP
# =========================================================

def main():

    if not SUPABASE_URL or not SUPABASE_KEY:

        st.title("🎬 BẮP AI VIDEO")

        st.error(
            "Chưa cấu hình Supabase. "
            "Hãy thêm SUPABASE_URL và SUPABASE_KEY "
            "vào Streamlit Secrets."
        )

        st.stop()

    # CHƯA ĐĂNG NHẬP
    if not current_user():

        auth_panel()

        return

    user = current_user()

    # LẤY PROFILE
    try:

        profile = refresh_profile()

        if not profile:

            st.error(
                "Không tìm thấy hồ sơ người dùng. "
                "Hãy kiểm tra trigger tạo profiles trong Supabase."
            )

            if st.button("Đăng xuất"):
                sign_out()

            return

        st.session_state.profile = profile

    except Exception as exc:

        st.error(
            f"Không tải được hồ sơ: {str(exc)}"
        )

        st.stop()

    # KIỂM TRA ADMIN
    admin_status = is_admin(user)

    # SIDEBAR
    with st.sidebar:

        st.title("🎬 BẮP AI VIDEO")

        st.caption("AI CONTENT CREATOR")

        st.write(user.email)

        st.metric(
            "💰 Số dư Credits",
            profile.get("credits", 0)
        )

        st.caption(
            "Ảnh: 2 Credits · Video: 10 Credits"
        )

        st.divider()

        if st.button(
            "🚪 ĐĂNG XUẤT",
            use_container_width=True
        ):

            sign_out()

        st.divider()

        menu = [
            "Tổng quan",
            "Chỉnh sửa ảnh",
            "Tạo video",
            "Giọng đọc AI",
            "Nạp Credits",
            "Lịch sử giao dịch",
            "Lịch sử sản phẩm"
        ]

        if admin_status:
            menu.append("Quản trị Admin")

        page = st.radio(
            "MENU CHỨC NĂNG",
            menu
        )

    # NỘI DUNG CHÍNH
    st.title("🎬 BẮP AI VIDEO")

    st.caption(
        "Không gian sáng tạo hình ảnh, video và giọng đọc bằng AI."
    )

    if page == "Tổng quan":

        st.subheader("Xin chào! 👋")

        c1, c2, c3 = st.columns(3)

        c1.metric(
            "Credits hiện có",
            profile.get("credits", 0)
        )

        c2.metric(
            "Chi phí chỉnh ảnh",
            f"{COST_IMAGE_EDIT} Credits"
        )

        c3.metric(
            "Chi phí tạo video",
            f"{COST_VIDEO_GEN} Credits"
        )

        st.divider()

        st.markdown("### 🚀 CÔNG CỤ AI")

        col1, col2, col3 = st.columns(3)

        with col1:

            st.markdown("#### 🖼️ Tạo ảnh")

            st.write("Chỉnh sửa ảnh bằng FLUX Kontext.")

        with col2:

            st.markdown("#### 🎥 Tạo video")

            st.write("Biến ảnh thành video bằng Kling 3.0.")

        with col3:

            st.markdown("#### 🎙️ Giọng đọc")

            st.write("Tạo giọng đọc tiếng Việt tự nhiên.")

        st.info(
            "Chọn chức năng tại thanh MENU bên trái để bắt đầu."
        )

    elif page == "Chỉnh sửa ảnh":

        image_workspace()

    elif page == "Tạo video":

        video_workspace()

    elif page == "Giọng đọc AI":

        tts_workspace()

    elif page == "Nạp Credits":

        topup_workspace(user)

    elif page == "Lịch sử giao dịch":

        history_workspace(user)

    elif page == "Lịch sử sản phẩm":

        creation_history_workspace()

    elif page == "Quản trị Admin" and admin_status:

        admin_workspace()


# =========================================================
# 17. CHẠY ỨNG DỤNG
# =========================================================

if __name__ == "__main__":

    try:

        main()

    except UnicodeEncodeError:

        st.error(
            "LỖI MÃ HÓA UNICODE/ASCII. "
            "Hãy kiểm tra lại Secrets và các thông tin kết nối."
        )

    except Exception as error:

        st.error(
            f"Ứng dụng gặp lỗi: {str(error)}"
        )
