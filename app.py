import os
import random
import streamlit as st
import google.generativeai as genai
from pypdf import PdfReader

# ======================
# 基本設定
# ======================
st.set_page_config(page_title="G検定クイズアプリ（Gemini版）", layout="wide")

PDF_PATH = "data/JDLA_Gtest_Syllabus_2024_v1.3_JP.pdf"

# Gemini APIキー
GEMINI_KEY = st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
if not GEMINI_KEY:
    st.error("Gemini APIキー（GEMINI_API_KEY）が見つかりません。Streamlit Secrets か環境変数に設定してください。")
    st.stop()
genai.configure(api_key=GEMINI_KEY)

# ======================
# ユーティリティ
# ======================
def load_pdf_text(path: str) -> str:
    try:
        r = PdfReader(path)
        texts = []
        for p in r.pages:
            t = p.extract_text() or ""
            texts.append(t)
        return "\n".join(texts)
    except Exception as e:
        st.error(f"PDFの読み込みに失敗しました: {e}")
        return ""

def small_truncate(s: str, limit: int = 4000) -> str:
    return s if len(s) <= limit else s[:limit]

OFFLINE_BANK = [
    {
        "q": "教師あり学習の説明として最も適切なのはどれ？",
        "choices": ["入力と正解ラベルを用いて学習する", "正解ラベルなしで構造を見つける", "報酬最大化の行動を学習する", "テキスト生成のみを扱う学習法"],
        "ans": "A",
        "exp": {
            "A": "教師あり学習は入力と正解ラベルの組で学習する。",
            "B": "これは教師なし学習の説明。",
            "C": "これは強化学習の説明。",
            "D": "学習法の分類ではない。"
        }
    },
    {
        "q": "過学習（オーバーフィッティング）を抑える代表的な手法は？",
        "choices": ["ドロップアウト", "学習率を無限大にする", "訓練データを必ず減らす", "エポック数を必ず増やす"],
        "ans": "A",
        "exp": {
            "A": "ドロップアウトは汎化性能を高め、過学習の抑制に有効。",
            "B": "過大な学習率は不安定化する。",
            "C": "一般にデータを減らすと過学習は悪化しやすい。",
            "D": "エポック増は過学習を助長する場合がある。"
        }
    },
    {
        "q": "強化学習でオンポリシーTD法の代表例はどれ？",
        "choices": ["SARSA", "K-means", "主成分分析", "線形回帰"],
        "ans": "A",
        "exp": {
            "A": "SARSAはオンポリシーなTD学習法。",
            "B": "K-meansは教師なしのクラスタリング。",
            "C": "主成分分析は次元圧縮。",
            "D": "線形回帰は回帰分析。"
        }
    }
]

def make_offline_question():
    item = random.choice(OFFLINE_BANK)
    return {
        "question": item["q"],
        "choices": item["choices"],
        "correct": item["ans"],   # "A" / "B" / "C" / "D"
        "explain": item["exp"]
    }

def set_question_to_state(payload):
    st.session_state.question = payload["question"]
    st.session_state.choices = payload["choices"]
    st.session_state.correct = payload["correct"]
    st.session_state.explain = payload["explain"]
    st.session_state.picked = None
    st.session_state.phase = "question"  # idle -> question -> answered

def reset_state():
    for k in ["question", "choices", "correct", "explain", "picked", "phase"]:
        st.session_state.pop(k, None)
    st.session_state.phase = "idle"

# 初期化
if "phase" not in st.session_state:
    st.session_state.phase = "idle"

# ======================
# モデル選択（flash系を優先）
# ======================
try:
    all_models = [m for m in genai.list_models() if "generateContent" in m.supported_generation_methods]
    names = [m.name for m in all_models]
    preferred = [n for n in names if "flash" in n]
    others = [n for n in names if n not in preferred]
    model_options = preferred + others if preferred else names
except Exception as e:
    st.sidebar.error(f"モデル一覧の取得失敗: {e}")
    model_options = ["gemini-2.0-flash"]

default_idx = 0
for i, n in enumerate(model_options):
    if "gemini-2.0-flash" in n:
        default_idx = i
        break

model_name = st.sidebar.selectbox("使用モデルを選択", model_options, index=default_idx)
st.sidebar.caption(f"選択モデル: `{model_name}`")

# ======================
# PDFロード
# ======================
syllabus_text = load_pdf_text(PDF_PATH)
if not syllabus_text.strip():
    st.error("シラバスPDFを読み込めません。`data/` 配置とファイル名を確認してください。")
    st.stop()

# ======================
# 画面：出題ヘッダ
# ======================
st.header("出題")

# 説明（初回）
if st.session_state.phase == "idle":
    st.info("「AIで問題を作る」を押すと、シラバスに基づく問題を生成します。無料枠がない場合はオフライン問題に切り替わります。")

# ======================
# 1) 出題ボタン（idle の時だけ有効）
# ======================
gen_btn = st.button("AIで問題を作る", disabled=(st.session_state.phase != "idle"))

if gen_btn and st.session_state.phase == "idle":
    # まずAIで生成を試みる
    try:
        model = genai.GenerativeModel(model_name)
        prompt = (
            "以下のG検定シラバス本文のみを根拠に、4択の単一正解問題を1問作成してください。"
            "出力は次の厳密フォーマットで返してください：\n"
            "【問題文】...\n"
            "A: ...\nB: ...\nC: ...\nD: ...\n"
            "【正解】A|B|C|D\n"
            "【解説】\nA: ...\nB: ...\nC: ...\nD: ...\n"
            "本文外の知識は使わないこと。曖昧表現は避けること。\n\n"
            f"--- シラバス本文 ---\n{small_truncate(syllabus_text, 4000)}"
        )
        resp = model.generate_content(prompt)
        text = (resp.text or "").strip()

        # ざっくりパース
        def pick(line_prefix, blob):
            for line in blob.splitlines():
                if line.startswith(line_prefix):
                    return line[len(line_prefix):].strip()
            return ""

        q = ""
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if line.startswith("【問題文】"):
                q = line.replace("【問題文】", "").strip()
                break

        A = pick("A:", text)
        B = pick("B:", text)
        C = pick("C:", text)
        D = pick("D:", text)
        correct_line = ""
        for line in lines:
            if line.startswith("【正解】"):
                correct_line = line.replace("【正解】", "").strip()
                break
        correct = correct_line[:1] if correct_line else ""

        # 解説
        explA = ""
        explB = ""
        explC = ""
        explD = ""
        in_exp = False
        for line in lines:
            if line.startswith("【解説】"):
                in_exp = True
                continue
            if in_exp:
                if line.startswith("A:"):
                    explA = line[2:].strip()
                elif line.startswith("B:"):
                    explB = line[2:].strip()
                elif line.startswith("C:"):
                    explC = line[2:].strip()
                elif line.startswith("D:"):
                    explD = line[2:].strip()

        if not (q and A and B and C and D and correct in ["A","B","C","D"]):
            # 形式が崩れたらフォールバック
            raise ValueError("AI出力のフォーマット不整合")

        payload = {
            "question": q,
            "choices": [A, B, C, D],
            "correct": correct,
            "explain": {"A": explA or "（本文根拠に基づく説明）",
                        "B": explB or "（本文根拠に基づく説明）",
                        "C": explC or "（本文根拠に基づく説明）",
                        "D": explD or "（本文根拠に基づく説明）"}
        }
        set_question_to_state(payload)

    except Exception as e:
        # 429や失敗時はオフラインに切替
        msg = str(e)
        if "429" in msg or "quota" in msg.lower() or "free_tier" in msg.lower():
            st.warning("Geminiの無料枠（クォータ）が 0 のため、オフライン問題を表示します。")
        else:
            st.warning(f"AI出題に失敗しました（{e}）。オフライン問題に切り替えます。")
        set_question_to_state(make_offline_question())

# ======================
# 2) 出題中の画面（phase == question）
# ======================
if st.session_state.phase == "question":
    st.subheader("出題")
    st.write(st.session_state.question)

    options = [
        f"A：{st.session_state.choices[0]}",
        f"B：{st.session_state.choices[1]}",
        f"C：{st.session_state.choices[2]}",
        f"D：{st.session_state.choices[3]}",
    ]
    picked = st.radio("選択肢を選んでください：", options, index=0, key="answer_choice")

    if st.button("回答する"):
        st.session_state.picked = picked.split("：", 1)[0]  # "A"/"B"/"C"/"D"
        st.session_state.phase = "answered"
        st.rerun()  # ← 修正ポイント1

# ======================
# 3) 回答後の画面（phase == answered）
# ======================
if st.session_state.phase == "answered":
    st.subheader("結果")
    picked = st.session_state.picked
    correct = st.session_state.correct

    if picked == correct:
        st.success(f"正解！ 選択：{picked} / 正解：{correct}")
    else:
        st.error(f"不正解。 選択：{picked} / 正解：{correct}")

    st.markdown("**解説**（全選択肢）")
    labels = ["A", "B", "C", "D"]
    for i, lab in enumerate(labels):
        text = st.session_state.choices[i]
        exp = st.session_state.explain.get(lab, "")
        prefix = "✅" if lab == correct else ("🔴" if lab == picked else "・")
        st.write(f"{prefix} {lab}：{text}")
        if exp:
            st.caption(f"解説：{exp}")

    st.divider()
    if st.button("次の問題へ"):
        reset_state()
        st.rerun()  # ← 修正ポイント2
