"""
history.py
=====================================

問題を解いた履歴の管理を担当するモジュール。
meta.json の usage と連携し、アプリ全体の利用履歴を記録する。

meta.json の usage 構造:

"usage": {
    "total_questions": 0,
    "online_questions": 0,
    "offline_questions": 0
}

total_questions: 出題総数
online_questions: Live モードで解いた問題数
offline_questions: オフライン（保存済バンク）で解いた問題数
"""

from __future__ import annotations
from typing import Dict, Any, List, Optional
import time


class HistoryManager:
    """
    解答履歴と usage カウンタを管理するクラス。
    """

    def __init__(self, meta_ref: Dict[str, Any]):
        """
        meta.json をそのまま dict として渡す。
        （MetaManager が読み込み、辞書を参照で保持している前提）
        """
        self.meta_ref = meta_ref

        # usage 初期化（存在しない場合の安全策）
        if "usage" not in self.meta_ref:
            self.meta_ref["usage"] = {}

        usage = self.meta_ref["usage"]
        usage.setdefault("total_questions", 0)
        usage.setdefault("online_questions", 0)
        usage.setdefault("offline_questions", 0)

        # メモリ内履歴
        self.session_history: List[Dict[str, Any]] = []

    # ---------------------------------------------------------
    # 履歴を追加
    # ---------------------------------------------------------
    def record_question(
        self,
        question_id: str,
        mode: str,  # "online" / "offline"
        correct: Optional[bool] = None,
        extra: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        出題履歴を 1 件追加し、meta.json の usage に反映する。

        mode:
            "online"  → online_questions を加算
            "offline" → offline_questions を加算
        """

        record = {
            "id": question_id,
            "mode": mode,
            "correct": correct,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        if extra:
            record.update(extra)

        # セッション履歴に記録
        self.session_history.append(record)

        # meta.json 側の usage を更新
        usage = self.meta_ref["usage"]
        usage["total_questions"] += 1

        if mode == "online":
            usage["online_questions"] += 1
        elif mode == "offline":
            usage["offline_questions"] += 1

    # ---------------------------------------------------------
    # 状態を取得（UI 用）
    # ---------------------------------------------------------
    def get_usage_status(self) -> Dict[str, Any]:
        """UI などで参照するための usage 取得"""
        return {
            "total_questions": self.meta_ref["usage"]["total_questions"],
            "online_questions": self.meta_ref["usage"]["online_questions"],
            "offline_questions": self.meta_ref["usage"]["offline_questions"],
        }

    # ---------------------------------------------------------
    # セッション履歴の取得
    # ---------------------------------------------------------
    def get_session_history(self) -> List[Dict[str, Any]]:
        """
        アプリが起動してから記録した履歴を取得（永続化はしない）
        """
        return self.session_history
