"""
meta.py
======================

bank/meta.json の読み書きと、
出題バランス制御・使用量カウンタ・クォータ推定をまとめて扱うモジュール。

meta.json の想定構造（抜粋）:

{
  "version": 1,
  "created_at": "1970-01-01T00:00:00Z",
  "updated_at": "1970-01-01T00:00:00Z",
  "usage": {
    "total_questions": 0,
    "online_questions": 0,
    "offline_questions": 0
  },
  "quota_estimate": {
    "total_used_tokens": 0,
    "estimated_limit_tokens": null,
    "last_429_at": null,
    "last_error": null
  },
  "chapter_stats": {
      "1. 人工知能の定義": {
          "total_questions": 10,
          "online_questions": 4,
          "offline_questions": 6
      },
      ...
  },
  "last_chapter_id": "1. 人工知能の定義",
  "chapters": { ... }  # シラバス構造（大分類・中分類）
}

※ 実際の meta.json は bank/meta.json に存在するものを真とする。
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Literal

from .quota import QuotaManager

UsageSource = Literal["online", "offline"]


class MetaManager:
    """
    bank/meta.json を扱うユーティリティクラス。

    主な責務:
    - meta.json のロード／セーブ
    - usage カウンタの更新
    - chapter_stats による出題バランス制御（偏りを抑える）
    - last_chapter_id による「前回と同じ章を避ける」ロジック
    - QuotaManager のラップ
    """

    def __init__(self, path: str = "bank/meta.json"):
        self.path = Path(path)
        self.meta: Dict[str, Any] = {}
        self.quota: Optional[QuotaManager] = None

    # ------------------------------------------------------------------
    # ロード / セーブ
    # ------------------------------------------------------------------
    def load(self) -> None:
        """meta.json を読み込む。存在しない場合は基本骨格を作る。"""
        if self.path.exists():
            with self.path.open("r", encoding="utf-8") as f:
                self.meta = json.load(f)
        else:
            now = _now_iso()
            self.meta = {
                "version": 1,
                "created_at": now,
                "updated_at": now,
                "usage": {
                    "total_questions": 0,
                    "online_questions": 0,
                    "offline_questions": 0,
                },
                "quota_estimate": {
                    "total_used_tokens": 0,
                    "estimated_limit_tokens": None,
                    "last_429_at": None,
                    "last_error": None,
                },
                "chapter_stats": {},
                "last_chapter_id": None,
                "chapters": {},
            }

        # 足りないキーを安全に補完
        self._ensure_structure()
        # QuotaManager を初期化
        self.quota = QuotaManager(self.meta)

    def save(self) -> None:
        """meta.json を保存する。更新日時を自動で進める。"""
        if not self.meta:
            return

        self.meta["updated_at"] = _now_iso()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(self.meta, f, ensure_ascii=False, indent=2)

    # ------------------------------------------------------------------
    # 内部構造の補完
    # ------------------------------------------------------------------
    def _ensure_structure(self) -> None:
        """meta.json に必要なキーが必ず存在するように補完する。"""
        m = self.meta

        m.setdefault("version", 1)
        m.setdefault("created_at", _now_iso())
        m.setdefault("updated_at", _now_iso())
        m.setdefault("usage", {})
        m.setdefault("quota_estimate", {})
        m.setdefault("chapter_stats", {})
        m.setdefault("last_chapter_id", None)
        m.setdefault("chapters", {})

        usage = m["usage"]
        usage.setdefault("total_questions", 0)
        usage.setdefault("online_questions", 0)
        usage.setdefault("offline_questions", 0)

        quota = m["quota_estimate"]
        quota.setdefault("total_used_tokens", 0)
        quota.setdefault("estimated_limit_tokens", None)
        quota.setdefault("last_429_at", None)
        quota.setdefault("last_error", None)

        # chapter_stats は { chapter_id: { ... } } の形を想定
        if not isinstance(m["chapter_stats"], dict):
            m["chapter_stats"] = {}

    # ------------------------------------------------------------------
    # usage / chapter_stats の更新
    # ------------------------------------------------------------------
    def record_usage(self, chapter_id: str, source: UsageSource) -> None:
        """
        問題を 1問解いたタイミングで呼び出す。

        chapter_id:
            question_bank.jsonl の "chapter_id" に合わせた文字列（例: "1. 人工知能の定義"）
        source:
            "online" または "offline"
        """
        usage = self.meta["usage"]

        usage["total_questions"] += 1
        if source == "online":
            usage["online_questions"] += 1
        elif source == "offline":
            usage["offline_questions"] += 1

        stats = self.meta["chapter_stats"]
        if chapter_id not in stats or not isinstance(stats[chapter_id], dict):
            stats[chapter_id] = {
                "total_questions": 0,
                "online_questions": 0,
                "offline_questions": 0,
            }

        stats[chapter_id]["total_questions"] += 1
        if source == "online":
            stats[chapter_id]["online_questions"] += 1
        elif source == "offline":
            stats[chapter_id]["offline_questions"] += 1

        # 最後に出題した章として記録
        self.meta["last_chapter_id"] = chapter_id

    # ------------------------------------------------------------------
    # 章バランス制御
    # ------------------------------------------------------------------
    def get_all_chapter_labels(self) -> List[str]:
        """
        meta["chapters"] から、シラバス上の全ての subchapter の label を抽出する。

        戻り値の例:
            ["1. 人工知能の定義", "2. 人工知能分野で議論される問題", ...]
        """
        chapters = self.meta.get("chapters", {})
        labels: List[str] = []

        if not isinstance(chapters, dict):
            return labels

        for _group_key, group_val in chapters.items():
            subchapters = group_val.get("subchapters", {})
            if not isinstance(subchapters, dict):
                continue
            for _sub_key, sub_val in subchapters.items():
                label = sub_val.get("label")
                if isinstance(label, str):
                    labels.append(label)

        return labels

    def choose_next_chapter(
        self,
        available_chapter_ids: List[str],
        avoid_same_as_last: bool = True,
    ) -> Optional[str]:
        """
        次に出題する章を決める。

        ポリシー:
        - meta["chapters"] に含まれる章ラベルのうち、
          available_chapter_ids に含まれるものだけを候補とする
        - chapter_stats["total_questions"] が最小の章を優先
        - avoid_same_as_last=True のとき、可能なら last_chapter_id を避ける
        - 候補が複数あればランダムに選ぶ

        返り値:
            選ばれた chapter_id (例: "1. 人工知能の定義")
            候補が無ければ None
        """
        if not available_chapter_ids:
            return None

        # シラバスに定義されている章から、利用可能なものだけに絞る
        syllabus_labels = self.get_all_chapter_labels()
        candidates = [c for c in syllabus_labels if c in available_chapter_ids]

        # シラバス側に定義が無いが、問題は存在する章も一応含める
        for cid in available_chapter_ids:
            if cid not in candidates:
                candidates.append(cid)

        if not candidates:
            return None

        stats: Dict[str, Any] = self.meta.get("chapter_stats", {})
        # 各章の total_questions を取得（無ければ 0）
        def total_for(chap: str) -> int:
            v = stats.get(chap)
            if isinstance(v, dict):
                return int(v.get("total_questions", 0))
            return 0

        # 最小出題回数を求める
        totals = [total_for(c) for c in candidates]
        if not totals:
            return None
        min_total = min(totals)

        # その最小値を持つ章だけ残す
        least_used = [c for c in candidates if total_for(c) == min_total]

        last_chapter = self.meta.get("last_chapter_id")
        if (
            avoid_same_as_last
            and last_chapter in least_used
            and len(least_used) > 1
        ):
            least_used = [c for c in least_used if c != last_chapter]

        return random.choice(least_used) if least_used else None

    # ------------------------------------------------------------------
    # クォータ関連 (QuotaManager のラップ)
    # ------------------------------------------------------------------
    def get_quota_manager(self) -> QuotaManager:
        """
        QuotaManager インスタンスを返す。
        load() 済みであることが前提。
        """
        if self.quota is None:
            self.quota = QuotaManager(self.meta)
        return self.quota

    def get_quota_status(self) -> Dict[str, Any]:
        """
        UI から使いやすい形でクォータ状況を返す。
        """
        return self.get_quota_manager().get_status()


# ----------------------------------------------------------------------
# ユーティリティ
# ----------------------------------------------------------------------
def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
