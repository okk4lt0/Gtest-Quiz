# tools/auto_refill.py
# 目的: 毎日 04:00 JST に Gemini で新しい四択問題を自動生成し、
#       bank/question_bank.jsonl に1行1問で追記する（429等でも失敗終了しない）

import os, json, random, re, sys
from datetime import datetime
from pathlib import Path

PDF_PATH = Path("data/JDLA_Gtest_Syllabus_2024_v1.3_JP.pdf")
BANK_DIR = Path("bank")
BANK_FILE = BANK_DIR / "question_bank.jsonl"

NUM_QUESTIONS = int(os.getenv("NUM_QUESTIONS", "1"))      # ←負荷を下げる
MODEL_NAME    = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")  # ←軽めに寄せる

def safe_print(msg): print(msg, flush=True)

def ensure_files():
    BANK_DIR.mkdir(parents=True, exist_ok=True)
    if not BANK_FILE.exists():
        BANK_FILE.write_text("", encoding="utf-8")

def append_jsonl(obj: dict):
    with BANK_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")

def gen_question(prompt: str) -> dict | None:
    """429 を含む各種エラーは None 返し（= 落とさない）"""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        safe_print("[info] GEMINI_API_KEY missing; skip online.")
        return None
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(MODEL_NAME)
        resp = model.generate_content(
            prompt,
            generation_config={
                "response_mime_type": "application/json",
                "temperature": 0.2,        # 落ち着いた出力
                "max_output_tokens": 400,  # 負荷を下げる
            },
        )
        text = getattr(resp, "text", "") or ""
    except Exception as e:
        # 429/Rate/Quota などはここに来る。落とさない。
        safe_print(f"[info] generate_content failed: {e}")
        return None

    # JSON抽出（```json ... ``` を剥がす）
    if text.startswith("```"):
        text = text.strip("`")
        text = text.replace("json\n", "").replace("json\r\n", "")
    m = re.search(r"\{.*\}", text, flags=re.S)
    jtxt = m.group(0) if m else text
    try:
        obj = json.loads(jtxt)
    except Exception:
        return None

    # 最低限の妥当性
    choices = obj.get("choices")
    if isinstance(choices, list) and len(choices) == 4:
        choices = {k: v for k, v in zip(["A","B","C","D"], choices)}
        obj["choices"] = choices
    if not isinstance(obj.get("choices"), dict) or len(obj["choices"]) != 4:
        return None
    ans = obj.get("correct") or obj.get("answer")
    if ans not in ["A","B","C","D"]: return None
    if not obj.get("question"): return None

    obj["correct"] = ans
    obj["created_at"] = datetime.utcnow().isoformat()+"Z"
    obj.setdefault("source", "gemini-auto")
    obj.setdefault("explanations", {})
    return obj

SYSTEM = (
    "あなたはG検定対策の作問者です。四択問題を1問だけ日本語で作成。"
    "選択肢はA〜Dで正解は1つ。各選択肢に1文の解説を付ける。"
    "出力は必ずJSON（question, choices{A..D}, correct, explanations{A..D}）。"
)

def make_prompt():
    # 現時点はPDF未使用。短い固定指示＋一般的テーマで負荷を抑えて1問生成。
    themes = ["教師あり/なし学習", "過学習と正則化", "損失関数", "評価指標", "強化学習の基本", "バイアス/バリアンス"]
    topic = random.choice(themes)
    return SYSTEM + f"\nテーマ: {topic}\n"

def main():
    ensure_files()

    added = 0
    trials = 0
    max_trials = NUM_QUESTIONS * 4  # リトライ幅

    while added < NUM_QUESTIONS and trials < max_trials:
        trials += 1
        obj = gen_question(make_prompt())
        if not obj:
            continue
        append_jsonl(obj)
        added += 1

    safe_print(f"[done] auto_refill: added={added}, trials={trials}, file={BANK_FILE}")
    # 追加0でも exit 0（ワークフローは失敗にしない）
    sys.exit(0)

if __name__ == "__main__":
    main()
