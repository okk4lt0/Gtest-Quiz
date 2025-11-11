import os, json
from io import BytesIO
import streamlit as st

# ===== LLM（OpenAI互換API）=====
try:
    from openai import OpenAI
    client = OpenAI()  # OPENAI_API_KEY を使用
    MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
except Exception:
    client = None
    MODEL = None

def ask_llm(messages, temperature=0.2, max_tokens=800):
    if client is None or MODEL is None:
        raise RuntimeError("LLM未設定: OPENAI_API_KEY またはモデルが未設定です。")
    resp = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )
    return resp.choices[0].message.content

# ===== PDF抽出 =====
from pdfminer.high_level import extract_text

def extract_text_from_pdf(uploaded_file):
    data = uploaded_file.read()
    return extract_text(BytesIO(data))

# ===== UI =====
st.set_page_config(page_title="G検定シラバス出題(MVP)", page_icon="📝", layout="centered")
st.title("📝 G検定シラバス 自動4択出題（MVP）")

with st.expander("使い方", expanded=False):
    st.markdown(
        "1) シラバスPDFをアップロード **または** テキストを貼り付け\n"
        "2) 「問題を作成 / 次の問題」→ 回答 → 解説\n"
        "※ 生成はシラバス内の記述に限定されます"
    )

mode = st.radio("入力モード", ["PDFアップロード", "テキスト貼り付け"], index=0, horizontal=True)
syllabus = ""

if mode == "PDFアップロード":
    pdf_file = st.file_uploader("G検定シラバスPDFを選択", type=["pdf"])
    if pdf_file:
        with st.spinner("PDFを解析中..."):
            try:
                text = extract_text_from_pdf(pdf_file)
                syllabus = text[:120000]  # MVP: 長文は一部のみ使用
                st.success("PDFからテキストを抽出しました")
            except Exception as e:
                st.error(f"PDF抽出に失敗: {e}")
else:
    syllabus = st.text_area("シラバス本文を貼り付け", height=220)

col1, col2, col3 = st.columns(3)
difficulty = col1.selectbox("難易度", ["易", "中", "難"], index=1)
qstyle = col2.selectbox("問い方", ["定義", "用語", "計算", "穴埋め", "正誤判定"], index=4)
scope = col3.text_input("出題範囲（章/節など任意）", value="全体")

if "item" not in st.session_state:
    st.session_state.item = None
if "picked" not in st.session_state:
    st.session_state.picked = None

def build_messages(syl: str):
    system = (
        "あなたは資格試験の出題者です。ユーザーが与えたシラバスのみを根拠に、"
        "単一正解の4択問題を1問だけ作ります。出力は必ずJSONスキーマに従うこと。"
        "シラバスにない事実・推測は禁止。"
    )
    user = f"""
<syllabus>
{syl}
</syllabus>

要件:
- 難易度: {difficulty}
- 問い方: {qstyle}
- 出題範囲: {scope}

出力はJSONのみ。スキーマ:
{{
  "question": "string(40-120字目安)",
  "choices": [
    {{"id": "A", "text": "string"}},
    {{"id": "B", "text": "string"}},
    {{"id": "C", "text": "string"}},
    {{"id": "D", "text": "string"}}
  ],
  "answer": "A|B|C|D",
  "explanations": {{
    "A":"string","B":"string","C":"string","D":"string"
  }},
  "source_spans": ["根拠となる該当箇所（章番号や抜粋）"]
}}
"""
    return [{"role": "system", "content": system},
            {"role": "user", "content": user}]

def new_question():
    msgs = build_messages(syllabus)
    raw = ask_llm(msgs)
    try:
        item = json.loads(raw)
        assert set([c["id"] for c in item["choices"]]) == {"A","B","C","D"}
        assert item["answer"] in {"A","B","C","D"}
        st.session_state.item = item
        st.session_state.picked = None
    except Exception:
        st.error("生成結果の解析に失敗しました。")
        st.code(raw)

st.divider()
disabled = not (syllabus and syllabus.strip())
if st.button("問題を作成 / 次の問題", disabled=disabled):
    new_question()

item = st.session_state.item
if item:
    st.subheader("出題")
    st.write(item.get("question","(問題文なし)"))
    labels = {c["id"]: f'{c["id"]}. {c["text"]}' for c in item["choices"]}
    choice = st.radio("あなたの解答", ["A","B","C","D"], format_func=lambda k: labels[k], index=0)
    if st.button("回答する"):
        st.session_state.picked = choice

    if st.session_state.picked:
        ans = item["answer"]
        ok = (st.session_state.picked == ans)
        st.success("正解！🎉") if ok else st.error(f"不正解。正解は {ans} です。")
        st.markdown("### 解説（全選択肢）")
        for k in ["A","B","C","D"]:
            bullet = "✅" if k==ans else "✳️" if k==st.session_state.picked else "・"
            st.markdown(f"**{bullet} {k}. {labels[k][3:]}**\n\n{item['explanations'].get(k,'(説明なし)')}")
        if item.get("source_spans"):
            st.caption("根拠: " + " / ".join(item["source_spans"]))
