import os
import streamlit as st
from openai import OpenAI

# ✅ GPT-5 対応クライアント
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

st.title("G検定クイズアプリ（GPT-5版）")

# === 問題をAIで生成 ===
def generate_question():
    prompt = """
あなたは日本のG検定対策用のAI講師です。
以下の形式で1問の4択問題を日本語で作ってください。
必ずG検定シラバスに関連する内容にしてください。

【出力形式】
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
"""
    resp = client.chat.completions.create(
        model="gpt-5",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        max_output_tokens=800,
    )
    return resp.choices[0].message.content.strip()

# === メイン処理 ===
if "question_data" not in st.session_state:
    if st.button("AIで問題を作る"):
        with st.spinner("問題を生成中...（数秒お待ちください）"):
            st.session_state.question_data = generate_question()

# === 出題と回答 ===
if "question_data" in st.session_state:
    lines = [l.strip() for l in st.session_state.question_data.splitlines() if l.strip()]
    q_text = next((l.replace("問題文：", "").replace("問題文:", "") for l in lines if "問題文" in l), "問題が生成されませんでした。")
    st.write("### 問題")
    st.write(q_text)

    # 選択肢抽出
    options = {}
    for k in ["A", "B", "C", "D"]:
        opt = next((l for l in lines if l.startswith(f"{k}：") or l.startswith(f"{k}:")), None)
        if opt:
            options[k] = opt.split("：", 1)[-1].split(":", 1)[-1].strip()

    answer_line = next((l for l in lines if l.startswith("正解")), "")
    answer = answer_line.replace("正解：", "").replace("正解:", "").strip()

    if options:
        selected = st.radio("選択肢を選んでください：",
                            [f"A：{options['A']}", f"B：{options['B']}",
                             f"C：{options['C']}", f"D：{options['D']}"])
        if st.button("回答する"):
            picked = selected[0]
            if picked == answer:
                st.success("正解です！🎉")
            else:
                st.error(f"不正解です。正解は {answer} です。")
            st.divider()
            st.subheader("🧠 解説")
            for tag in ["解説", "Aの解説", "Bの解説", "Cの解説", "Dの解説"]:
                seg = next((l for l in lines if l.startswith(tag)), None)
                if seg:
                    st.write(seg)
