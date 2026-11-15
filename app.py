import os
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# Lấy biến môi trường từ st.secrets (trên Streamlit Cloud) hoặc os.environ (.env)
def get_env(key, default=""):
    try:
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return os.getenv(key, default)

SUPABASE_URL = get_env("SUPABASE_URL")
SUPABASE_KEY = get_env("SUPABASE_KEY")
FAL_KEY = get_env("FAL_KEY")
ADMIN_EMAIL = get_env("ADMIN_EMAIL", "admin@bapaivideo.com")

# Thiết lập biến môi trường cho fal-client nếu có
if FAL_KEY:
    os.environ["FAL_KEY"] = FAL_KEY

# Chi phí Credits cho từng tính năng
COST_IMAGE_EDIT = 2   # FLUX Kontext
COST_VIDEO_GEN = 10   # Kling 3.0

# Thông tin tài khoản ngân hàng VietQR cố định của Ngô Văn Khánh
BANK_INFO = {
    "bank_code": "PVCB",
    "bank_bin": "970412",
    "bank_name": "PVcomBank",
    "account_number": "107004099152",
    "account_name_vi": "NGÔ VĂN KHÁNH",
    "account_name_ascii": "NGO VAN KHANH"
}

# Các gói nạp Credits
CREDIT_PACKAGES = [
    {
        "id": "starter",
        "name": "Gói Cơ Bản",
        "amount": 50000,
        "credits": 50,
        "badge": "TIẾT KIỆM",
        "description": "Phù hợp để trải nghiệm tạo ảnh và vài video ngắn quảng cáo sản phẩm."
    },
    {
        "id": "pro",
        "name": "Gói Pro",
        "amount": 199000,
        "credits": 250,
        "badge": "PHỔ BIẾN NHẤT",
        "description": "Lựa chọn tốt nhất cho các nhà sáng tạo nội dung và nhà bán hàng TikTok."
    },
    {
        "id": "studio",
        "name": "Gói Studio",
        "amount": 499000,
        "credits": 700,
        "badge": "SIÊU ƯU ĐÃI",
        "description": "Dành cho agency chuyên nghiệp sản xuất số lượng lớn video mỗi ngày."
    }
]

# Danh sách giọng đọc tiếng Việt qua Edge-TTS
VIETNAMESE_VOICES = {
    "Nữ Miền Nam (Hoài My - Mượt mà, tự nhiên)": "vi-VN-HoaiMyNeural",
    "Nam Miền Bắc (Nam Minh - Truyền cảm, uy tín)": "vi-VN-NamMinhNeural"
}

def build_transfer_content(user_id: str, tx_id: str) -> str:
    """Tạo nội dung chuyển khoản chuẩn: BAPAI <4_ký_tự_đầu_user> <4_số_đầu_tx>"""
    u_short = user_id.replace("-", "")[:4].upper()
    t_short = tx_id.replace("-", "")[:4].upper()
    return f"BAPAI {u_short} {t_short}"

def build_vietqr_url(amount: int, add_info: str) -> str:
    """Tạo URL ảnh VietQR động theo đúng thông tin tài khoản PVcomBank"""
    bank = BANK_INFO["bank_code"]
    stk = BANK_INFO["account_number"]
    name = BANK_INFO["account_name_ascii"].replace(" ", "%20")
    return f"https://img.vietqr.io/image/{bank}-{stk}-compact2.png?amount={amount}&addInfo={add_info}&accountName={name}"
