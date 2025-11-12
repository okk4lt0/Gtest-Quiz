import os
import random
import streamlit as st
import google.generativeai as genai
from pypdf import PdfReader

# ---------------------------
# 基本設定
# ---------------------------
st.set_page_config(page_title="G検定クイズアプリ（Gemini版）", layout="wide")

PDF_PATH = "data/JDLA_Gtest_Syllabus_2024_v1.3_JP.pdf"

# 環境変数/Secrets のキー名（Gemini）
GEMINI_KEY = st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
if not GEMINI_KEY:
    st.error("Gemini APIキーが設定されていません（GEMINI_API_KEY）。")
    st.stop()
genai.configure(api_key=GEMINI_KEY)

# ---------------------------
# 共通ユーティリティ
# ---------------------------
def load_pdf_text(path: str) -> str:
    try:
        r = PdfReader(path)
        buf = []
        for p in r.pages:
            t = p.extract_text() or ""
            buf.append(t)
        return "\n".join(buf)
    except Exception as e:
        st.error(f"PDFの読み込みに失敗しました: {e}")
        return ""

def small_truncate(s: str, limit: int = 4000) -> str:
    # 入力トークンを抑えるため、長文を適度に切る
    if len(s) <= limit:
        return s
    return s[:limit]

# 429時の簡易オフライン問題（最低限の体験継続用）
OFFLINE_BANK = [
    {
        "q": "過学習（オーバーフィッティング）を抑えるための代表的な手法はどれ？",
        "choices": ["ドロップアウト", "学習率を無限大にする", "訓練データを減らす", "エポック数を必ず増やす"],
        "ans": "A",
        "exp": {
            "A": "ドロップアウトは汎化性能を高め、過学習の抑制に有効。",
            "B": "学習率を極端に大きくすると学習が不安定になる。",
            "C": "データを減らすと一般には過学習が悪化しやすい。",
            "D": "エポック数の増加は過学習を助長する場合がある。"
        }
    },
    {
        "q": "強化学習で、行動価値に基づき方策を改善していく代表的な手法は？",
        "choices": ["SARSA", "K-means", "主成分分析", "線形回帰"],
        "ans": "A",
        "exp": {
            "A": "SARSAはオンポリシーなTD学習法で、価値と方策の更新を同時に進める。",
            "B": "K-meansは教師なし学習のクラスタリング。",
            "C": "主成分分析は次元圧縮。",
            "D": "線形回帰は回帰分析。"
        }
    },
    {
        "q": "教師あり学習の説明として最も適切なのはどれ？",
        "choices": ["入力と正解ラベルを用いて学習する", "正解ラベルなしで構造を見つける", "報酬を最大化する行動を学習する", "テキスト生成のみを扱う学習法"],
        "ans": "A",
        "exp": {
            "A": "教師あり学習は入力と正解ラベルの組で学習する。",
            "B": "これは教師なし学習。",
            "C": "これは強化学習。",
            "D": "生成はタスクの一例で学習分類ではない。"
        }
    }
]

def render_offline_question():
    item = random.choice(OFFLINE_BANK)
    st.warning("Geminiの無料枠（クォータ）が 0 のため、オフライン問題を表示します。")
    st.subheader("出題（オフライン）")
    st.write(item["q"])
    picked = st.radio("選択肢を選んでください：", [f"A：{item['choices'][0]}",
                                              f"B：{item['choices'][1]}",
                                              f"C：{item['choices'][2]}",
                                              f"D：{item['choices'][3]}"], index=0)
    if st.button("回答する（オフライン）"):
        ans_letter = item["ans"]
        correct_text = {"A": item['choices'][0], "B": item['choices'][1],
                        "C": item['choices'][2], "D": item['choices'][3]}[ans_letter]
        st.success(f"正解：{ans_letter}（{correct_text}）")
        st.markdown("**解説**")
        for k in ["A","B","C","D"]:
            st.write(f"- {k}：{item['exp'][k]}")

# ---------------------------
# UI
# ---------------------------
st.sidebar.title("設定")
# モデル一覧を取得（generateContent対応のみ）。flash系を先頭に。
try:
    all_models = [m for m in genai.list_models() if "generateContent" in m.supported_generation_methods]
    # 名前だけ取り出し
    names = [m.name for m in all_models]
    # flash 系を優先（使用実績から無料枠が通る可能性が最も高い）
    preferred = [n for n in names if "flash" in n]
    others = [n for n in names if n not in preferred]
    model_options = preferred + others if preferred else names
except Exception as e:
    st.sidebar.error(f"モデル一覧の取得に失敗: {e}")
    model_options = ["gemini-2.0-flash"]

# デフォルトを gemini-2.0-flash に
default_index = 0
for i, n in enumerate(model_options):
    if "gemini-2.0-flash" in n:
        default_index = i
        break

model_name = st.sidebar.selectbox("使用モデルを選択", model_options, index=default_index)
st.sidebar.caption(f"選択モデル: `{model_name}`")

st.header("出題")

syllabus_text = load_pdf_text(PDF_PATH)
if not syllabus_text.strip():
    st.error("シラバスPDFの読み込みに失敗しています。`data/` 配置とファイル名を確認してください。")
    st.stop()

# ---------------------------
# 出題ボタン
# ---------------------------
if st.button("AIで問題を作る"):
    with st.spinner("問題を生成中..."):
        try:
            model = genai.GenerativeModel(model_name)
            prompt = (
                "以下のG検定シラバス本文のみを根拠に、4択の単一正解問題を1問作ってください。"
                "出題は日本語、曖昧表現を避け、ハルシネーションを防ぐため本文外の知識は用いないこと。"
                "出力フォーマット：\n"
                "【問題文】...\nA: ...\nB: ...\nC: ...\nD: ...\n"
                "【正解】A|B|C|D\n"
                "【解説】各選択肢について1〜2文で根拠を説明（本文にない情報は書かない）。\n\n"
                f"--- シラバス本文 ---\n{small_truncate(syllabus_text, 4000)}"
            )
            resp = model.generate_content(prompt)
            st.subheader("出題（AI）")
            st.write(resp.text.strip())
        except Exception as e:
            # 429（無料枠0）を含むエラーはここでフォールバック
            msg = str(e)
            if "429" in msg or "quota" in msg.lower() or "free_tier" in msg.lower():
                render_offline_question()
            else:
                st.error(f"生成に失敗しました: {e}")
else:
    st.info("「AIで問題を作る」を押すと、シラバスに基づく問題を生成します。無料枠が無い場合はオフライン問題に切り替わります。")
