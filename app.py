
import asyncio
import concurrent.futures
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import base64
from io import BytesIO
from typing import Optional

import streamlit as st

# CẤU HÌNH STREAMLIT PHẢI ĐẶT TRƯỚC CÁC LỆNH GIAO DIỆN
st.set_page_config(
    page_title="BẮP AI VIDEO - TikTok Shop Edition",
    page_icon="🎬",
    layout="centered",
)

# TỰ CÀI THƯ VIỆN CÒN THIẾU
_PACKAGES = {
    "edge_tts": "edge-tts",
    "imageio_ffmpeg": "imageio-ffmpeg",
    "PIL": "Pillow",
    "google": "google-genai",
    "requests": "requests",
    "fal_client": "fal-client",
}

_missing = [
    package
    for module, package in _PACKAGES.items()
    if importlib.util.find_spec(module) is None
]

if _missing:
    with st.spinner("Đang cài thư viện cần thiết..."):
        try:
            subprocess.check_call([
                sys.executable,
                "-m",
                "pip",
                "install",
                "--quiet",
                *_missing
            ])
        except Exception as install_error:
            st.error(f"Không thể cài thư viện: {install_error}")
            st.stop()

try:
    import edge_tts
    import imageio_ffmpeg
    import requests
    import fal_client

    from google import genai
    from google.genai import types
    from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

except Exception as import_error:
    st.error(f"Lỗi nạp thư viện: {import_error}")
    st.stop()

# ---------------------------------------------------------
# CẤU HÌNH ẢNH NỀN
# ---------------------------------------------------------

# Không sử dụng chuỗi Base64 bị cắt dở.
# Cần bổ sung ảnh nền hợp lệ để khôi phục hình nền bản đồ Việt Nam.
BACKGROUND_IMAGE_B64 = ""

def load_background_image():
    if not BACKGROUND_IMAGE_B64:
        return None

    try:
        image_data = base64.b64decode(
            BACKGROUND_IMAGE_B64,
            validate=True
        )
        image = Image.open(BytesIO(image_data))
        image.load()
        return image.convert("RGB")

    except Exception as error:
        st.warning(f"Không thể tải ảnh nền: {error}")
        return None
