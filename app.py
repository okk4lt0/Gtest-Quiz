# app.py
# G検定クイズ（オンライン=Gemini → 失敗時はオフライン）
# 依存: streamlit, google-generativeai, pypdf（オフライン時は不要）

import os
import json
from pathlib import Path
import random
import streamlit as st

# ===== 基本設定 =====
st.set_page_config(page_title="G検定クイズアプリ", page_icon="🧠", layout="centered")

APP_DIR = Path(__file__).parent
DATA_DIR = APP_DIR / "data"
BANK_DIR = APP_DIR / "bank"                      # ← リポジトリの bank/ を参照
BANK_FILE = BANK_DIR / "question_bank.jsonl"     # 1行1問の JSON Lines

# ===== 状態確保 =====
def ensure_state():
    ss = st.session_state
    ss.setdefault("question", None)     # 現在の出題（dict）
    ss.setdefault("picked", None)       # "A"〜"D"
    ss.setdefault("result", None)       # 採点結果
    ss.setdefault("mode", None)         # "online" / "offline"
    ss.setdefault("model_name", None)   # 実際に使ったモデル名
ensure_state()

# ===== ユーティリティ =====
def normalize_item(item: dict) -> dict | None:
    """行ごとの辞書をアプリ内部の統一形式に変換"""
    if not isinstance(item, dict):
        return None
    q = item.get("question")
    choices = item.get("choices")
    correct = item.get("correct") or item.get("answer")

    # choices が配列なら A〜D に割り当て
    if isinstance(choices, list) and len(choices) == 4:
        choices = {k: v for k, v in zip(["A", "B", "C", "D"], choices)}

    if not q or not isinstance(choices, dict) or len(choices) != 4:
        return None
    if correct not in ["A", "B", "C", "D"]:
        return None

    return {
        "source": item.get("source", "offline"),
        "question": q,
        "choices": choices,
        "correct": correct,
        "explanations": item.get("explanations", {})
    }

def read_jsonl(path: Path) -> list[dict]:
    items = []
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                except Exception:
                    continue
                norm = normalize_item(raw)
                if norm:
                    items.append(norm)
    return items

def load_offline_bank() -> list[dict]:
    bank = read_jsonl(BANK_FILE)
    if bank:
        return bank
    # バンクが空のときの最低限の1問
    return [{
        "source": "offline_default",
        "question": "教師あり学習の説明として最も適切なのはどれ？",
        "choices": {
            "A": "入力と正解ラベルを用いて学習する",
            "B": "正解ラベルなしで構造を見つける",
            "C": "報酬最大化の行動を学習する",
            "D": "テキスト生成のみを扱う学習法"
        },
        "correct": "A",
        "explanations": {
            "A": "教師あり学習は入力と正解ラベルのペアで学習します。",
            "B": "これは教師なし学習の説明です。",
            "C": "これは強化学習の説明です。",
            "D": "学習設定の説明ではありません。"
        }
    }]

# ===== Gemini（オンライン） =====
def get_gemini_api_key() -> str | None:
    try:
        return st.secrets["GEMINI_API_KEY"]
    except Exception:
        return os.getenv("GEMINI_API_KEY")

@st.cache_data(show_spinner=False, ttl=900)
def list_available_models(api_key: str) -> list[str]:
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    models = []
    try:
        for m in genai.list_models():
            methods = getattr(m, "supported_generation_methods", []) or []
            if "generateContent" in methods:
                models.append(m.name)
    except Exception:
        # 取得失敗時のフォールバック候補
        models = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.0-flash-lite"]
    return sorted(models)

def generate_with_gemini(model_name: str) -> dict:
    """Geminiで1問生成し内部形式で返す。失敗時は例外を送出。"""
    api_key = get_gemini_api_key()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY が設定されていません。")

    import google.generativeai as genai
    genai.configure(api_key=api_key)

    sys_prompt = (
        "あなたはG検定対策の問題作成者です。四択問題を1問だけ日本語で作成。"
        "選択肢はA〜Dで1つだけ正解。各選択肢に1文の解説を付ける。"
        "内容は機械学習/ディープラーニング/統計/倫理の基礎範囲から。"
    )
    generation_config = {
        "response_mime_type": "application/json",
        "temperature": 0.6,
        "max_output_tokens": 600,
    }
    payload = {
        "question": "問題文（1〜2文）",
        "choices": {"A": "…", "B": "…", "C": "…", "D": "…"},
        "correct": "A|B|C|D のいずれか1つ",
        "explanations": {"A": "…", "B": "…", "C": "…", "D": "…"}
    }

    model = genai.GenerativeModel(model_name, generation_config=generation_config)
    resp = model.generate_content([{"role": "user", "parts": [sys_prompt, json.dumps(payload, ensure_ascii=False)]}])

    text = ""
    try:
        text = resp.candidates[0].content.parts[0].text
    except Exception:
        text = getattr(resp, "text", "") or ""

    data = json.loads(text)
    norm = normalize_item(data)
    if not norm:
        raise ValueError("Gemini応答の形式が不正です。")
    norm["source"] = "online"
    return norm

# ===== 出題・採点 =====
def start_online_or_offline(model_choice: str):
    """まずオンラインに挑戦。失敗ならオフラインへ切替。"""
    st.session_state.result = None
    st.session_state.picked = None
    st.session_state.model_name = None

    try:
        q = generate_with_gemini(model_choice)
        st.session_state.question = q
        st.session_state.mode = "online"
        st.session_state.model_name = model_choice
        st.success("オンライン（Gemini）で問題を生成しました。")
        return
    except Exception:
        st.info("Geminiが使えないため、オフライン問題に切り替えます。")

    bank = load_offline_bank()
    st.session_state.question = random.choice(bank)
    st.session_state.mode = "offline"

def grade(picked: str):
    q = st.session_state.question
    st.session_state.result = {
        "is_correct": (picked == q["correct"]),
        "picked": picked,
        "correct": q["correct"]
    }

# ===== UI =====
st.title("G検定クイズ（Gemini/オフライン対応）")

api_key = get_gemini_api_key()
models = list_available_models(api_key) if api_key else []
selected_model = st.selectbox(
    "使用モデル（キー未設定時は無効）",
    options=models if models else ["gemini-2.0-flash"],
    index=0,
    disabled=not bool(api_key),
)

st.caption("まず Gemini で生成を試み、失敗時は自動でオフライン問題に切替します。")

if st.button("AIで問題を作る", type="primary"):
    start_online_or_offline(selected_model)

q = st.session_state.question
if q:
    st.subheader("出題")
    st.write(q["question"])

    # Radio 用ラベル
    labels = [f"{k}：{v}" for k, v in q["choices"].items()]
    # 直前選択の維持
    default_idx = 0
    if st.session_state.picked in q["choices"]:
        default_idx = ["A", "B", "C", "D"].index(st.session_state.picked)

    chosen_label = st.radio(
        "選択肢：", options=labels, index=default_idx, key="picked_label_radio"
    )
    st.session_state.picked = chosen_label.split("：", 1)[0]

    submit_label = "回答する（オンライン）" if st.session_state.mode == "online" else "回答する（オフライン）"
    if st.button(submit_label):
        grade(st.session_state.picked)

# 結果は問題の下に表示（問題は残す）
if st.session_state.result and st.session_state.question:
    res = st.session_state.result
    q = st.session_state.question
    st.subheader("結果")

    if res["is_correct"]:
        st.success(f"正解！ 選択：{res['picked']} / 正解：{res['correct']}")
    else:
        st.error(f"不正解… 選択：{res['picked']} / 正解：{res['correct']}")

    st.markdown("**解説（全選択肢）**")
    for k in ["A", "B", "C", "D"]:
        head = "✅" if k == q["correct"] else "・"
        st.markdown(f"{head} **{k}：{q['choices'][k]}**")
        st.write(f"解説：{q['explanations'].get(k, '（解説なし）')}")

    if st.button("もう一問出す"):
        st.session_state.result = None
        st.session_state.picked = None
        start_online_or_offline(selected_model)

# フッタ
mode_info = ("オンライン: " + (st.session_state.model_name or "—")) if st.session_state.mode == "online" else "オフライン出題中"
st.caption(mode_info)
