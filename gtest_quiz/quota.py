"""
quota.py
======================

・アプリ内部で使用する簡易クォータ管理
・meta.json の quota_estimate と同期する役割

本アプリでは本格的な API 利用トークンではなく、
「学習履歴」「使用量ログ」「429 などの状態」を meta 側に反映する。
"""

from __future__ import annotations
import time
from typing import Optional, Dict, Any


class QuotaManager:
    """
    meta.json の `quota_estimate` に相当する値を内部で扱うユーティリティ。

    本アプリでは主に以下を扱う：
        - total_used_tokens      : 使用量の概算
        - estimated_limit_tokens : 想定上限（任意）
        - last_429_at            : 429 があれば記録
        - last_error             : 直近エラー内容
    """

    def __init__(self, meta_ref: Dict[str, Any]):
        """
        meta.json の dict をそのまま受け取る。
        （app.py で MetaManager.parse() の結果を渡す前提）
        """
        self.meta_ref = meta_ref

        # 初期化（存在しない場合に安全に作る）
        if "quota_estimate" not in self.meta_ref:
            self.meta_ref["quota_estimate"] = {}

        self.q = self.meta_ref["quota_estimate"]
        self.q.setdefault("total_used_tokens", 0)
        self.q.setdefault("estimated_limit_tokens", None)
        self.q.setdefault("last_429_at", None)
        self.q.setdefault("last_error", None)

    # ----------------------------------------------------------------------
    # 使用量の更新
    # ----------------------------------------------------------------------
    def add_usage(self, used_tokens: int) -> None:
        """使用トークン量（概算）を加算"""
        if used_tokens < 0:
            used_tokens = 0
        self.q["total_used_tokens"] += used_tokens

    # ----------------------------------------------------------------------
    # 429 エラー
    # ----------------------------------------------------------------------
    def register_429(self) -> None:
        """429 を記録"""
        self.q["last_429_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # ----------------------------------------------------------------------
    # エラー記録
    # ----------------------------------------------------------------------
    def register_error(self, message: str) -> None:
        """汎用エラーを記録"""
        self.q["last_error"] = message

    # ----------------------------------------------------------------------
    # クォータ状況取得
    # ----------------------------------------------------------------------
    def get_status(self) -> Dict[str, Any]:
        """アプリ側で UI 表示のために取得する"""
        return {
            "total_used_tokens": self.q.get("total_used_tokens"),
            "estimated_limit_tokens": self.q.get("estimated_limit_tokens"),
            "last_429_at": self.q.get("last_429_at"),
            "last_error": self.q.get("last_error"),
        }
