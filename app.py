import os
import streamlit as st
from openai import OpenAI

# ========================
# 基本設定
# ========================
st.set_page_config(page_title="G検定クイズアプリ（GPT-5版）", page_icon="📝", layout="centered")
st.title("G検定クイズアプリ（GPT-5版）")

# OpenAIクライアント（Secretsの OPENAI_API_KEY を使用）
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ========================
# ヘルパー
# ========================
def generate_question():
    """
    GPT-5（Responses API）で、G検定向けの4択問題を1問生成。
    """
    prompt = """
あなたは日本のG検定対策用のAI講師です。
G検定シラバスの範囲に沿った内容から、1問だけ4択問題を日本語で作成してください。
出力は必ず次のフォーマットで、不要な文言や装飾は付けないでください。

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

    # ✅ GPT-5 は Responses API を使う（max_output_tokens を使用）
    resp = client.responses.create(
        model="gpt-5",
        input=[
            {"role": "system", "content": "あなたは厳密で正確な出題者です。"},
            {"role": "user",   "content": prompt},
        ],
        # temperature はこのモデルで未対応だったので指定しない
        max_output_tokens=800,
    )
    return resp.output_text.strip()

def parse_question_block(text: str):
    """
    生成テキストを簡易パースして {question, options, answer, notes} を返す。
    """
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    # 問題文
    q = next((l.split("：", 1)[-1] if "：" in l else l.split(":", 1)[-1]
              for l in lines if l.startswith("問題文")), "問題が取得できませんでした。")
    # 選択肢
    opts = {}
    for k in ["A", "B", "C", "D"]:
        line = next((l for l in lines if l.startswith(f"{k}：") or l.startswith(f"{k}:")), None)
        if line:
            opts[k] = line.split("：", 1)[-1].split(":", 1)[-1].strip()
    # 正解
    ans_line = next((l for l in lines if l.startswith("正解")), "")
    ans = (ans_line.replace("正解：", "").replace("正解:", "").strip() or "").upper()
    ans = ans[:1] if ans[:1] in ["A", "B", "C", "D"] else ""

    # 解説群（そのまま表示）
    notes = {}
    for tag in ["解説", "Aの解説", "Bの解説", "Cの解説", "Dの解説"]:
        seg = next((l for l in lines if l.startswith(tag)), None)
        if seg:
            notes[tag] = seg

    return {
        "question": q,
        "options": opts,
        "answer": ans,
        "notes": notes,
        "raw": text
    }

# ========================
# UI（セッション管理）
# ========================
if "item" not in st.session_state:
    st.session_state.item = None
if "picked" not in st.session_state:
    st.session_state.picked = None

with st.expander("使い方（最短）", expanded=False):
    st.markdown(
        "1) 「AIで問題を作る」を押す → 2) 回答を選んで「回答する」 → 3) 解説を読む\n"
        "※ まずはランダム出題。あとでシラバスPDF対応を加えられます。"
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
    st.write(item["question"])

    opts = item["options"]
    if len(opts) == 4:
        labels = [f"A：{opts['A']}", f"B：{opts['B']}", f"C：{opts['C']}", f"D：{opts['D']}"]
        choice = st.radio("選択肢を選んでください：", labels, index=0)
        if st.button("回答する"):
            st.session_state.picked = choice[0]  # 先頭の A/B/C/D を取る

    if st.session_state.picked:
        ans = item["answer"]
        if not ans:
            st.warning("正解の抽出に失敗しました。生成結果を確認してください。")
            st.code(item["raw"])
        else:
            ok = (st.session_state.picked == ans)
            if ok:
                st.success("正解です！🎉")
            else:
                st.error(f"不正解。正解は {ans} です。")

        st.divider()
        st.subheader("🧠 解説")
        notes = item["notes"]
        # 全体解説
        if "解説" in notes:
            st.write(notes["解説"])
        # 選択肢ごとの解説（あれば）
        for tag in ["Aの解説", "Bの解説", "Cの解説", "Dの解説"]:
            if tag in notes:
                st.write(notes[tag])
    else:
        st.caption("※ 回答を選んで「回答する」を押してください。")

else:
    st.caption("「AIで問題を作る」を押すと1問生成されます。")
