import os
import re
import streamlit as st

# --- Gemini (Google) ---
# pip: google-generativeai
import google.generativeai as genai

# ========================
# 基本設定
# ========================
st.set_page_config(page_title="G検定クイズアプリ（Gemini版）", page_icon="📝", layout="centered")
st.title("G検定クイズアプリ（Gemini版）")

# Secrets から API キーを取得
GEMINI_KEY = st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
if not GEMINI_KEY:
    st.error("GEMINI_API_KEY が設定されていません（Streamlit Secrets に GEMINI_API_KEY を追加してください）。")
    st.stop()

genai.configure(api_key=GEMINI_KEY)
MODEL_NAME = "gemini-1.5-flash"  # 無料枠で軽快・高性能

# ========================
# ヘルパー
# ========================
SYSTEM_NOTE = (
    "あなたは日本のG検定対策用のAI講師です。事実に基づき、"
    "簡潔で誤解のない表現を心がけ、出力フォーマットを厳守してください。"
)

PROMPT_TEMPLATE = """
{system}

G検定シラバス（一般的な内容）に関連するトピックから、
4択の学習問題を**1問だけ**日本語で作成してください。
難易度は初中級程度。用語の定義や基礎的な理解を問う出題にしてください。

必ず**次のフォーマット**で出力してください。余計な文章や装飾は禁止です。

問題文：
A：
B：
C：
D：
正解：（A〜Dのいずれか）
解説：
Aの解説：
Bの解説：
Cの解説：
Dの解説：
""".strip()


def call_gemini(prompt: str) -> str:
    """Geminiへ投げてテキストを得る（例外は上位で処理）"""
    model = genai.GenerativeModel(MODEL_NAME)
    resp = model.generate_content(prompt)
    # safety/empty 対応
    if not resp or not getattr(resp, "text", None):
        raise RuntimeError("Gemini から有効な応答が得られませんでした。")
    return resp.text.strip()


def parse_question_block(text: str):
    """
    生成テキストをフォーマットに沿ってパース。
    戻り値: {question, options:{A..D}, answer, notes:{...}, raw}
    """
    # 全角コロン・半角コロンに両対応
    def after(label: str) -> str:
        pat = rf"^{label}[：:]\s*(.*)$"
        for line in text.splitlines():
            m = re.match(pat, line.strip())
            if m:
                return m.group(1).strip()
        return ""

    question = after("問題文")
    options = {k: after(k) for k in ["A", "B", "C", "D"]}

    # 正解行（先頭の A/B/C/D を拾う）
    ans_raw = after("正解")
    answer = ""
    if ans_raw:
        head = ans_raw.strip().upper()[:1]
        if head in ["A", "B", "C", "D"]:
            answer = head

    notes = {}
    for tag in ["解説", "Aの解説", "Bの解説", "Cの解説", "Dの解説"]:
        val = after(tag)
        if val:
            notes[tag] = f"{tag}：{val}"

    return {
        "question": question,
        "options": options,
        "answer": answer,
        "notes": notes,
        "raw": text,
    }


def generate_question():
    prompt = PROMPT_TEMPLATE.format(system=SYSTEM_NOTE)
    text = call_gemini(prompt)
    return text


# ========================
# UI（セッション）
# ========================
if "item" not in st.session_state:
    st.session_state.item = None
if "picked" not in st.session_state:
    st.session_state.picked = None

with st.expander("使い方（最短）", expanded=False):
    st.markdown(
        "1) 「AIで問題を作る」を押す → 2) 回答を選んで「回答する」 → 3) 解説を読む\n"
        "まずはランダム出題。あとでPDFシラバスの読込にも対応できます。"
    )

col1, col2 = st.columns(2)
with col1:
    if st.button("AIで問題を作る"):
        with st.spinner("問題を生成中…"):
            try:
                raw = generate_question()
                st.session_state.item = parse_question_block(raw)
                st.session_state.picked = None
            except Exception as e:
                st.error(f"生成に失敗しました: {e}")

# ========================
# 出題〜判定表示
# ========================
item = st.session_state.item
if item:
    st.subheader("出題")
    st.write(item["question"] or "問題文の取得に失敗しました。")

    opts = item["options"]
    if all(opts.get(k) for k in ["A", "B", "C", "D"]):
        labels = [f"A：{opts['A']}", f"B：{opts['B']}", f"C：{opts['C']}", f"D：{opts['D']}"]
        choice = st.radio("選択肢を選んでください：", labels, index=0)
        if st.button("回答する"):
            st.session_state.picked = choice[0]  # ラベル先頭の A/B/C/D
    else:
        st.warning("選択肢の抽出に失敗しました。生成結果を下で確認してください。")
        st.code(item["raw"])

    if st.session_state.picked:
        ans = item["answer"]
        if not ans:
            st.warning("正解の抽出に失敗しました。生成結果を確認してください。")
            st.code(item["raw"])
        else:
            ok = (st.session_state.picked == ans)
            st.success("正解です！🎉") if ok else st.error(f"不正解。正解は {ans} です。")

        st.divider()
        st.subheader("🧠 解説")
        notes = item["notes"]
        if "解説" in notes:
            st.write(notes["解説"])
        for tag in ["Aの解説", "Bの解説", "Cの解説", "Dの解説"]:
            if tag in notes:
                st.write(notes[tag])
    else:
        st.caption("※ 回答を選んで「回答する」を押してください。")

else:
    st.caption("「AIで問題を作る」を押すと1問生成されます。")
