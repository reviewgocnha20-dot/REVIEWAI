# -*- coding: utf-8 -*-
# REVIEWAI - Công cụ tạo video review sản phẩm
# Phiên bản đã chỉnh sửa: hỗ trợ chạy lại và thời lượng 10/20/30/40s

import time
import uuid
from datetime import datetime

import streamlit as st

st.set_page_config(page_title="REVIEWAI", page_icon="🎬", layout="wide")

DURATIONS = [10, 20, 30, 40]
ASPECT_RATIOS = ["9:16", "16:9", "1:1"]
REVIEW_STYLES = ["Trong bếp", "Phòng khách", "Vlog", "Cầm tay cận cảnh"]

STAGES = [
    "Đang phân tích sản phẩm",
    "Đang viết kịch bản",
    "Đang tạo giọng đọc",
    "Đang tạo nhân vật",
    "Đang tạo cảnh",
    "Đang đồng bộ khẩu hình",
    "Đang ghép video",
    "Đang kiểm tra chất lượng",
    "Đang lưu video",
]

# ---------- Trạng thái phiên ----------
if "history" not in st.session_state:
    st.session_state.history = []
if "last_config" not in st.session_state:
    st.session_state.last_config = None


def generate_video(config: dict, on_stage):
    """
    TODO: Thay phần này bằng code gọi API thật (LLM, TTS, video, lipsync...).
    Hàm cần trả về dict chứa kết quả, ví dụ {"video_url": "..."}.
    Hiện tại chỉ chạy mô phỏng từng công đoạn.
    """
    for i, stage in enumerate(STAGES, start=1):
        on_stage(stage, i / len(STAGES))
        time.sleep(0.4)
    return {"video_url": None}


def run_job(config: dict):
    progress = st.progress(0.0)
    status = st.empty()

    def on_stage(label, ratio):
        status.info(label)
        progress.progress(ratio)

    try:
        result = generate_video(config, on_stage)
        status.success("Hoàn thành")
        st.session_state.history.insert(
            0,
            {
                "id": str(uuid.uuid4())[:8],
                "time": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                "config": config,
                "result": result,
            },
        )
    except Exception as e:
        status.error(f"Thất bại: {e}")


# ---------- Giao diện ----------
st.title("🎬 REVIEWAI")
st.caption("Tạo video review sản phẩm bằng AI")

left, right = st.columns([1, 1])

with left:
    st.subheader("Thông tin sản phẩm")
    product_name = st.text_input("Tên sản phẩm")
    product_url = st.text_input("Link sản phẩm (tuỳ chọn)")
    product_image = st.file_uploader(
        "Ảnh sản phẩm", type=["png", "jpg", "jpeg", "webp"]
    )
    if product_image:
        st.image(product_image, width=240)

with right:
    st.subheader("Cấu hình video")
    duration = st.selectbox(
        "Thời lượng (giây)", DURATIONS, index=1, format_func=lambda x: f"{x}s"
    )
    aspect = st.selectbox("Tỉ lệ khung hình", ASPECT_RATIOS)
    style = st.selectbox("Phong cách review", REVIEW_STYLES)

col_a, col_b = st.columns(2)

with col_a:
    if st.button("🚀 Tạo video", type="primary", use_container_width=True):
        if not product_name.strip():
            st.warning("Vui lòng nhập tên sản phẩm.")
        elif product_image is None:
            st.warning("Vui lòng tải ảnh sản phẩm.")
        else:
            config = {
                "product_name": product_name.strip(),
                "product_url": product_url.strip(),
                "product_image_name": product_image.name,
                "duration_sec": duration,
                "aspect_ratio": aspect,
                "review_style": style,
            }
            st.session_state.last_config = config
            run_job(config)

with col_b:
    can_rerun = st.session_state.last_config is not None
    if st.button(
        "🔁 Chạy lại với cấu hình trước",
        use_container_width=True,
        disabled=not can_rerun,
    ):
        run_job(st.session_state.last_config)

# ---------- Lịch sử ----------
st.divider()
st.subheader("Video đã tạo")

if not st.session_state.history:
    st.write("Chưa có video nào.")
else:
    for item in st.session_state.history:
        cfg = item["config"]
        with st.expander(
            f"{cfg['product_name']} - {cfg['duration_sec']}s - {item['time']}"
        ):
            st.json(cfg)
            if item["result"].get("video_url"):
                st.video(item["result"]["video_url"])
            else:
                st.caption("Chưa kết nối API tạo video thật (đang chạy mô phỏng).")
