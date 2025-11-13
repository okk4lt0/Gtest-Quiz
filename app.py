# app.py
# G検定クイズアプリ（オンライン=Gemini / オフライン=問題バンク）
# 依存: streamlit, google-generativeai

import os
import json
import random
from datetime import datetime, date
from pathlib import Path

import streamlit as st

# ========= 基本設定 =========
st.set_page_config(page_title="G検定クイズアプリ", page_icon="🧠", layout="centered")

APP_DIR = Path(__file__).parent
BANK_DIR = APP_DIR / "bank"
BANK_FILE = BANK_DIR / "question_bank.jsonl"
QUOTA_STATS_FILE = BANK_DIR / "quota_stats.json"

# ========= クォータ学習用ユーティリティ =========

def load_quota_stats() -> dict:
    if not QUOTA_STATS_FILE.exists():
        return {}
    try:
        with QUOTA_STATS_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_quota_stats(stats: dict) -> None:
    try:
        with QUOTA_STATS_FILE.open("w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
    except Exception:
        # 書き込みに失敗してもアプリ自体は動くようにする
        pass


def register_quota_call(result: str) -> None:
    """
    result: "success" / "429" / "error"
    1回のオンライン出題試行ごとに呼び出す。
    """
    stats = load_quota_stats()
    today = date.today().isoformat()
    entry = stats.get(today, {"calls": 0, "had_429": False})
    entry["calls"] = int(entry.get("calls", 0)) + 1
    if result == "429":
        entry["had_429"] = True
    stats[today] = entry
    save_quota_stats(stats)


def estimate_daily_limit_from_stats(default_limit: int = 5) -> int:
    """
    quota_stats.json から「安全そうな1日上限」を推定する。
    あくまで目安であり、Google 公式のクォータではない。
    """
    stats = load_quota_stats()
    if not stats:
        return default_limit

    min_calls_at_429 = None
    max_calls_without_429 = 0

    for _, entry in stats.items():
        calls = int(entry.get("calls", 0))
        had_429 = bool(entry.get("had_429", False))
        if had_429 and calls > 0:
            if min_calls_at_429 is None or calls < min_calls_at_429:
                min_calls_at_429 = calls
        elif not had_429:
            if calls > max_calls_without_429:
                max_calls_without_429 = calls

    limit = default_limit

    # 429 が観測されている場合は、その中で最も早く詰んだ回数をベースに安全側に寄せる
    if min_calls_at_429 is not None:
        safe = int(min_calls_at_429 * 0.7)
        if safe < 3:
            safe = 3
        limit = safe

    # 429 が一度も無いが、結構使っているなら少し上振れさせる
    elif max_calls_without_429 > default_limit:
        limit = max_calls_without_429 + 2

    # 上限の下限を少しだけ確保
    if limit < 3:
        limit = 3

    return limit


# ========= オフライン問題読み込み =========

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
    """
    bank/question_bank.jsonl を読み込み、形式を統一して返す。
    - 自動生成: choices がリスト ["Aの文", ...]
    - 手作業: choices が {"A": "..."} の dict
    どちらも吸収して {question, choices(dict), correct, explanations} で返す。
    """
    items = read_jsonl(BANK_FILE)
    bank = []

    for obj in items:
        if "question" not in obj:
            continue

        raw_choices = obj.get("choices", {})
        if isinstance(raw_choices, list):
            if len(raw_choices) != 4:
                continue
            choices = {k: v for k, v in zip(["A", "B", "C", "D"], raw_choices)}
        elif isinstance(raw_choices, dict):
            choices = raw_choices
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

    # バンクが空だった場合の最低限デフォルト
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


# ========= セッション状態 =========

def ensure_state():
    if "question" not in st.session_state:
        st.session_state.question = None
    if "picked" not in st.session_state:
        st.session_state.picked = None
    if "result" not in st.session_state:
        st.session_state.result = None  # {"is_correct", "picked", "correct"}
    if "mode" not in st.session_state:
        st.session_state.mode = None    # "online" or "offline"
    if "model_name" not in st.session_state:
        st.session_state.model_name = None
    if "available_models" not in st.session_state:
        st.session_state.available_models = []

    if "usage" not in st.session_state:
        today = date.today().isoformat()
        # daily_limit は後で推定値に上書きする
        st.session_state.usage = {
            "daily_limit": 5,
            "minute_limit": 2,
            "today": today,
            "used_today": 0,
            "recent": [],  # UTC timestamp の配列（直近60秒）
        }


ensure_state()

# 推定クォータから daily_limit を初期化
_estimated = estimate_daily_limit_from_stats(default_limit=5)
st.session_state.usage["daily_limit"] = _estimated

# ========= Gemini API =========

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
        # フォールバック候補
        models = [
            "models/gemini-2.0-flash",
            "models/gemini-2.0-flash-001",
            "models/gemini-2.0-flash-lite",
        ]
    # 重複除去してソート
    return sorted(set(models))


def pick_default_model(models: list[str]) -> str:
    if not models:
        return "models/gemini-2.0-flash"
    # 2.5 を含む名前を優先 → 2.0 → 最初
    for kw in ["2.5", "2.0"]:
        for m in models:
            if kw in m:
                return m
    return models[0]


def generate_with_gemini(model_name: str) -> dict:
    """
    Gemini で四択問題を JSON 形式で1問生成。
    正常終了なら dict を返し、エラー時は例外を投げる。
    """
    api_key = get_gemini_api_key()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY が設定されていません。")

    import google.generativeai as genai

    genai.configure(api_key=api_key)

    sys_prompt = (
        "あなたはG検定対策の問題作成者です。"
        "四択問題を1問だけ日本語で作成してください。"
        "選択肢はA〜Dの4つで、正答は1つだけ。"
        "各選択肢に1文程度の解説も付けてください。"
        "内容はG検定一般レベルの、機械学習/ディープラーニング/統計/倫理などから広く選んでください。"
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

    model = genai.GenerativeModel(
        model_name,
        generation_config=generation_config,
    )

    resp = model.generate_content(
        [{"role": "user", "parts": [json.dumps(prompt, ensure_ascii=False)]}]
    )

    text = ""
    try:
        text = resp.candidates[0].content.parts[0].text
    except Exception:
        text = getattr(resp, "text", "")

    data = json.loads(text)

    required = {"question", "choices", "correct", "explanations"}
    if not required.issubset(data.keys()):
        raise ValueError("JSONに必要なキーが足りません。")

    q = {
        "source": "online",
        "question": data["question"],
        "choices": data["choices"],
        "correct": data["correct"],
        "explanations": data["explanations"],
    }
    return q


# ========= 使用量メーター =========

def reset_usage_if_new_day():
    u = st.session_state.usage
    today = date.today().isoformat()
    if u["today"] != today:
        u["today"] = today
        u["used_today"] = 0
        u["recent"] = []


def can_use_gemini():
    """
    目安の上限を超えていないかをチェック。
    OKなら usage を1つ進める。
    """
    reset_usage_if_new_day()
    u = st.session_state.usage
    now = datetime.utcnow().timestamp()

    # 直近60秒だけ残す
    u["recent"] = [t for t in u["recent"] if now - t < 60]

    if u["used_today"] >= u["daily_limit"]:
        return False, "このアプリ上の '1日の目安回数' を超えます。"
    if len(u["recent"]) >= u["minute_limit"]:
        return False, "このアプリ上の '直近60秒の目安回数' を超えます。"

    u["used_today"] += 1
    u["recent"].append(now)
    return True, ""


def usage_meter_sidebar():
    u = st.session_state.usage
    with st.sidebar.expander("使用量メーター（このアプリ内の目安）", expanded=False):
        st.write(
            "※ ここでの数値は **Google公式のクォータ残量ではありません**。\n"
            "　このブラウザからオンライン出題を試みた回数を、アプリ側で数えている目安です。"
        )

        daily_default = u["daily_limit"]
        minute_default = u["minute_limit"]

        daily = st.number_input(
            "1日の目安回数（このアプリからオンライン出題を試す回数）",
            min_value=1,
            max_value=100,
            value=int(daily_default),
            step=1,
            key="daily_limit_input",
        )
        minute = st.number_input(
            "直近60秒の目安回数（連続で叩きすぎないための目安）",
            min_value=1,
            max_value=60,
            value=int(minute_default),
            step=1,
            key="minute_limit_input",
        )

        u["daily_limit"] = int(daily)
        u["minute_limit"] = int(minute)

        st.write(
            f"今日のオンライン出題試行（このブラウザ）: {u['used_today']} / {u['daily_limit']} "
            f"(残り {max(u['daily_limit'] - u['used_today'], 0)})"
        )
        st.progress(min(u["used_today"] / max(u["daily_limit"], 1), 1.0))

        st.write(f"直近60秒のオンライン出題試行: {len(u['recent'])} / {u['minute_limit']}")

        if st.button("今日のカウンターをリセット"):
            today = date.today().isoformat()
            u.update({"today": today, "used_today": 0, "recent": []})
            st.success("このアプリ内のカウンターをリセットしました。")


usage_meter_sidebar()

# ========= 出題フロー（オンライン優先 → 失敗でオフライン） =========

def is_429_error(e: Exception) -> bool:
    s = str(e)
    return ("429" in s) or ("Resource exhausted" in s) or ("ResourceExhausted" in s)


def try_online_with_model_chain(selected_model: str):
    """
    selected_model → 他のモデルの順にオンライン出題を試す。
    成功したら (question_dict, None) を返す。
    すべて失敗したら (None, last_error_message) を返す。
    """
    api_key = get_gemini_api_key()
    if not api_key:
        return None, "GEMINI_API_KEY が設定されていません。"

    ok, reason = can_use_gemini()
    if not ok:
        return None, reason

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
            register_quota_call("success")
            st.session_state.mode = "online"
            st.session_state.model_name = m
            return q, None
        except Exception as e:
            if is_429_error(e):
                register_quota_call("429")
            else:
                register_quota_call("error")
            last_error = str(e)

    return None, last_error or "オンライン生成に失敗しました。"


def start_online_or_offline(selected_model: str):
    """
    1問分の出題を開始。
    まずオンラインを試し、ダメならオフラインバンクからランダム出題。
    """
    st.session_state.result = None
    st.session_state.picked = None

    q, err = try_online_with_model_chain(selected_model)
    if q:
        st.session_state.question = q
        return

    msg = "Geminiオンライン出題に失敗したため、オフライン問題バンクから出題します。"
    if err:
        msg += f"\n（参考情報: {err}）"
    st.info(msg)

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


# ========= UI =========

st.title("G検定クイズアプリ（Gemini / オフライン対応）")

api_key_present = bool(get_gemini_api_key())
models = []
default_model = "models/gemini-2.0-flash"

if api_key_present:
    models = list_available_models(get_gemini_api_key())
    st.session_state.available_models = models
    if models:
        default_model = pick_default_model(models)

selected_model = st.selectbox(
    "使用するGeminiモデル（オンライン出題に成功した場合のみ利用）",
    options=models if models else [default_model],
    index=0,
    disabled=not api_key_present,
)

st.caption(
    "「AIで問題を作る」を押すと、まず選択した Gemini モデルでオンライン出題を試み、"
    "失敗した場合は別モデルを試し、それでもダメならオフライン問題バンクから出題します。"
)

if st.button("AIで問題を作る", type="primary", key="btn_new"):
    start_online_or_offline(selected_model)
    st.rerun()

# 出題表示
q = st.session_state.question
if q:
    # 出題元ラベル
    if st.session_state.mode == "online":
        label = f"出題元：オンライン（{st.session_state.model_name or 'Gemini'}）"
        st.markdown(f"🛰 **{label}**")
    else:
        st.markdown("📚 **出題元：オフライン（問題バンク）**")

    st.subheader("出題")
    st.write(q["question"])

    # 選択肢
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
        st.rerun()

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
        st.rerun()

# フッタ
with st.expander("使い方"):
    st.markdown(
        "1. 上で Gemini モデルを選択（APIキーがある場合のみ有効）\n"
        "2. **AIで問題を作る** → まずオンライン出題を試み、ダメならオフライン問題バンクへ切替\n"
        "3. 回答すると、結果と全ての選択肢の解説が表示されます\n"
        "4. **もう一問出す** で次の問題へ\n\n"
        "- オフライン問題は `bank/question_bank.jsonl` から読み込みます。\n"
        "- 使用量メーターは、このアプリからオンライン出題を試みた回数の“目安カウンター”です。"
    )

if st.session_state.mode == "online":
    st.caption(f"現在：オンライン出題（{st.session_state.model_name or 'Gemini'}）")
elif st.session_state.mode == "offline":
    st.caption("現在：オフライン出題（問題バンク）")
else:
    st.caption("現在：未出題")
