import json
import os
from datetime import datetime
from typing import Dict, Any


META_PATH = os.path.join(os.path.dirname(__file__), "..", "bank", "meta.json")


def load_meta() -> Dict[str, Any]:
    """Load meta.json. If missing keys exist, initialize them safely."""
    if not os.path.exists(META_PATH):
        return {
            "last_chapter_id": None,
            "chapter_stats": {},
            "chapters": {},
        }

    with open(META_PATH, "r", encoding="utf-8") as f:
        meta = json.load(f)

    # Safety initialization
    meta.setdefault("last_chapter_id", None)
    meta.setdefault("chapter_stats", {})
    meta.setdefault("chapter_timestamps", {})  # 新しく追加（必要）

    return meta


def save_meta(meta: Dict[str, Any]) -> None:
    """Write updated meta.json with pretty formatting."""
    with open(META_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def extract_chapter_id(question: Dict[str, Any]) -> str:
    """
    Extract the chapter ID directly from question["chapter_id"].
    e.g., "1. 人工知能の定義" → "01_01_人工知能の定義"
    
    ※ question_bank.jsonl の `chapter_id` が "1. ..."" なので、
       "NN_NN_..." にマッピングするルールを定義する必要がある。
       ここでは、meta.json のキーを直接検索してマッピングする。
    """
    raw = question["chapter_id"].split(".", 1)[1].strip()  # 「人工知能の定義」

    # meta.json の chapters 構造から検索する
    meta = load_meta()

    for major_key, major_val in meta["chapters"].items():
        for sub_key, sub_val in major_val["subchapters"].items():
            if sub_val["label"].endswith(raw):
                return sub_key

    # 見つからない場合 → raw を返す（フォールバック）
    return raw


def update_chapter_stats(question: Dict[str, Any]) -> None:
    """出題後に章の出題回数と時刻を更新する。"""
    meta = load_meta()
    chapter_id = extract_chapter_id(question)

    # 出題回数をカウント
    if chapter_id not in meta["chapter_stats"]:
        meta["chapter_stats"][chapter_id] = 0
    meta["chapter_stats"][chapter_id] += 1

    # 出題時刻も記録
    now = datetime.utcnow().isoformat()
    meta["chapter_timestamps"][chapter_id] = now

    # 最後に出題した章
    meta["last_chapter_id"] = chapter_id

    save_meta(meta)


def pick_chapter_with_min_usage() -> str:
    """
    出題すべき章を、chapter_stats が最小の章から選ぶ。
    章ツリー (meta["chapters"]) から全章を抽出し、
    出題回数が最も少ないものを返す。
    """
    meta = load_meta()

    # 全 subchapter の key をメタから抽出
    all_chapters = []
    for major_key, major_val in meta["chapters"].items():
        for sub_key in major_val["subchapters"].keys():
            all_chapters.append(sub_key)

    # stats が無い章は 0 として扱う
    usage = {
        chapter: meta["chapter_stats"].get(chapter, 0)
        for chapter in all_chapters
    }

    # 最低出題数の章を選ぶ
    return min(usage, key=usage.get)


def pick_question_balanced(questions: list[Dict[str, Any]]) -> Dict[str, Any]:
    """
    chapter_stats を使い、最も未出題の章から問題を選ぶ。
    """
    target_chapter = pick_chapter_with_min_usage()

    # その章の問題だけを抽出
    filtered = [
        q for q in questions
        if extract_chapter_id(q) == target_chapter
    ]

    # 必ず1問以上ある前提で random 不要（最初の1問で十分）
    question = filtered[0]

    # メタ情報を更新
    update_chapter_stats(question)

    return question
