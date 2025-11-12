# app.py
# G検定クイズアプリ（オンライン=Gemini / オフライン=問題バンク）
# 依存: streamlit, google-generativeai, requests
import os
import json
import random
from pathlib import Path
import streamlit as st

# ====== 基本設定 ======
st.set_page_config(page_title="G検定クイズアプリ", page_icon="🧠", layout="centered")

APP_DIR = Path(__file__).parent
DATA_DIR = APP_DIR / "data"
BANK_DIR = APP_DIR / "problem_bank"
BANK_FILE = BANK_DIR / "question_bank.jsonl"  # 1行1問のJSON Lines

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
                    # 壊れた行は無視
                    continue
    return items

def load_offline_bank():
    bank = read_jsonl(BANK_FILE)
    if bank:
        return bank

    # バンクが空でも最低限のデフォルト問題（オフライン）
    return [
        {
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
                "D": "特定タスクの一例で学習設定そのものではありません。"
            }
        }
    ]

def ensure_state():
    if "question" not in st.session_state:
        st.session_state.question = None   # 現在の出題データ(dict)
    if "picked" not in st.session_state:
        st.session_state.picked = None     # ユーザー選択（"A"〜"D"）
    if "result" not in st.session_state:
        st.session_state.result = None     # {"is_correct": bool, "reason": "..."}
    if "mode" not in st.session_state:
        st.session_state.mode = None       # "online" or "offline"
    if "model_name" not in st.session_state:
        st.session_state.model_name = None # 実際に使ったモデル名（オンライン時）

ensure_state()

# ====== Gemini オンライン出題 ======
def get_gemini_api_key():
    # Streamlit Cloud の「Secrets」に GCP の Gemini API キーを入れておく想定
    # キー名: GEMINI_API_KEY
    try:
        return st.secrets["GEMINI_API_KEY"]
    except Exception:
        return os.getenv("GEMINI_API_KEY")  # 念のため環境変数でも拾う

@st.cache_data(show_spinner=False, ttl=900)
def list_available_models(api_key: str):
    """生成に使えるモデル（generateContent対応）を列挙。"""
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    models = []
    try:
        for m in genai.list_models():
            # v0.8.x は supported_generation_methods を持つ
            methods = getattr(m, "supported_generation_methods", []) or []
            if "generateContent" in methods:
                models.append(m.name)
    except Exception:
        # 取得失敗時は代表的な動作確認済みモデルにフォールバック
        models = [
            "gemini-2.0-flash",
            "gemini-2.0-flash-001",
            "gemini-2.0-flash-lite",
        ]
    return sorted(models)

def generate_with_gemini(model_name: str):
    """Geminiで四択問題をJSONで生成。成功すれば dict を返し、失敗時は例外を投げる。"""
    api_key = get_gemini_api_key()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY が設定されていません。")

    import google.generativeai as genai
    genai.configure(api_key=api_key)

    # PDFは今は読み取らず（モバイル運用を優先）。後で前処理辞書化する前提。
    # ここでは一般的なG検定範囲の基礎問題をモデルに作らせる。
    sys_prompt = (
        "あなたはG検定対策の問題作成者です。"
        "四択問題を1問だけ日本語で作成してください。"
        "選択肢はA〜Dの4つ。正答は1つだけ。"
        "各選択肢に短い解説も用意してください。"
        "内容は一般的な機械学習/ディープラーニング/統計/倫理から基本的な範囲。"
    )

    # JSONで返すように強制
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
                "D": "選択肢D"
            },
            "correct": "A|B|C|D のいずれか1つ",
            "explanations": {
                "A": "Aの解説（1文）",
                "B": "Bの解説（1文）",
                "C": "Cの解説（1文）",
                "D": "Dの解説（1文）"
            }
        }
    }

    model = genai.GenerativeModel(model_name, generation_config=generation_config)
    resp = model.generate_content(
        [
            {"role": "user", "parts": [json.dumps(prompt, ensure_ascii=False)]}
        ]
    )

    # レスポンス取得（v0.8.x）
    text = ""
    try:
        text = resp.candidates[0].content.parts[0].text
    except Exception:
        text = getattr(resp, "text", "")

    data = json.loads(text)

    # 最低限のバリデーション
    req_keys = {"question", "choices", "correct", "explanations"}
    if not req_keys.issubset(set(data.keys())):
        raise ValueError("JSONに必要なキーが足りません。")

    # 形をそろえる
    q = {
        "source": "online",
        "question": data["question"],
        "choices": data["choices"],
        "correct": data["correct"],
        "explanations": data["explanations"],
    }
    return q

# ====== 出題フロー ======
def start_online_or_offline(model_choice: str):
    """オンライン試行→失敗ならオフライン"""
    # まず既存状態をリセット（ただし直前の問題は画面に残したいので別キーに退避しない）
    st.session_state.result = None
    st.session_state.picked = None
    st.session_state.model_name = None

    # オンライン試行
    try:
        q = generate_with_gemini(model_choice)
        st.session_state.question = q
        st.session_state.mode = "online"
        st.session_state.model_name = model_choice
        st.success("オンライン（Gemini）で問題を生成しました。")
        return
    except Exception as e:
        # よくある 429 / 無償枠0 / キー未設定 などはここに来る
        st.info("Geminiが使えないため、オフライン問題に切り替えます。")
        # print(str(e))  # 必要ならログ

    # オフライン
    bank = load_offline_bank()
    st.session_state.question = random.choice(bank)
    st.session_state.mode = "offline"
    st.session_state.model_name = None

def grade(picked: str):
    q = st.session_state.question
    is_correct = (picked == q["correct"])
    # 結果保持（ページ遷移/再実行でも残す）
    st.session_state.result = {
        "is_correct": is_correct,
        "picked": picked,
        "correct": q["correct"]
    }

# ====== UI ======
st.title("G検定クイズアプリ（Gemini/オフライン対応）")

# モデル選択（APIキーがある場合のみ取得）
models = []
api_key_present = bool(get_gemini_api_key())
if api_key_present:
    models = list_available_models(get_gemini_api_key())

selected_model = st.selectbox(
    "使用モデルを選択（Geminiが使える時のみ有効）",
    options=models if models else ["gemini-2.0-flash"],
    index=0,
    disabled=not api_key_present,
)

st.caption(
    "「AIで問題を作る」を押すと、まず Gemini で問題を生成します。"
    "APIが使えない/クオータ0などの場合は**自動的にオフライン問題**へ切替。"
)

# 出題ボタン
if st.button("AIで問題を作る", type="primary"):
    start_online_or_offline(selected_model)

# ====== 出題表示 ======
q = st.session_state.question
if q:
    st.subheader("出題")
    # 問題文は常に残す
    st.write(q["question"])

    # 選択
    choice_labels = [f"{k}：{v}" for k, v in q["choices"].items()]
    # key を固定して再描画でも選択維持
    picked_label = st.radio(
        "選択肢を選んでください：",
        options=choice_labels,
        index=0 if st.session_state.picked is None else
        list(q["choices"].keys()).index(st.session_state.picked),
        key="picked_label_radio"
    )

    # ラベル → "A"/"B"/"C"/"D" に戻す
    picked_key = picked_label.split("：", 1)[0]
    st.session_state.picked = picked_key

    submit_label = "回答する（オンライン）" if st.session_state.mode == "online" else "回答する（オフライン）"
    if st.button(submit_label):
        grade(st.session_state.picked)

# ====== 結果表示（問題は残したまま下に表示） ======
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

    # もう一問ボタン
    if st.button("もう一問出す"):
        # 次の出題のために結果だけクリア（問題は差し替える）
        st.session_state.result = None
        st.session_state.picked = None
        start_online_or_offline(selected_model)

# ====== フッタ情報 ======
with st.expander("使い方（最短）"):
    st.markdown(
        "1. 上でモデルを選択（APIキーが設定済みのとき）\n"
        "2. **AIで問題を作る** を押す → オンライン生成に挑戦し、ダメならオフライン\n"
        "3. 回答 → 結果と全選択肢の解説を確認\n"
        "4. **もう一問出す** で繰り返し\n\n"
        "- PDF（`data/JDLA_Gtest_Syllabus_2024_v1.3_JP.pdf`）は今は読み込まず、"
        "将来の前処理（章節ごとの要点辞書化）で使う想定です。\n"
        "- オフライン問題は `problem_bank/question_bank.jsonl`（1行1問のJSON）から読み込みます。"
    )

st.caption(
    ("オンライン: " + (st.session_state.model_name or "—"))
    if st.session_state.mode == "online"
    else "オフライン出題中"
)
