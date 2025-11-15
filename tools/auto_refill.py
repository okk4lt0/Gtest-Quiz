"""
tools/auto_refill.py
===========================

GitHub Actions (.github/workflows/auto_refill.yml) から起動され、
bank/question_bank.jsonl に自動的に問題を追加するスクリプト。

主な役割:
- bank/meta.json を読み込む (MetaManager)
- question_bank.jsonl を読み込む (QuestionBank)
- 出題の少ない章を優先して、Google Gemini に問題生成を依頼
- 生成された問題を JSONL 形式で追記
- meta.json の usage / chapter_stats / quota_estimate を更新

前提:
- 環境変数 GEMINI_API_KEY に Google Gemini API キーが設定されている
- pip で `google-generativeai` がインストールされていること
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import google.generativeai as genai

from gtest_quiz.meta import MetaManager
from gtest_quiz.models import Question
from gtest_quiz.question_bank import (
    load_question_bank,
    get_all_questions,
)
from gtest_quiz.syllabus import TECH_DOMAIN_LABEL, LAW_DOMAIN_LABEL  # 仮: 必要なら調整
from gtest_quiz.quota import QuotaManager


BANK_PATH = Path("bank/question_bank.jsonl")


# -------------------------------------------------------------
#  Gemini 初期化
# -------------------------------------------------------------
def init_gemini() -> None:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("環境変数 GEMINI_API_KEY が設定されていません。")
    genai.configure(api_key=api_key)


def list_available_models() -> List[str]:
    """
    利用可能なテキスト生成モデルの一覧を取得する。
    より新しいモデルを優先するため、名前でソートして返す。
    """
    models = genai.list_models()
    names: List[str] = []
    for m in models:
        # text / chat が可能なものに絞る
        if "generateContent" in getattr(m, "supported_generation_methods", []):
            names.append(m.name)
    # 新しい model 名ほど後半に来ることが多いので逆順ソート
    names = sorted(names, reverse=True)
    return names


def choose_model_with_fallback(preferred_model: Optional[str] = None) -> str:
    """
    利用可能なモデルの中から、優先度付きで 1 つ選ぶ。

    - preferred_model が指定されていて利用可能ならそれ
    - そうでなければ、一覧の先頭 (最も新しいとみなすもの)
    """
    available = list_available_models()
    if not available:
        raise RuntimeError("利用可能な Gemini モデルが見つかりません。")

    if preferred_model and preferred_model in available:
        return preferred_model
    return available[0]


# -------------------------------------------------------------
#  章ラベルから domain / chapter_group を推定
# -------------------------------------------------------------
def infer_domain_and_group(meta: Dict[str, Any], chapter_label: str) -> Dict[str, str]:
    """
    meta["chapters"] から、chapter_label に対応する大分類ラベルを探し、
    domain (技術分野 / 法律・倫理分野) と chapter_group (大分類ラベル) を返す。

    domain は、章キーのプレフィックス 01〜08 を 技術分野、
    09〜10 を 法律・倫理分野 として扱う。
    """
    chapters = meta.get("chapters", {})
    for group_key, group_val in chapters.items():
        sub = group_val.get("subchapters", {})
        for _sub_key, sub_val in sub.items():
            if sub_val.get("label") == chapter_label:
                group_label = group_val.get("label", "")
                # group_key から domain を推定
                if str(group_key).startswith(("09_", "10_")):
                    domain = LAW_DOMAIN_LABEL
                else:
                    domain = TECH_DOMAIN_LABEL
                return {"domain": domain, "chapter_group": group_label}

    # 見つからない場合のフォールバック
    return {"domain": TECH_DOMAIN_LABEL, "chapter_group": "不明な章"}


# -------------------------------------------------------------
#  question_id の生成
# -------------------------------------------------------------
def generate_question_id(chapter_label: str, existing_ids: List[str]) -> str:
    """
    question_bank.jsonl 内の既存 ID を踏まえつつ、
    衝突しないシンプルな ID を生成する。

    形式:
        Q_AUTO_<yyyymmddHHMMss>_<seq>
    """
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    base = f"Q_AUTO_{ts}"
    seq = 1
    id_set = set(existing_ids)
    while True:
        qid = f"{base}_{seq:02d}"
        if qid not in id_set:
            return qid
        seq += 1


# -------------------------------------------------------------
#  Gemini へ与えるプロンプト
# -------------------------------------------------------------
def build_prompt(chapter_label: str, chapter_group: str) -> str:
    """
    指定したシラバス中項目 (chapter_label) に対応する
    G検定レベルの四択問題を 1問生成するためのプロンプト。
    """
    return f"""
あなたは日本語で G検定(JDLA Deep Learning for GENERAL) の高品質な四択問題を作る専門家です。

以下の制約を厳密に守って、指定されたシラバス項目に対応する四択問題を 1 問だけ生成してください。

# シラバス情報
- 分野: {chapter_group}
- 中項目: {chapter_label}

# 出力条件
- G検定本試験レベルの知識を問う。
- 純粋な知識問題・概念理解問題・応用イメージ問題をバランス良く含める。
- 選択肢は必ず 4 つ。紛らわしいが、1つだけ明確に正しい選択肢を含める。
- 難易度は basic / standard / advanced のいずれかを、内容に応じて自分で決める。

# 出力フォーマット (JSON 1オブジェクトのみ)
以下のキーを含む JSON オブジェクトとして出力してください:

{{
  "question": "問題文（文末に「どれか。」などを含めてもよい）",
  "choices": ["選択肢1", "選択肢2", "選択肢3", "選択肢4"],
  "correct_index": 0,
  "explanation": "なぜこれが正しく、他が誤りかを丁寧に解説する。",
  "difficulty": "basic|standard|advanced"
}}

絶対に JSON 以外の文字列は出力しないでください。
"""


# -------------------------------------------------------------
#  1問生成 → Question への変換
# -------------------------------------------------------------
def generate_one_question(
    model_name: str,
    chapter_label: str,
    chapter_group: str,
    meta_dict: Dict[str, Any],
    quota: QuotaManager,
) -> Optional[Question]:
    """
    指定した章について問題を 1 問生成し、Question オブジェクトとして返す。
    失敗した場合は None。
    """
    prompt = build_prompt(chapter_label, chapter_group)

    # 概算トークン数 (非常に大雑把で良い)
    approx_prompt_tokens = len(prompt) // 2

    try:
        model = genai.GenerativeModel(model_name)
        response = model.generate_content(prompt)
        text = response.text.strip() if hasattr(response, "text") else ""

        # 出力が JSON である前提
        data = json.loads(text)
    except Exception as e:
        # 429 らしき場合のみクォータ推定を更新
        msg = str(e)
        if "429" in msg or "Resource exhausted" in msg:
            quota.register_429(message=msg)
        else:
            quota.register_error(message=msg)
        return None

    # 概算で usage に加算
    approx_output_tokens = len(text) // 2
    quota.add_usage(approx_prompt_tokens + approx_output_tokens)

    # meta から domain / chapter_group を決定
    info = infer_domain_and_group(meta_dict, chapter_label)
    domain = info["domain"]
    chapter_group_resolved = info["chapter_group"]

    # ID を生成
    existing_ids = list(load_question_bank().keys())
    qid = generate_question_id(chapter_label, existing_ids)

    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # JSON から Question へマッピング
    jq: Dict[str, Any] = {
        "id": qid,
        "source": "auto_refill",
        "created_at": created_at,
        "domain": domain,
        "chapter_group": chapter_group_resolved,
        "chapter_id": chapter_label,
        "difficulty": data.get("difficulty", "standard"),
        "question": data.get("question", "").strip(),
        "choices": data.get("choices", []),
        "correct_index": int(data.get("correct_index", 0)),
        "explanation": data.get("explanation", "").strip(),
        "syllabus": "G2024_v1.3",
    }

    # 最低限のバリデーション
    if (
        not jq["question"]
        or not isinstance(jq["choices"], list)
        or len(jq["choices"]) != 4
    ):
        return None

    return Question.from_dict(jq)


# -------------------------------------------------------------
#  メイン処理
# -------------------------------------------------------------
def refill_questions(
    count: int,
    preferred_model: Optional[str] = None,
    dry_run: bool = False,
) -> None:
    """
    問題を count 問生成してバンクに追加する。

    - 偏りを減らすため、MetaManager.choose_next_chapter を用いて
      出題回数の少ない章から優先的に出題
    - dry_run=True の場合、生成内容を標準出力に表示するだけで
      question_bank.jsonl には書き込まない
    """
    # 初期化
    mm = MetaManager()
    mm.load()
    quota = mm.get_quota_manager()

    all_questions = get_all_questions()
    available_chapters = sorted({q.chapter_id for q in all_questions})

    if not available_chapters:
        raise RuntimeError("question_bank.jsonl に既存の問題が存在しません。")

    model_name = choose_model_with_fallback(preferred_model)

    new_questions: List[Question] = []

    for _ in range(count):
        chapter_id = mm.choose_next_chapter(available_chapter_ids=available_chapters)
        if chapter_id is None:
            break

        info = infer_domain_and_group(mm.meta, chapter_id)
        chapter_group = info["chapter_group"]

        q = generate_one_question(
            model_name=model_name,
            chapter_label=chapter_id,
            chapter_group=chapter_group,
            meta_dict=mm.meta,
            quota=quota,
        )
        if q is None:
            continue

        new_questions.append(q)
        # usage 更新（オンライン問題としてカウント）
        mm.record_usage(chapter_id=q.chapter_id, source="online")

    # 追記 or dry-run
    if not new_questions:
        print("新規問題は生成されませんでした。")
    elif dry_run:
        print(f"[DRY RUN] {len(new_questions)}問生成:")
        for q in new_questions:
            print(json.dumps(q.to_dict(), ensure_ascii=False))
    else:
        BANK_PATH.parent.mkdir(parents=True, exist_ok=True)
        with BANK_PATH.open("a", encoding="utf-8") as f:
            for q in new_questions:
                f.write(json.dumps(q.to_dict(), ensure_ascii=False))
                f.write("\n")
        print(f"{len(new_questions)}問を {BANK_PATH} に追記しました。")

    # meta 保存
    mm.save()


# -------------------------------------------------------------
#  CLI エントリーポイント
# -------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="G検定クイズ用 question_bank 自動補充スクリプト",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=5,
        help="生成する問題数（デフォルト: 5）",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="優先的に使いたい Gemini モデル名（任意）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="問題バンクには書き込まず、生成結果のみ標準出力に表示する",
    )
    args = parser.parse_args()

    init_gemini()
    refill_questions(
        count=args.count,
        preferred_model=args.model,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
