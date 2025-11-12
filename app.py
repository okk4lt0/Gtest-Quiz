import streamlit as st
import openai
import os

# OpenAI APIキーをSecretsから取得
openai.api_key = os.getenv("OPENAI_API_KEY")

st.title("G検定クイズアプリ（AI出題テスト版）")

# 問題を生成する関数
def generate_question():
    prompt = """
    あなたは日本のG検定対策用のAI講師です。
    以下の形式で1問の4択問題を作ってください。

    【出力形式】
    問題文：
    A：
    B：
    C：
    D：
    正解：
    解説：
    Aの解説：
    Bの解説：
    Cの解説：
    Dの解説：
    """
    response = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=600,
        temperature=0.7
    )
    return response.choices[0].message["content"]

# セッションに問題を保持
if "question_data" not in st.session_state:
    if st.button("AIで問題を作る"):
        st.session_state.question_data = generate_question()

# 出題と解答
if "question_data" in st.session_state:
    lines = st.session_state.question_data.splitlines()
    q_text = "\n".join(lines[0:1])
    options = [l[2:] for l in lines if l.startswith(("A：", "B：", "C：", "D："))]
    answer_line = next((l for l in lines if l.startswith("正解：")), "")
    answer = answer_line.replace("正解：", "").strip()

    st.write("###", q_text)
    choice = st.radio("選択肢を選んでください：", options)
    if st.button("回答する"):
        if choice == answer:
            st.success("正解です！ 🎉")
        else:
            st.error(f"不正解。正解は {answer} です。")
        st.write("---")
        st.write("🧠 解説")
        st.write("\n".join(lines[-5:]))
