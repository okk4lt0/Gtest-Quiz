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

sdk_ver = getattr(genai, "__version__", "unknown")
st.caption(f"google-generativeai version: `{sdk_ver}`")

# --- 利用可能モデルの列挙 ---
@st.cache_resource
def get_supported_models():
    names = []
    try:
        for m in genai.list_models():
            methods = getattr(m, "supported_generation_methods", [])
            if "generateContent" in methods:
                names.append(m.name.split("/")[-1])
    except Exception as e:
        st.warning(f"モデル一覧の取得に失敗しました: {e}")
    return sorted(set(names))

supported = get_supported_models()
if supported:
    with st.expander("このAPIキーで利用可能なモデル（generateContent対応）", expanded=False):
        st.code("\n".join(supported), language="text")
else:
    st.error("利用可能モデルを取得できませんでした。プロジェクトのクォータ／権限を確認してください。")
    st.stop()

# よく使う候補を先頭に来るよう並べ替え
PREFERRED_ORDER = [
    "gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.0-flash-001",
    "gemini-flash-latest", "gemini-2.5-flash-lite", "gemini-2.0-flash-lite",
    "gemini-2.5-pro", "gemini-pro-latest"
]
ordered = sorted(supported, key=lambda m: (PREFERRED_ORDER.index(m) if m in PREFERRED_ORDER else 999, m))

# --- モデル選択UI ---
default_model = ordered[0]
model_name = st.selectbox("使用モデルを選択", ordered, index=ordered.index(default_model))
st.caption(f"使用モデル: `{model_name}`")

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
    model = genai.GenerativeModel(model_name)
    # できるだけ短く（無料枠節約用）※枠0の場合は無意味ですが将来のため
    resp = model.generate_content(prompt)
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
