"""
question_bank.py
===========================

JSONL 形式の問題バンクを読み込み、
検索・抽出・ランダム出題のための関数を提供するモジュール。

目的:
- JSONL は巨大化するので、最適化されたロード処理が必要
- 破損行への耐性（壊れている行は skip）
- Question モデルとの型整合性
- 多回ロード時の高速化（ウォームキャッシュ）
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Dict, List, Optional, Iterable

from .models import Question

# ----------------------------------------------------------------------
#  グローバルキャッシュ（Pythonプロセス中は維持される）
# ----------------------------------------------------------------------
_QUESTION_CACHE: Dict[str, Question] = {}
_IS_LOADED = False

# ----------------------------------------------------------------------
#  パス定義
# ----------------------------------------------------------------------
BANK_PATH = Path("bank/question_bank.jsonl")


# ----------------------------------------------------------------------
#  JSONL 読み込み
# ----------------------------------------------------------------------
def load_question_bank(force_reload: bool = False) -> Dict[str, Question]:
    """
    question_bank.jsonl を読み込み、id をキーとする Question 辞書を返す。

    - force_reload=True の場合のみ再読込
    - 壊れた行は安全にスキップ（print などは行わない）
    """
    global _IS_LOADED, _QUESTION_CACHE

    if _IS_LOADED and not force_reload:
        return _QUESTION_CACHE

    if not BANK_PATH.exists():
        raise FileNotFoundError(f"問題バンクが見つかりません: {BANK_PATH}")

    cache: Dict[str, Question] = {}

    with BANK_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            try:
                data = json.loads(line)
                q = Question.from_dict(data)
                cache[q.id] = q
            except Exception:
                # 壊れた行は無視する
                continue

    _QUESTION_CACHE = cache
    _IS_LOADED = True
    return cache


# ----------------------------------------------------------------------
#  単純ヘルパー
# ----------------------------------------------------------------------
def get_all_questions() -> List[Question]:
    """全問題のリスト"""
    return list(load_question_bank().values())


def get_question_by_id(qid: str) -> Optional[Question]:
    """id で 1問取得"""
    return load_question_bank().get(qid)


def get_questions_by_chapter(chapter_id: str) -> List[Question]:
    """章（chapter_id）の完全一致でフィルタ"""
    return [
        q for q in load_question_bank().values()
        if q.chapter_id == chapter_id
    ]


def get_questions_by_group(group_name: str) -> List[Question]:
    """chapter_group でフィルタ（例:「人工知能とは」）"""
    return [
        q for q in load_question_bank().values()
        if q.chapter_group == group_name
    ]


# ----------------------------------------------------------------------
#  ランダム出題（重みなし）
# ----------------------------------------------------------------------
def pick_random_question() -> Question:
    """
    単純にランダムで 1問返す。
    必ず Question を返す。0件なら例外。
    """
    bank = get_all_questions()
    if not bank:
        raise ValueError("問題バンクが空です。")
    return random.choice(bank)


# ----------------------------------------------------------------------
#  ランダム出題（章指定）
# ----------------------------------------------------------------------
def pick_random_from_chapter(chapter_id: str) -> Optional[Question]:
    """
    章内からランダム出題。0件なら None。
    """
    items = get_questions_by_chapter(chapter_id)
    if not items:
        return None
    return random.choice(items)


# ----------------------------------------------------------------------
#  検索：全文検索（最低限）
# ----------------------------------------------------------------------
def search(keyword: str) -> List[Question]:
    """
    問題文・選択肢・章名を対象とする簡易全文検索。

    ※高速検索が必要なら将来 FAISS/SQlite/Elasticsearch を検討。
    """
    keyword = keyword.strip()
    if not keyword:
        return []

    keyword_lower = keyword.lower()

    results = []
    for q in load_question_bank().values():
        t = (
            q.question.lower(),
            " ".join(q.choices).lower(),
            q.chapter_group.lower(),
            q.chapter_id.lower(),
        )
        if any(keyword_lower in part for part in t):
            results.append(q)

    return results
