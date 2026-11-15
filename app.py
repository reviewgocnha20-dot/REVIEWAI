
def show_brand_header():
    image_path = os.path.join(
        os.path.dirname(__file__),
        "hoang_sa_truong_sa_background.jpg"
    )

    if not os.path.exists(image_path):
        st.warning("Chưa tìm thấy ảnh nền bản đồ.")
        return

    with open(image_path, "rb") as f:
        image_data = base64.b64encode(f.read()).decode()

    st.markdown(f"""
    <style>
    .stApp {{
        background:
        linear-gradient(
            rgba(10, 0, 0, 0.30),
            rgba(10, 0, 0, 0.65)
        ),
        url("data:image/jpeg;base64,{image_data}");

        background-size: cover;
        background-position: center top;
        background-attachment: fixed;
    }}

    .map-hero {{
        width: 100%;
        padding: 25px 15px 20px;
        text-align: center;
        border-radius: 18px;
        background: rgba(15, 0, 0, 0.65);
        border: 1px solid rgba(220, 160, 55, 0.5);
        margin-bottom: 25px;
    }}

    .map-icon {{
        font-size: 48px;
        margin-bottom: 8px;
    }}

    .map-title {{
        color: #FFD36A;
        font-size: clamp(23px, 5vw, 38px);
        font-weight: 900;
        text-shadow: 0 0 15px #A64B00;
        margin: 0;
    }}

    .map-subtitle {{
        color: #FFFFFF;
        font-size: 18px;
        font-weight: bold;
        margin-top: 12px;
    }}

    .map-flag {{
        font-size: 30px;
        margin-top: 8px;
    }}
    </style>

    <div class="map-hero">
        <div class="map-icon">🗺️</div>
        <div class="map-title">
            HOÀNG SA – TRƯỜNG SA
        </div>
        <div class="map-subtitle">
            LÀ CỦA VIỆT NAM
        </div>
        <div class="map-flag">🇻🇳</div>
    </div>
    """, unsafe_allow_html=True)
