import streamlit as st
import google.generativeai as genai
import os
from pypdf import PdfReader

# ========== 設定 ==========
st.set_page_config(page_title="G検定クイズアプリ（Gemini版）", layout="wide")

# Google Gemini APIキー
api_key = st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
if not api_key:
    st.error("Gemini APIキーが設定されていません。")
    st.stop()
genai.configure(api_key=api_key)

# ========== サイドバー ==========
st.sidebar.title("G検定クイズアプリ（Gemini版）")

# モデル一覧を取得して選択肢に表示
try:
    models = [m.name for m in genai.list_models() if "generateContent" in m.supported_generation_methods]
except Exception as e:
    st.sidebar.error(f"モデル一覧の取得に失敗しました: {e}")
    models = ["gemini-2.0-flash"]

model_name = st.sidebar.selectbox("使用モデルを選択", models, index=0)
st.sidebar.write(f"使用モデル: `{model_name}`")

# ========== PDF読み込み ==========
PDF_PATH = "data/JDLA_Gtest_Syllabus_2024_v1.3_JP.pdf"

def load_pdf_text(pdf_path):
    """PDFからテキストを抽出"""
    text = ""
    try:
        reader = PdfReader(pdf_path)
        for page in reader.pages:
            text += page.extract_text() or ""
        return text
    except Exception as e:
        st.error(f"PDFの読み込みに失敗しました: {e}")
        return ""

syllabus_text = load_pdf_text(PDF_PATH)

# ========== メイン表示 ==========
st.header("出題")

if not syllabus_text.strip():
    st.error("シラバスの内容を読み込めませんでした。PDFを確認してください。")
    st.stop()

if st.button("AIで問題を作る"):
    with st.spinner("問題を生成中..."):
        prompt = (
            "以下のG検定シラバスの内容に基づいて、"
            "選択式のクイズ問題を1問生成してください。"
            "フォーマットは以下に従ってください。\n\n"
            "【問題文】...\nA: ...\nB: ...\nC: ...\nD: ...\n"
            "正解はA〜Dのいずれか1つにしてください。\n\n"
            f"シラバス内容:\n{syllabus_text[:8000]}"  # Gemini入力制限対策
        )

        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            quiz_text = response.text.strip()
            st.markdown("### 出題")
            st.write(quiz_text)
        except Exception as e:
            st.error(f"生成に失敗しました: {e}")
else:
    st.info("「AIで問題を作る」を押すと、シラバス内容に基づく問題が1問生成されます。")
