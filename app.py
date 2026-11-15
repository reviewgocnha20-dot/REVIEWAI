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
from typing import Optional

import streamlit as st

# Tự cài thư viện còn thiếu để Bắp chỉ cần thay MỘT file app.py.
# Streamlit đã được cài sẵn trên Streamlit Cloud nên không cài lại.
_PACKAGES = {
    "edge_tts": "edge-tts",
    "imageio_ffmpeg": "imageio-ffmpeg",
    "PIL": "Pillow",
    "google": "google-genai",
    "requests": "requests",
    "fal_client": "fal-client",
}
_missing = [
    package for module, package in _PACKAGES.items()
    if importlib.util.find_spec(module) is None
]
if _missing:
    with st.spinner("Đang tự cài thư viện cần thiết lần đầu..."):
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "--quiet", *_missing]
            )
        except Exception as install_error:
            st.error(
                "Không thể tự cài thư viện: "
                + ", ".join(_missing)
                + f". Chi tiết: {install_error}"
            )
            st.stop()

try:
    import edge_tts
    import imageio_ffmpeg
    from google import genai
    from google.genai import types
    from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps
except Exception as import_error:
    st.error(f"Không nạp được thư viện sau khi cài: {import_error}")
    st.stop()

# ---------------------------------------------------------
# CẤU HÌNH
# ---------------------------------------------------------
st.set_page_config(
    page_title="BẮP AI VIDEO - TikTok Shop Edition",
    page_icon="🎬",
    layout="centered",
)

# ---------------------------------------------------------
# GIAO DIỆN NỀN BẢN ĐỒ VIỆT NAM
# Ảnh nền được nhúng trực tiếp trong app.py để chỉ cần một file code.
# ---------------------------------------------------------
BACKGROUND_IMAGE_B64 = "/9j/4AAQSkZJRgABAQAASABIAAD/4QCARXhpZgAATU0AKgAAAAgABQESAAMAAAABAAEAAAEaAAUAAAABAAAASgEbAAUAAAABAAAAUgEoAAMAAAABAAIAAIdpAAQAAAABAAAAWgAAAAAAAABIAAAAAQAAAEgAAAABAAKgAgAEAAAAAQAAAsKgAwAEAAAAAQAABgAAAAAA/+0AOFBob3Rvc2hvcCAzLjAAOEJJTQQEAAAAAAAAOEJJTQQlAAAAAAAQ1B2M2Y8AsgTpgAmY7PhCfv/iAihJQ0NfUFJPRklMRQABAQAAAhhhcHBsBAAAAG1udHJSR0IgWFlaIAfmAAEAAQAAAAAAAGFjc3BBUFBMAAAAAEFQUEwAAAAAAAAAAAAAAAAAAAAAAAD21gABAAAAANMtYXBwbAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACmRlc2MAAAD8AAAAMGNwcnQAAAEsAAAAUHd0cHQAAAF8AAAAFHJYWVoAAAGQAAAAFGdYWVoAAAGkAAAAFGJYWVoAAAG4AAAAFHJUUkMAAAHMAAAAIGNoYWQAAAHsAAAALGJUUkMAAAHMAAAAIGdUUkMAAAHMAAAAIG1sdWMAAAAAAAAAAQAAAAxlblVTAAAAFAAAABwARABpAHMAcABsAGEAeQAgAFAAM21sdWMAAAAAAAAAAQAAAAxlblVTAAAANAAAABwAQwBvAHAAeQByAGkAZwBoAHQAIABBAHAAcABsAGUAIABJAG4AYwAuACwAIAAyADAAMgAyWFlaIAAAAAAAAPbVAAEAAAAA0yxYWVogAAAAAAAAg98AAD2/////u1hZWiAAAAAAAABKvwAAsTcAAAq5WFlaIAAAAAAAACg4AAARCwAAyLlwYXJhAAAAAAADAAAAAmZmAADypwAADVkAABPQAAAKW3NmMzIAAAAAAAEMQgAABd7///MmAAAHkwAA/ZD///ui///9owAAA9wAAMBu/8AAEQgGAALCAwEiAAIRAQMRAf/EAB8AAAEFAQEBAQEBAAAAAAAAAAABAgMEBQYHCAkKC//EALUQAAIBAwMCBAMFBQQEAAABfQECAwAEEQUSITFBBhNRYQcicRQygZGhCCNCscEVUtHwJDNicoIJChYXGBkaJSYnKCkqNDU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6g4SFhoeIiYqSk5SVlpeYmZqio6Slpqeoqaqys7S1tre4ubrCw8TFxsfIycrS09TV1tfY2drh4uPk5ebn6Onq8fLz9PX29/j5+v/EAB8BAAMBAQEBAQEBAQEAAAAAAAABAgMEBQYHCAkKC//EALURAAIBAgQEAwQHBQQEAAECdwABAgMRBAUhMQYSQVEHYXETIjKBCBRCkaGxwQkjM1LwFWJy0QoWJDThJfEXGBkaJicoKSo1Njc4OTpDREVGR0hJSlNUVVZXWFlaY2RlZmdoaWpzdHV2d3h5eoKDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uLj5OXm5+jp6vLz9PX29/j5+v/bAEMAAQEBAQEBAgEBAgMCAgIDBAMDAwMEBQQEBAQEBQYFBQUFBQUGBgYGBgYGBgcHBwcHBwgICAgICQkJCQkJCQkJCf/bAEMBAQEBAgICBAICBAkGBQYJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCJCQkJCf/dAAQALf/aAAwDAQACEQMRAD8A/wA/+iiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKAP//Q/wA/+iiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKAP//R/wA/+iiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKAP//S/wA/+iiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKAP//T/wA/+iiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKAP//U/wA/+iiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKAP//V/wA/+iiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKAP//W/wA/+iiigAooooAKKK19E0DW/EmoJpWgWst5cSfdjiUs3146D3PFAGRRX1N4e/Zd1eZBN431m00cHkwoDdTj2KxkID9Xr1Cz/Zx+BtuAupaxrN0ccmFLeEE+wfzDQB8E0V933/7NvwZukYaRruq2b/wm4hhnX8fLaM/pXkniX9mPxfp6Nc+D7221+JedsBMVxj/rjJgn6KWoA+a6KtXtleabdPY6hE8E0R2vHIpVlPoQeRVWgAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACor23wf8APiD4sgj1G4ij0mxkwRcXzeUGHqqYMjfguPevctK/Zk+GlrGD4j8S3d1J3WytlRffDSuSf++RQB8QUV9/T/ALO3wDeMLbalrsb92f7M4/75CKf1rg9d/Zc0mVWfwT4minb+GG/ha3Y+3mKZEz9cCgD49ortvGPw68Z+ArgQ+KLF7dk+5KMPE/8AySKSp/A5riaACiiigAooooAKKKKAP//X/wA/+iiigAoorpPCXhu68Wa9BolqdvmHLueiIOWY/QfrxQB1fw4+Gl745umu7qQ2mmW7AT3BGST12Rj+Jz+Q6n3+xNJOmeF9M/sPwjbiwtf4yv8ArZT/AHpZOrfToOwrIgisdNsING0pPKtLVdsafzZvVmPJNL5i/wCf/wBVAGq143QHFRfam9azS5PSmUAa32tvU1Kl7ICHUkEdxWKDjkU4Oe9AFzxRpXh/x/ZCw8YRb5VG2G8Qf6RF6ZP8a/7LZ9sGvirxt4I1fwNq39najiSJxugnT/Vyp/eX39QeQa+zPMHbNZuvaLY+LtEl8N6lgK/zQSHrFL2Yex6MO4oA+E6Ku6jp93pN/Npl8myaByjqexU4NUqACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoor0H4T/DzVfi18TdB+GeiHbda7fQWSMeiea4UufZQSx9hUzmoxcpbI0o0pVJqEFdvRHqn7Pf7JHx1/ab1L7J8KtDrby2WVal8zytL2MJvVWy3IJHRRyxUc19han/wAEsviJ4S8VSfD74i317oWvxIrtaz6d/C/KOMzgtG/VWAww5Ffq5/wTs/aO+Ev7Nf7adl8GvEt9PpfwjN7Bp5G6IWou4AYUvr1pBuSOQljI8bAglS25Qa9o+JH7RH7R/wAcP2xNS8NftQ3p07W9IvJtL0vS4IEjtLFlc/ZreFUB3RSZVhMWcuCGDEMK/nTiXxEzuOYVaWHUYUYxTi93K763VtLO6Xlrqf3P4ReB3Dk68aOf0nUXK5TlzSjy/wCBQ1aXVvbfyP5sPj/+wl8ff2fPD7+Otd0/+1PDMcixSarYh3it3kOES5RlV4C54UuuxjwrE8V8Z1/B3upJGTgjpX7of8ABNn9hvwt7T+E39p18Jftg/sE/H39kfW7q68WeG9TfwhdXEi2HiiPS7hdEuQzb4IjfENb+eV2h/LmlDFgVLK0Zf9O1oD+caiv0v8A2Xf+CRf7W/7Xvwj1D46+APDWp2PhS2sppNE1K4sZZE128iQssVhGp3vE5Uos7bUBbdsZFZq7f8AYz/4Iu/tSftafDeH47XthN4N8Gy2s0lpfanYztcaq8QbeLNPl8pE2MrSS8FoyqLJzQB+YVFfqp4X/4ItftneLf2kJ/2YLDwtdjUbS2S/uNSnt5YNLttPYkfbJLthjysqwVI/MMm1tgIBx0n7bP/BC39oz9kvwJqPxG8OWj67pGlRzy6jFf2k9re2dvb533Mh+aKSFUGX+bKhWJGFNAH5EUUUV+pHwc/wCCCX7avxx/Z4sP2hvB3gy/fUtV3y2Ph6S2khluLWPA85rlv3Ks7MyxRAhiU3NtVgaAPzXor2r45/s8fF79nnx1deBPit4W1HQLu2uJbZftVrLFFJJEdrmJ2G2RCeAwJBrv8A4bfscftK/FrwbefELwL4L1G80jTppLW4vBaSrCs8Yy0UchG15AOdkZLYBOKAPlqivp/wCHH7HH7SHxV8bS+BfCXgjWri/hMnnO2nzrBGsX3y8jKEAXow3Zz0zXUfG3/gnb+2v8APh6vxJ8bfD/WbXQY5JI7q7fT5/IsjE21vtTbf3O0jB37cfNnrQB8q0V+i/wv8A+CEX7bfxS+Bln+0D4f8ABV+t1qjOuiaJLaSw3F/BF8v2jzm/dJ5rD90pILKyu21eTXwP44+FPj/4b+NJvA/jfSrrTNUspDFPZzwyRTIy9cpIN2D1BxzQBw9FfZvjX/AIJm/tqfD/4br8V9b8A6udEMAnuJU0+d5bWEtv8ANSIDdKix/vGKKdqliMDmuE+Av7GH7Sn7TvhrxN4s+D3hK+1jS/Cls93qN3BaSzrGkalnjXYNrygKx2KdwVS2MDJAPlagrX2l/s0fsgfF39qTxlp/gfwTo19dS3c5t57uOyma
