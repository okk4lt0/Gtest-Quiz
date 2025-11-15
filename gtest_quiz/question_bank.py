"""
question_bank.py
======================

オフライン問題（JSONL）の読み込みと出題管理。

要件:
- JSONL（1行＝1問）形式の安全な読み込み
- 壊れた行は読み飛ばしつつログに残す（クラッシュ禁止）
- 章ごとの問題分布を保持し、偏りを抑える
- chapter_id ベースで検索できる
- ランダム出題にも対応
"""

from __future__ import annotations
import json
import random
from pathlib import Path
from typing import List, Dict, Any, Optional


class QuestionBank:
    """
    ローカルの JSONL 問題バンクを管理するクラス。
    """

    def __init__(self, filepath: str):
        self.filepath = Path(filepath)
        self.questions: List[Dict[str, Any]] = []
        self.by_chapter: Dict[str, List[Dict[str, Any]]] = {}
        self._loaded = False

    # ----------------------------------------------------------------------
    # JSONL を読み込む
    # ----------------------------------------------------------------------
    def load(self) -> None:
        """JSONL を読み込む。壊れた行は安全にスキップする。"""
        if not self.filepath.exists():
            self.questions = []
            self.by_chapter = {}
            self._loaded = True
            return

        questions = []
        by_chapter = {}

        with self.filepath.open("r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue

                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    # 壊れた行はスキップ（クラッシュ防止）
                    print(f"[WARN] JSON decode error at line {line_no}: {line[:50]}")
                    continue

                # chapter_id が必須
                chap = obj.get("chapter_id")
                if not chap:
                    print(f"[WARN] No chapter_id at line {line_no}")
                    continue

                questions.append(obj)

                if chap not in by_chapter:
                    by_chapter[chap] = []
                by_chapter[chap].append(obj)

        self.questions = questions
        self.by_chapter = by_chapter
        self._loaded = True

    # ----------------------------------------------------------------------
    # 章から問題を 1 題取得
    # ----------------------------------------------------------------------
    def pick_by_chapter(self, chapter_id: str) -> Optional[Dict[str, Any]]:
        """chapter_id の中からランダムに 1 題返す"""
        if not self._loaded:
            self.load()

        if chapter_id not in self.by_chapter:
            return None

        return random.choice(self.by_chapter[chapter_id])

    # ----------------------------------------------------------------------
    # ランダム出題（全体から）
    # ----------------------------------------------------------------------
    def pick_random(self) -> Optional[Dict[str, Any]]:
        """全問題からランダムに出題"""
        if not self._loaded:
            self.load()

        if not self.questions:
            return None

        return random.choice(self.questions)

    # ----------------------------------------------------------------------
    # 指定章リストから優先的に一つ返す
    # meta 偏り制御から呼ばれる
    # ----------------------------------------------------------------------
    def pick_from_candidates(self, candidate_chapters: List[str]) -> Optional[Dict[str, Any]]:
        """
        meta で決めた候補章リストから問題を取得する。
        どの章にも問題が無い場合は None。
        """
        if not self._loaded:
            self.load()

        pool = []
        for chap in candidate_chapters:
            if chap in self.by_chapter:
                pool.extend(self.by_chapter[chap])

        if not pool:
            return None

        return random.choice(pool)

    # ----------------------------------------------------------------------
    # 問題総数
    # ----------------------------------------------------------------------
    def count(self) -> int:
        if not self._loaded:
            self.load()
        return len(self.questions)
