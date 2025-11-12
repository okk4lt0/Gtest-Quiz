import os
import re
import streamlit as st
import google.generativeai as genai

st.set_page_config(page_title="G検定クイズアプリ（Gemini版）", page_icon="📝", layout="centered")
st.title("G検定クイズアプリ（Gemini版）")

# --- APIキー ---
GEMINI_KEY = st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
if not GEMINI_KEY:
    st.error("GEMINI_API_KEY が未設定です。Streamlit Secrets に GEMINI_API_KEY を保存してください。")
    st.stop()
genai.configure(api_key=GEMINI_KEY)

# SDK バージョン表示（デバッグに有用）
sdk_ver = getattr(genai, "__version__", "unknown")
st.caption(f"google-generativeai version: `{sdk_ver}`")

# --- 利用可能モデルの列挙（公式推奨のやり方） ---
@st.cache_resource
def get_supported_models():
    names = []
    try:
        for m in genai.list_models():
            methods = getattr(m, "supported_generation_methods", [])
            # generateContent をサポートするモデルだけ集める（公式の属性名）
            if "generateContent" in methods:
                # 公式の出力は "models/xxx" 形式なので末尾IDに整形
                model_id = m.name.split("/")[-1]
                names.append(model_id)
    except Exception as e:
        st.warning(f"モデル一覧の取得に失敗しました: {e}")
    return names

supported = get_supported_models()
if supported:
    st.caption("このAPIキーで利用可能なモデル（generateContent対応）:")
    st.code("\n".join(supported), language="text")
else:
    st.warning("このAPIキーで利用可能なモデル一覧を取得できませんでした。通信/権限の問題か、キー種別で制限されている可能性があります。")

# 選好順（上から優先）。存在しない場合は supported の先頭にフォールバック
PREFERRED = [
    "gemini-1.5-flash-latest",
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
    "gemini-1.5-pro",
    "gemini-1.0-pro",
]
def choose_model():
    # supported にあるものの中から優先候補を選ぶ
    for m in PREFERRED:
        if m in supported:
            return m
    # どれも無ければ、supported の先頭を使う（キーが許す唯一の選択肢）
    return supported[0] if supported else None

MODEL_NAME = choose_model()
if not MODEL_NAME:
    st.error("利用可能な Gemini モデルが見つかりません。APIキーのプランや提供状況をご確認ください。")
    st.stop()

st.caption(f"使用モデル: `{MODEL_NAME}`")

SYSTEM_NOTE = (
    "あなたは日本のG検定対策用のAI講師です。事実に基づき、"
    "簡潔で誤解のない表現を心がけ、出力フォーマットを厳守してください。"
)

PROMPT_TEMPLATE = """
{system}

G検定シラバスに関連する基礎事項から、4択の学習問題を**1問だけ**日本語で作成してください。
難易度は初中級。概念理解や用語定義を問う内容にしてください。
以下の**フォーマット厳守**。余計な文や装飾は禁止。

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

def generate_raw():
    prompt = PROMPT_TEMPLATE.format(system=SYSTEM_NOTE)
    model = genai.GenerativeModel(MODEL_NAME)  # 公式の推奨どおりの呼び出し方
    resp = model.generate_content(prompt)       # generateContent を使用
    if not resp or not getattr(resp, "text", None):
        raise RuntimeError("Gemini から有効な応答が得られませんでした。")
    return resp.text.strip()

def parse_question_block(text: str):
    def after(label: str) -> str:
        pat = rf"^{label}[：:]\s*(.*)$"
        for line in text.splitlines():
            m = re.match(pat, line.strip())
            if m:
                return m.group(1).strip()
        return ""

    question = after("問題文")
    options = {k: after(k) for k in ["A", "B", "C", "D"]}
    ans_raw = after("正解").upper()
    answer = ans_raw[:1] if ans_raw[:1] in ["A", "B", "C", "D"] else ""

    notes = {}
    for tag in ["解説", "Aの解説", "Bの解説", "Cの解説", "Dの解説"]:
        val = after(tag)
        if val:
            notes[tag] = f"{tag}：{val}"
    return {"question": question, "options": options, "answer": answer, "notes": notes, "raw": text}

# --- セッション ---
if "item" not in st.session_state:
    st.session_state.item = None
if "picked" not in st.session_state:
    st.session_state.picked = None

with st.expander("使い方（最短）", expanded=False):
    st.markdown("1) 「AIで問題を作る」→ 2) 回答を選んで「回答する」→ 3) 解説を読む")

if st.button("AIで問題を作る"):
    with st.spinner("問題を生成中…"):
        try:
            raw = generate_raw()
            st.session_state.item = parse_question_block(raw)
            st.session_state.picked = None
        except Exception as e:
            st.error(f"生成に失敗しました: {e}")

item = st.session_state.item
if item:
    st.subheader("出題")
    st.write(item["question"] or "問題文の取得に失敗しました。")

    opts = item["options"]
    if all(opts.get(k) for k in ["A", "B", "C", "D"]):
        labels = [f"A：{opts['A']}", f"B：{opts['B']}", f"C：{opts['C']}", f"D：{opts['D']}"]
        choice = st.radio("選択肢を選んでください：", labels, index=0)
        if st.button("回答する"):
            st.session_state.picked = choice[0]
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
    st.caption("「AIで問題を作る」を押すと1問生成されます。")
