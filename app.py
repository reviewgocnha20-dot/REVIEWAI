import streamlit as st
from PIL import Image, ImageOps
from io import BytesIO
import re

# -------------------------------------------------
# CẤU HÌNH
# -------------------------------------------------
st.set_page_config(
    page_title="BẮP AI VIDEO - TikTok Shop Edition",
    page_icon="🎬",
    layout="centered",
)

if "duration" not in st.session_state:
    st.session_state.duration = "20 giây"
if "jobs" not in st.session_state:
    st.session_state.jobs = []

# -------------------------------------------------
# GIAO DIỆN
# -------------------------------------------------
st.markdown("""
<style>
.stApp {background:#f1f5f9;color:#0f172a}
.block-container {max-width:760px;padding-top:1.2rem;padding-bottom:2rem}
.header-card {
 background:linear-gradient(135deg,#162033 0%,#0f172a 100%);
 padding:22px 20px;border-radius:20px;margin-bottom:22px;
 box-shadow:0 8px 20px rgba(15,23,42,.15)
}
.section-label {
 color:#475569;font-weight:700;font-size:12px;letter-spacing:.5px;
 margin:16px 0 8px 0
}
.stTextArea textarea,.stTextInput input {
 background:#fff!important;color:#0f172a!important;
 border-radius:14px!important;border:1px solid #e2e8f0!important
}
div[data-testid="column"] button {
 width:100%;border-radius:12px!important;font-weight:600!important
}
.avatar-box {
 background:#fff;border-radius:16px;padding:12px;
 border:1px solid #e2e8f0;text-align:center
}
div.stButton>button[kind="primary"] {
 background:linear-gradient(135deg,#2563eb,#1d4ed8);
 color:white;border:0;border-radius:15px;font-weight:700;
 min-height:48px
}
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="header-card">
 <div style="display:flex;justify-content:space-between;align-items:center">
  <div>
   <h3 style="margin:0;color:white;font-size:22px;font-weight:800">BẮP AI VIDEO</h3>
   <p style="margin:2px 0 10px;color:#94a3b8;font-size:12px;font-weight:600">TIKTOK SHOP EDITION</p>
  </div>
  <div style="font-size:28px">🎬</div>
 </div>
 <span style="background:#064e3b;color:#34d399;padding:4px 10px;border-radius:8px;font-size:11px;font-weight:700">
  FREE-FIRST SYSTEM
 </span>
 <h2 style="margin:14px 0 6px;color:white;font-size:18px">Từ link sản phẩm đến video quảng cáo</h2>
 <p style="margin:0;color:#cbd5e1;font-size:12px;line-height:1.5">
  Quản lý link sản phẩm · Chọn nhân vật · Chuẩn bị nội dung video 9:16
 </p>
</div>
""", unsafe_allow_html=True)

st.subheader("Giao diện thao tác trên iPhone")

# -------------------------------------------------
# NHẬP LINK SẢN PHẨM
# -------------------------------------------------
st.markdown('<div class="section-label">LINK SẢN PHẨM TIKTOK SHOP — MỖI DÒNG MỘT LINK</div>', unsafe_allow_html=True)
product_links = st.text_area(
    "Danh sách link sản phẩm",
    placeholder="Dán link sản phẩm thứ nhất...\nDán link sản phẩm thứ hai...",
    height=110,
    label_visibility="collapsed",
    key="product_links",
)

links = []
for line in product_links.splitlines():
    candidate = line.strip()
    if candidate and candidate not in links:
        links.append(candidate)

st.caption(f"Đã nhập {len(links)} link không trùng.")

# -------------------------------------------------
# THỜI LƯỢNG
# -------------------------------------------------
st.markdown('<div class="section-label">THỜI LƯỢNG VIDEO</div>', unsafe_allow_html=True)
durations = ["10 giây", "20 giây", "30 giây", "40 giây"]
duration_cols = st.columns(4)
for i, duration in enumerate(durations):
    with duration_cols[i]:
        if st.button(
            duration,
            key=f"duration_{i}",
            type="primary" if st.session_state.duration == duration else "secondary",
            use_container_width=True,
        ):
            st.session_state.duration = duration
            st.rerun()

# -------------------------------------------------
# NHÂN VẬT — RADIO ĐỂ CHỈ CHỌN MỘT
# -------------------------------------------------
st.markdown('<div class="section-label">NHÂN VẬT REVIEWER</div>', unsafe_allow_html=True)
c1, c2 = st.columns(2)
with c1:
    st.markdown("""
    <div class="avatar-box">
      <div style="font-size:42px">👩🏻</div>
      <b style="color:#1e293b">Nữ Reviewer</b>
      <div style="font-size:11px;color:#64748b">Giọng nữ tiếng Việt</div>
    </div>
    """, unsafe_allow_html=True)
with c2:
    st.markdown("""
    <div class="avatar-box">
      <div style="font-size:42px">👨🏻</div>
      <b style="color:#1e293b">Nam Reviewer</b>
      <div style="font-size:11px;color:#64748b">Giọng nam tiếng Việt</div>
    </div>
    """, unsafe_allow_html=True)

reviewer = st.radio(
    "Chọn một nhân vật",
    ["Nữ Reviewer", "Nam Reviewer"],
    horizontal=True,
    label_visibility="collapsed",
    key="reviewer",
)

# -------------------------------------------------
# TẢI ẢNH
# -------------------------------------------------
with st.expander("➕ Tải ảnh sản phẩm hoặc ảnh nhân vật (tùy chọn)", expanded=False):
    uploaded_file = st.file_uploader(
        "Chọn ảnh JPG, JPEG hoặc PNG",
        type=["jpg", "jpeg", "png"],
        key="uploaded_image",
    )
    if uploaded_file is not None:
        try:
            image = Image.open(uploaded_file)
            image = ImageOps.exif_transpose(image).convert("RGB")
            st.image(image, caption="Ảnh đã tải lên", use_container_width=True)
        except Exception:
            st.error("Không đọc được ảnh. Vui lòng chọn file JPG hoặc PNG khác.")

# -------------------------------------------------
# GHI CHÚ SẢN PHẨM
# -------------------------------------------------
st.markdown('<div class="section-label">MÔ TẢ SẢN PHẨM (TÙY CHỌN)</div>', unsafe_allow_html=True)
product_note = st.text_area(
    "Mô tả sản phẩm",
    placeholder="Ví dụ: tên sản phẩm, màu sắc, chất liệu, công dụng, điểm nổi bật...",
    height=90,
    label_visibility="collapsed",
    key="product_note",
)

# -------------------------------------------------
# XỬ LÝ YÊU CẦU — KHÔNG GIẢ VỜ TẠO VIDEO
# -------------------------------------------------
st.markdown("")
if st.button("🚀 KIỂM TRA & CHUẨN BỊ DANH SÁCH VIDEO", type="primary", use_container_width=True):
    if not links:
        st.error("Bạn chưa nhập link sản phẩm. Hãy dán ít nhất một link.")
    elif len(links) > 20:
        st.error("Mỗi lượt hiện hỗ trợ tối đa 20 link để tránh quá tải.")
    else:
        invalid = [u for u in links if not re.match(r"^https?://", u, flags=re.I)]
        if invalid:
            st.error("Có link không đúng định dạng. Link cần bắt đầu bằng http:// hoặc https://.")
            for bad in invalid:
                st.write(f"• {bad}")
        else:
            st.session_state.jobs = [
                {
                    "link": link,
                    "duration": st.session_state.duration,
                    "reviewer": reviewer,
                    "note": product_note.strip(),
                    "status": "Đã nhận link — chờ kết nối bộ xử lý video",
                }
                for link in links
            ]
            st.success(f"Đã kiểm tra hợp lệ {len(links)} link.")
            st.info(
                "Đây mới là bước kiểm tra và chuẩn bị danh sách. "
                "Bản code giao diện này chưa tải được dữ liệu/ảnh trực tiếp từ TikTok Shop "
                "và chưa kết xuất MP4. Cần tích hợp bộ lấy dữ liệu sản phẩm, tạo kịch bản, "
                "giọng đọc và FFmpeg trước khi có thể tạo video thật."
            )

# -------------------------------------------------
# DANH SÁCH ĐÃ NHẬN
# -------------------------------------------------
if st.session_state.jobs:
    st.markdown('<div class="section-label">DANH SÁCH SẢN PHẨM ĐÃ NHẬN</div>', unsafe_allow_html=True)
    for index, job in enumerate(st.session_state.jobs, start=1):
        with st.container(border=True):
            st.markdown(f"**Sản phẩm {index}**")
            st.write(job["link"])
            st.caption(
                f'{job["duration"]} · {job["reviewer"]} · {job["status"]}'
            )

st.caption("BẮP AI VIDEO · Giao diện thử nghiệm. Không nhập API key hoặc mật khẩu TikTok vào ô link.")
