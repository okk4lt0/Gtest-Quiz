"""
meta.py
=======

出題履歴（meta.json）を扱うモジュール。
- 前回出題した章の回避
- 章ごとの出題回数の偏り調整
- 最近出題していない章の優遇
- メタデータの読み書き

question_bank.jsonl と syllabus.py の chapter_id を基準に
常に整合の取れた出題バランスを提供する。
"""

import json
import os
import time
from typing import Dict, List, Optional

from .syllabus import get_all_chapter_ids


META_FILE_PATH = "meta.json"


# ============================================================
# メタ情報の読み書き
# ============================================================

def load_meta() -> Dict:
    """meta.json を読み込む。存在しなければ初期状態を返す。"""
    if not os.path.exists(META_FILE_PATH):
        return {
            "last_chapter_id": None,
            "chapter_counts": {},
            "chapter_timestamps": {},
        }

    with open(META_FILE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_meta(meta: Dict):
    """meta.json を保存する。"""
    with open(META_FILE_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


# ============================================================
# バランス計算
# ============================================================

def select_next_chapter_id(meta: Dict) -> str:
    """
    出題バランスに基づき次の chapter_id を選択する。

    アルゴリズムの優先順位:
    1. 直前と同じ章は可能な限り避ける
    2. 出題回数（chapter_counts）が少ない章を優先
    3. 出題日時（chapter_timestamps）が古い章を優先
    """

    all_chapters = get_all_chapter_ids()

    chapter_counts = meta.get("chapter_counts", {})
    chapter_timestamps = meta.get("chapter_timestamps", {})
    last_chapter = meta.get("last_chapter_id")

    # 未登場の章は強く優先するため大幅に減点
    MINUS_INF = -1_000_000

    scored = []

    for chapter in all_chapters:
        count = chapter_counts.get(chapter, 0)
        last_ts = chapter_timestamps.get(chapter, 0)

        # 出題回数の少なさを重視（最小化）
        score = count * 10

        # 最近出題していないほど優遇（timestamp が小さい → 優遇）
        # 時間差を軽くスコア調整
        score += int(time.time() - last_ts) * -0.0001

        # 初登場は優遇
        if chapter not in chapter_counts:
            score += MINUS_INF

        # 直前章は重いペナルティ
        if chapter == last_chapter:
            score += 500

        scored.append((score, chapter))

    # 最小スコアが最優先
    scored.sort(key=lambda x: x[0])
    return scored[0][1]


# ============================================================
# メタ情報の更新
# ============================================================

def update_meta_after_question(meta: Dict, chapter_id: str):
    """
    question 出題後に chapter_id に応じて meta を更新する。
    - 出題回数
    - 最終出題タイムスタンプ
    - 最後に出題した章
    """

    now = time.time()

    # chapter_counts 更新
    meta.setdefault("chapter_counts", {})
    meta["chapter_counts"][chapter_id] = meta["chapter_counts"].get(chapter_id, 0) + 1

    # timestamp 更新
    meta.setdefault("chapter_timestamps", {})
    meta["chapter_timestamps"][chapter_id] = now

    # 最後の章
    meta["last_chapter_id"] = chapter_id

    save_meta(meta)
