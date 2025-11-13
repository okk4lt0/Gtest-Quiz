# app.py
# G検定クイズアプリ（オンライン=Gemini / オフライン=問題バンク）

import os
import json
import random
from datetime import datetime, date
from pathlib import Path

import streamlit as st

# ====== 基本設定 ======
st.set_page_config(page_title="G検定クイズアプリ", page_icon="🧠", layout="centered")

APP_DIR = Path(__file__).parent
DATA_DIR = APP_DIR / "data"
BANK_DIR = APP_DIR / "bank"  # ← リポジトリに合わせて bank に統一
BANK_FILE = BANK_DIR / "question_bank.jsonl"

# ====== ユーティリティ ======
def read_jsonl(path: Path):
    items = []
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except Exception:
                    continue
    return items


def load_offline_bank():
    """bank/question_bank.jsonl を読み込み、形式の違いを吸収して統一フォーマット化。"""
    items = read_jsonl(BANK_FILE)
    bank = []
    for obj in items:
        if "question" not in obj:
            continue

        # choices: リスト or dict の両方に対応
        choices_raw = obj.get("choices", {})
        if isinstance(choices_raw, list):
            if len(choices_raw) != 4:
                continue
            choices = {k: v for k, v in zip(["A", "B", "C", "D"], choices_raw)}
        elif isinstance(choices_raw, dict):
            choices = choices_raw
        else:
            continue

        correct = obj.get("correct") or obj.get("answer")
        if correct not in ["A", "B", "C", "D"]:
            continue

        explanations = obj.get("explanations", {}) or {}
        bank.append(
            {
                "source": obj.get("source", "bank"),
                "question": obj["question"],
                "choices": choices,
                "correct": correct,
                "explanations": explanations,
            }
        )

    if bank:
        return bank

    # バンクが空でも最低限のデフォルト問題
    return [
        {
            "source": "offline_default",
            "question": "教師あり学習の説明として最も適切なのはどれ？",
            "choices": {
                "A": "入力と正解ラベルを用いて学習する",
                "B": "正解ラベルなしで構造を見つける",
                "C": "報酬最大化の行動を学習する",
                "D": "テキスト生成のみを扱う学習法",
            },
            "correct": "A",
            "explanations": {
                "A": "教師あり学習は入力と正解ラベルのペアで学習します。",
                "B": "これは教師なし学習の説明です。",
                "C": "これは強化学習の説明です。",
                "D": "特定タスクの一例であり学習設定そのものではありません。",
            },
        }
    ]


def ensure_state():
    if "question" not in st.session_state:
        st.session_state.question = None
    if "picked" not in st.session_state:
        st.session_state.picked = None
    if "result" not in st.session_state:
        st.session_state.result = None
    if "mode" not in st.session_state:
        st.session_state.mode = None  # "online" / "offline"
    if "model_name" not in st.session_state:
        st.session_state.model_name = None
    if "available_models" not in st.session_state:
        st.session_state.available_models = []

    # 使用量メーター用
    if "usage" not in st.session_state:
        today = date.today().isoformat()
        st.session_state.usage = {
            "daily_limit": 5,
            "minute_limit": 2,
            "today": today,
            "used_today": 0,
            "recent": [],  # UTC timestamp のリスト（直近60秒）
        }


ensure_state()

# ====== Gemini API 周り ======
def get_gemini_api_key():
    try:
        return st.secrets["GEMINI_API_KEY"]
    except Exception:
        return os.getenv("GEMINI_API_KEY")


@st.cache_data(show_spinner=False, ttl=900)
def list_available_models(api_key: str):
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
        models = [
            "models/gemini-2.0-flash",
            "models/gemini-2.0-flash-001",
            "models/gemini-2.0-flash-lite",
        ]
    return sorted(set(models))


def pick_default_model(models: list[str]) -> str:
    if not models:
        return "models/gemini-2.0-flash"
    # 2.5 系優先 → 2.0 系 → 先頭
    for kw in ["2.5", "2.0"]:
        for m in models:
            if kw in m:
                return m
    return models[0]


def generate_with_gemini(model_name: str) -> dict:
    api_key = get_gemini_api_key()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY が設定されていません。")

    import google.generativeai as genai

    genai.configure(api_key=api_key)

    sys_prompt = (
        "あなたはG検定対策の問題作成者です。"
        "四択問題を1問だけ日本語で作成してください。"
        "選択肢はA〜Dの4つ。正答は1つだけ。"
        "各選択肢に短い解説も用意してください。"
        "内容は一般的な機械学習/ディープラーニング/統計/倫理から基本的な範囲とします。"
    )

    generation_config = {
        "response_mime_type": "application/json",
        "temperature": 0.6,
        "max_output_tokens": 600,
    }

    prompt = {
        "instruction": sys_prompt,
        "format": {
            "question": "問題文（1〜2文）",
            "choices": {
                "A": "選択肢A",
                "B": "選択肢B",
                "C": "選択肢C",
                "D": "選択肢D",
            },
            "correct": "A|B|C|D のいずれか1つ",
            "explanations": {
                "A": "Aの解説（1文）",
                "B": "Bの解説（1文）",
                "C": "Cの解説（1文）",
                "D": "Dの解説（1文）",
            },
        },
    }

    model = genai.GenerativeModel(model_name, generation_config=generation_config)
    resp = model.generate_content(
        [{"role": "user", "parts": [json.dumps(prompt, ensure_ascii=False)]}]
    )

    text = ""
    try:
        text = resp.candidates[0].content.parts[0].text
    except Exception:
        text = getattr(resp, "text", "")

    data = json.loads(text)

    req_keys = {"question", "choices", "correct", "explanations"}
    if not req_keys.issubset(data.keys()):
        raise ValueError("JSONに必要なキーが足りません。")

    q = {
        "source": "online",
        "question": data["question"],
        "choices": data["choices"],
        "correct": data["correct"],
        "explanations": data["explanations"],
    }
    return q


# ====== 使用量メーター ======
def reset_usage_if_new_day():
    u = st.session_state.usage
    today = date.today().isoformat()
    if u["today"] != today:
        u["today"] = today
        u["used_today"] = 0
        u["recent"] = []


def can_use_gemini():
    """目安を超えていないかチェックし、OKならカウントを増やす。"""
    reset_usage_if_new_day()
    u = st.session_state.usage
    now = datetime.utcnow().timestamp()
    # 直近60秒だけ残す
    u["recent"] = [t for t in u["recent"] if now - t < 60]

    if u["used_today"] >= u["daily_limit"]:
        return False, "1日の目安回数に達しました。"
    if len(u["recent"]) >= u["minute_limit"]:
        return False, "直近60秒の目安回数に達しました。"

    # ここまで来たら利用OKとしてカウント
    u["used_today"] += 1
    u["recent"].append(now)
    return True, ""


def usage_meter_sidebar():
    u = st.session_state.usage
    with st.sidebar.expander("使用量メーター", expanded=False):
        daily = st.number_input(
            "1日の目安回数",
            min_value=1,
            max_value=100,
            value=u["daily_limit"],
            step=1,
            key="daily_limit_input",
        )
        minute = st.number_input(
            "1分の目安回数",
            min_value=1,
            max_value=60,
            value=u["minute_limit"],
            step=1,
            key="minute_limit_input",
        )
        u["daily_limit"] = int(daily)
        u["minute_limit"] = int(minute)

        st.write(f"今日の使用: {u['used_today']}/{u['daily_limit']}（残り {max(u['daily_limit']-u['used_today'],0)}）")
        st.progress(min(u["used_today"] / max(u["daily_limit"], 1), 1.0))
        st.write(f"直近60秒のリクエスト: {len(u['recent'])}/{u['minute_limit']}")

        if st.button("メーターを手動リセット"):
            today = date.today().isoformat()
            st.session_state.usage.update(
                {"today": today, "used_today": 0, "recent": []}
            )


usage_meter_sidebar()

# ====== 出題フロー ======
def try_online_with_model_chain(selected_model: str):
    """selected_model → 他のモデルの順でオンライン生成を試す。成功したら dict を返す。"""
    api_key = get_gemini_api_key()
    if not api_key:
        return None, "GEMINI_API_KEY が設定されていません。"

    ok, reason = can_use_gemini()
    if not ok:
        return None, f"使用量メーターによりオンライン利用を停止しました（{reason}）"

    models = st.session_state.available_models or []
    chain = []
    if selected_model:
        chain.append(selected_model)
    for m in models:
        if m not in chain:
            chain.append(m)

    last_error = None
    for m in chain:
        try:
            q = generate_with_gemini(m)
            st.session_state.mode = "online"
            st.session_state.model_name = m
            st.success(f"オンライン（Gemini, {m}）で問題を生成しました。")
            return q, None
        except Exception as e:
            last_error = str(e)
            st.warning(f"{m} での生成に失敗しました。別のモデルを試します。")

    return None, last_error or "オンライン生成に失敗しました。"


def start_online_or_offline(selected_model: str):
    st.session_state.result = None
    st.session_state.picked = None

    q, err = try_online_with_model_chain(selected_model)
    if q:
        st.session_state.question = q
        return

    if err:
        st.info(f"オンライン生成に失敗しました（{err}）ので、オフライン問題に切り替えます。")

    bank = load_offline_bank()
    st.session_state.question = random.choice(bank)
    st.session_state.mode = "offline"
    st.session_state.model_name = None


def grade(picked: str):
    q = st.session_state.question
    is_correct = picked == q["correct"]
    st.session_state.result = {
        "is_correct": is_correct,
        "picked": picked,
        "correct": q["correct"],
    }


# ====== UI ======
st.title("G検定クイズアプリ（Gemini/オフライン対応）")

# モデル一覧の取得とデフォルト決定
api_key_present = bool(get_gemini_api_key())
models = []
default_model = "models/gemini-2.0-flash"

if api_key_present:
    models = list_available_models(get_gemini_api_key())
    st.session_state.available_models = models
    if models:
        default_model = pick_default_model(models)

selected_model = st.selectbox(
    "使用モデルを選択（Geminiが使える時のみ有効）",
    options=models if models else [default_model],
    index=0,
    disabled=not api_key_present,
)

st.caption(
    "「AIで問題を作る」を押すと、まず選択した Gemini モデルで出題を試み、"
    "失敗した場合は他のモデルを順に試します。すべて失敗したらオフライン問題に切り替えます。"
)

if st.button("AIで問題を作る", type="primary", key="btn_new"):
    start_online_or_offline(selected_model)

# 出題表示
q = st.session_state.question
if q:
    st.subheader("出題")
    st.write(q["question"])

    choice_labels = [f"{k}：{v}" for k, v in q["choices"].items()]
    if st.session_state.picked is None:
        default_index = 0
    else:
        default_index = list(q["choices"].keys()).index(st.session_state.picked)

    picked_label = st.radio(
        "選択肢を選んでください：",
        options=choice_labels,
        index=default_index,
        key="picked_label_radio",
    )
    picked_key = picked_label.split("：", 1)[0]
    st.session_state.picked = picked_key

    submit_label = (
        "回答する（オンライン）" if st.session_state.mode == "online" else "回答する（オフライン）"
    )
    if st.button(submit_label, key="btn_answer"):
        grade(st.session_state.picked)

# 結果表示
if st.session_state.result and st.session_state.question:
    res = st.session_state.result
    q = st.session_state.question
    st.subheader("結果")

    if res["is_correct"]:
        st.success(f"正解！ 選択：{res['picked']} / 正解：{res['correct']}")
    else:
        st.error(f"不正解… 選択：{res['picked']} / 正解：{res['correct']}")

    st.markdown("**解説（全選択肢）**")
    for key in ["A", "B", "C", "D"]:
        mark = "✅" if key == q["correct"] else "・"
        st.markdown(f"{mark} **{key}：{q['choices'][key]}**")
        st.write(f"解説：{q['explanations'].get(key, '（解説なし）')}")

    if st.button("もう一問出す", key="btn_next"):
        start_online_or_offline(selected_model)

# フッタ
with st.expander("使い方"):
    st.markdown(
        "1. 上でモデルを選択（APIキーがある場合）\n"
        "2. **AIで問題を作る** を押す → オンライン生成に挑戦し、ダメならオフライン\n"
        "3. 回答 → 結果と解説を確認\n"
        "4. **もう一問出す** で繰り返し\n\n"
        "- オフライン問題は `bank/question_bank.jsonl` から読み込みます。"
    )

st.caption(
    ("オンライン: " + (st.session_state.model_name or "—"))
    if st.session_state.mode == "online"
    else "オフライン出題中"
)
