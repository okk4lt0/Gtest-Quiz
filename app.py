# app.py
# G検定クイズ（オンライン=Gemini → 失敗時はオフライン）＋ 使用量メーター
# 依存: streamlit, google-generativeai

import os
import json
from pathlib import Path
import random
import time
from datetime import datetime, timedelta, timezone
import streamlit as st

# ===== 基本設定 =====
st.set_page_config(page_title="G検定クイズアプリ", page_icon="🧠", layout="centered")

APP_DIR = Path(__file__).parent
DATA_DIR = APP_DIR / "data"
BANK_DIR = APP_DIR / "bank"                      # 問題バンクの場所
BANK_FILE = BANK_DIR / "question_bank.jsonl"     # 1行1問の JSON Lines

# ===== メーター設定（推定値。必要ならSidebarで変更可能） =====
DEFAULT_DAILY_LIMIT = int(os.getenv("GEMINI_DAILY_LIMIT", "5"))   # Free相当の目安
DEFAULT_RPM_LIMIT   = int(os.getenv("GEMINI_RPM_LIMIT", "2"))     # 1分あたりの目安

METER_FILE = BANK_DIR / "usage_meter.json"  # リクエスト履歴をローカル保存（Streamlit CloudでもGit追跡対象外が望ましい）

JST = timezone(timedelta(hours=9))

# ===== 状態確保 =====
def ensure_state():
    ss = st.session_state
    ss.setdefault("question", None)     # 現在の出題（dict）
    ss.setdefault("picked", None)       # "A"〜"D"
    ss.setdefault("result", None)       # 採点結果
    ss.setdefault("mode", None)         # "online" / "offline"
    ss.setdefault("model_name", None)   # 実際に使ったモデル名
    ss.setdefault("last_error", "")     # 直近のオンライン失敗メッセージ
ensure_state()

# ===== メーターストレージ =====
def load_meter() -> dict:
    """usage_meter.json を読み込み。なければ初期化。"""
    BANK_DIR.mkdir(parents=True, exist_ok=True)
    if METER_FILE.exists():
        try:
            return json.loads(METER_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "tz": "JST",
        "daily_limit": DEFAULT_DAILY_LIMIT,
        "rpm_limit": DEFAULT_RPM_LIMIT,
        "today": datetime.now(JST).strftime("%Y-%m-%d"),
        "calls_today": 0,
        "call_timestamps": [],   # ISO文字列の配列（直近数分）
        "last_429_at": None
    }

def save_meter(m: dict):
    METER_FILE.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")

def reset_if_new_day(m: dict):
    today = datetime.now(JST).strftime("%Y-%m-%d")
    if m.get("today") != today:
        m["today"] = today
        m["calls_today"] = 0
        m["call_timestamps"] = []
        m["last_429_at"] = None

def record_call(m: dict, ok: bool, is_429: bool):
    now = datetime.now(JST)
    # 直近1分の履歴を維持
    cutoff = now - timedelta(minutes=2)
    kept = []
    for t in m.get("call_timestamps", []):
        try:
            dt = datetime.fromisoformat(t)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=JST)
        except Exception:
            continue
        if dt >= cutoff:
            kept.append(dt.astimezone(JST).isoformat())
    kept.append(now.isoformat())
    m["call_timestamps"] = kept

    if ok:
        m["calls_today"] = int(m.get("calls_today", 0)) + 1
    if is_429:
        m["last_429_at"] = now.isoformat()

def rpm_window_info(m: dict):
    """直近60秒での呼び出し数と、次に安全になるまでの目安秒数。"""
    now = datetime.now(JST)
    window_start = now - timedelta(seconds=60)
    cnt = 0
    oldest = None
    for t in m.get("call_timestamps", []):
        try:
            dt = datetime.fromisoformat(t)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=JST)
        except Exception:
            continue
        if dt >= window_start:
            cnt += 1
            if oldest is None or dt < oldest:
                oldest = dt
    cooldown_sec = 0
    if cnt >= int(m.get("rpm_limit", DEFAULT_RPM_LIMIT)) and oldest:
        # 最古の呼び出しから60秒経過するまで
        cooldown_sec = max(0, 60 - int((now - oldest).total_seconds()))
    return cnt, cooldown_sec

def get_daily_progress(m: dict):
    limit = max(1, int(m.get("daily_limit", DEFAULT_DAILY_LIMIT)))
    used = int(m.get("calls_today", 0))
    ratio = min(1.0, used / limit)
    remaining = max(0, limit - used)
    return used, limit, remaining, ratio

# ===== ユーティリティ（問題バンク） =====
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

def generate_with_gemini(model_name: str, meter: dict) -> dict:
    """Geminiで1問生成し内部形式で返す。失敗時は例外を送出。メーター記録込み。"""
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

    # 呼ぶ直前にメーター日付を同期
    reset_if_new_day(meter)
    try:
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

        # 成功記録
        record_call(meter, ok=True, is_429=False)
        save_meter(meter)
        return norm

    except Exception as e:
        # 429などの目印
        is_429 = ("429" in str(e)) or ("Resource exhausted" in str(e)) or ("quota" in str(e).lower()) or ("rate" in str(e).lower())
        record_call(meter, ok=False, is_429=is_429)
        save_meter(meter)
        raise

# ===== 出題・採点 =====
def start_online_or_offline(model_choice: str, meter: dict):
    """まずオンラインに挑戦。失敗ならオフラインへ切替。"""
    st.session_state.result = None
    st.session_state.picked = None
    st.session_state.model_name = None
    st.session_state.last_error = ""

    try:
        q = generate_with_gemini(model_choice, meter)
        st.session_state.question = q
        st.session_state.mode = "online"
        st.session_state.model_name = model_choice
        st.success("オンライン（Gemini）で問題を生成しました。")
        return
    except Exception as e:
        st.session_state.last_error = str(e)
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

# ===== UI: メーター表示 =====
meter = load_meter()
reset_if_new_day(meter)

with st.sidebar:
    st.subheader("使用量メーター")
    # 目安上限はユーザーが調整可能
    c1, c2 = st.columns(2)
    with c1:
        meter["daily_limit"] = st.number_input("1日の目安回数", 1, 1000, int(meter.get("daily_limit", DEFAULT_DAILY_LIMIT)))
    with c2:
        meter["rpm_limit"] = st.number_input("1分の目安回数", 1, 60, int(meter.get("rpm_limit", DEFAULT_RPM_LIMIT)))

    used, limit, remaining, ratio = get_daily_progress(meter)
    st.progress(ratio, text=f"今日の使用: {used}/{limit} （残り {remaining}）")

    cnt_1m, cooldown = rpm_window_info(meter)
    st.caption(f"直近60秒のリクエスト: {cnt_1m}/{meter['rpm_limit']}")

    if meter.get("last_429_at"):
        last429 = datetime.fromisoformat(meter["last_429_at"]).astimezone(JST)
        st.caption(f"最後の429: {last429.strftime('%H:%M:%S')} JST")
    if cooldown > 0:
        st.warning(f"混雑の可能性あり。目安クールダウン: {cooldown} 秒")

    if st.button("メーターを手動リセット"):
        meter["calls_today"] = 0
        meter["call_timestamps"] = []
        meter["last_429_at"] = None
        save_meter(meter)
        st.experimental_rerun()

# ===== メインUI =====
st.title("G検定クイズ（Gemini/オフライン＋メーター）")

api_key = get_gemini_api_key()
models = list_available_models(api_key) if api_key else []
selected_model = st.selectbox(
    "使用モデル（キー未設定時は無効）",
    options=models if models else ["gemini-2.5-flash"],
    index=0,
    disabled=not bool(api_key),
)

st.caption("まず Gemini で生成を試み、失敗時は自動でオフライン問題に切替します。サイドバーに推定メーターを表示しています。")

if st.button("AIで問題を作る", type="primary"):
    start_online_or_offline(selected_model, meter)

q = st.session_state.question
if q:
    st.subheader("出題")
    st.write(q["question"])

    labels = [f"{k}：{v}" for k, v in q["choices"].items()]
    default_idx = 0
    if st.session_state.picked in q["choices"]:
        default_idx = ["A", "B", "C", "D"].index(st.session_state.picked)

    chosen_label = st.radio("選択肢：", options=labels, index=default_idx, key="picked_label_radio")
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
        start_online_or_offline(selected_model, meter)

mode_info = ("オンライン: " + (st.session_state.model_name or "—")) if st.session_state.mode == "online" else "オフライン出題中"
if st.session_state.last_error:
    st.caption(mode_info + f"｜最後のオンラインエラー: {st.session_state.last_error[:80]}…")
else:
    st.caption(mode_info)
