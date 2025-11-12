# tools/auto_refill.py
# 目的: 毎日 04:00 JST に Gemini で新しい四択問題を自動生成し、
#       bank/question_bank.jsonl に1行1問で追記する。
# 前提:
#  - data/JDLA_Gtest_Syllabus_2024_v1.3_JP.pdf が存在
#  - 環境変数 GEMINI_API_KEY が設定済み（GitHub Actions の Repository secret）
#  - google-generativeai と pypdf がインストールされている

import os
import json
import random
from datetime import datetime
from pathlib import Path

import google.generativeai as genai
from pypdf import PdfReader

# ===== 設定 =====
PDF_PATH = Path("data") / "JDLA_Gtest_Syllabus_2024_v1.3_JP.pdf"
BANK_DIR = Path("bank")
BANK_FILE = BANK_DIR / "question_bank.jsonl"
NUM_QUESTIONS = int(os.getenv("NUM_QUESTIONS", "3"))  # 1回の補充で何問作るか（デフォ3）
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")  # 無料枠で動きやすい実績
SEED = int(os.getenv("SEED", "42"))

random.seed(SEED)

def load_pdf_text(pdf_path: Path, max_pages: int = 30) -> str:
    """PDF の冒頭から max_pages ページ分を軽量抽出（全文は長すぎるので切る）"""
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    reader = PdfReader(str(pdf_path))
    pages = min(len(reader.pages), max_pages)
    chunks = []
    for i in range(pages):
        try:
            chunks.append(reader.pages[i].extract_text() or "")
        except Exception:
            pass
    text = "\n".join(chunks)
    # さらに長すぎる場合はカット
    return text[:20000]

def ensure_files():
    BANK_DIR.mkdir(parents=True, exist_ok=True)
    if not BANK_FILE.exists():
        BANK_FILE.write_text("", encoding="utf-8")

def existing_questions_set() -> set:
    """重複防止用に既存の設問文集合を返す"""
    s = set()
    if BANK_FILE.exists():
        with BANK_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    q = (obj.get("question") or "").strip()
                    if q:
                        s.add(q)
                except Exception:
                    continue
    return s

SYSTEM_INSTRUCTIONS = """あなたは日本語のG検定対策作問エンジンです。
以下の「シラバス抜粋」を根拠に、厳密で短めの四択単一正解の設問を1問だけ生成してください。
出題範囲はG検定一般レベル。設問は1〜2文、選択肢はA〜Dで内容が重複しないように。
解説は正答の理由を1〜2文。出力は必ず JSON のみ:
{
  "question": "問題文",
  "choices": ["A", "B", "C", "D"],
  "answer": "A|B|C|D のどれか",
  "explanations": {
    "A": "Aの短い解説（正誤含む）",
    "B": "...",
    "C": "...",
    "D": "..."
  },
  "source": "JDLA Gtest Syllabus 2024 v1.3"
}
"""

def build_prompt(syllabus_snippets: list[str]) -> str:
    # ランダムに3片ほど繋ぐ
    picked = random.sample(syllabus_snippets, k=min(3, len(syllabus_snippets)))
    body = "\n---\n".join(picked)
    return f"【シラバス抜粋】\n{body}\n\n上記のみを根拠に作問してください。"

def split_into_snippets(text: str, chunk_size: int = 1000, overlap: int = 120) -> list[str]:
    """テキストを少し重ねながら分割して、話題の整合性を上げる"""
    snippets = []
    i = 0
    n = len(text)
    while i < n:
        j = min(i + chunk_size, n)
        snippets.append(text[i:j])
        if j >= n:
            break
        i = j - overlap
    # ノイズっぽい短すぎる片は捨てる
    return [s.strip() for s in snippets if len(s.strip()) > 200]

def call_gemini(model_name: str, prompt: str) -> dict | None:
    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
    model = genai.GenerativeModel(model_name)
    resp = model.generate_content(
        SYSTEM_INSTRUCTIONS + "\n\n" + prompt,
        generation_config={
            "temperature": 0.3,
            "response_mime_type": "application/json",
        },
    )
    text = (resp.text or "").strip()
    if not text:
        return None
    # まれに ```json ブロックで返るので剥がす
    if text.startswith("```"):
        text = text.strip("`")
        # 先頭にjsonと書かれていることがある
        text = text.replace("json\n", "").replace("json\r\n", "")
    try:
        obj = json.loads(text)
    except Exception:
        return None

    # 最低限のスキーマ検証
    if not isinstance(obj.get("choices"), list) or len(obj["choices"]) != 4:
        return None
    if obj.get("answer") not in ["A", "B", "C", "D"]:
        return None
    if not obj.get("question"):
        return None
    # 追記用メタ
    obj["created_at"] = datetime.utcnow().isoformat() + "Z"
    obj["source"] = obj.get("source") or "JDLA Gtest Syllabus 2024 v1.3"
    return obj

def append_jsonl(obj: dict):
    with BANK_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")

def main():
    ensure_files()
    text = load_pdf_text(PDF_PATH)
    snippets = split_into_snippets(text)
    if not snippets:
        raise RuntimeError("シラバスのテキスト抽出に失敗しました。")

    already = existing_questions_set()
    added = 0
    trials = 0
    max_trials = NUM_QUESTIONS * 4  # 重複や失敗を見込んで余裕をもって叩く

    while added < NUM_QUESTIONS and trials < max_trials:
        trials += 1
        prompt = build_prompt(snippets)
        obj = call_gemini(MODEL_NAME, prompt)
        if not obj:
            continue
        q = obj["question"].strip()
        if q in already:
            continue
        append_jsonl(obj)
        already.add(q)
        added += 1

    print(f"auto_refill: added={added}, trials={trials}, bank={BANK_FILE}")

if __name__ == "__main__":
    main()
