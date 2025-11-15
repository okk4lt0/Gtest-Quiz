"""
quota.py
======================

Google Gemini API の「推定クォータメーター」を管理するモジュール。

前提となる meta.json の構造（一部）:

"quota_estimate": {
  "total_used_tokens": 0,
  "estimated_limit_tokens": null,
  "last_429_at": null,
  "last_error": null
}

このモジュールの役割:
- 各 API 呼び出し時に、おおよその使用トークン数を加算
- 429(Resource Exhausted) が発生したタイミングで、
  その時点の total_used_tokens から「推定上限」を更新
- 使えば使うほど estimated_limit_tokens が洗練されていく
- UI 側からは「どのくらい危ない状態か」を問い合わせ可能
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional


class QuotaManager:
    """
    meta.json 内の quota_estimate をラップして扱うクラス。
    """

    def __init__(self, meta_ref: Dict[str, Any]):
        """
        meta_ref: bank/meta.json を読み込んだ dict そのものを参照で受け取る。
        """
        self.meta_ref = meta_ref

        if "quota_estimate" not in self.meta_ref:
            self.meta_ref["quota_estimate"] = {}

        q = self.meta_ref["quota_estimate"]
        q.setdefault("total_used_tokens", 0)
        q.setdefault("estimated_limit_tokens", None)
        q.setdefault("last_429_at", None)
        q.setdefault("last_error", None)

        self._q = q  # 参照を保持

    # ------------------------------------------------------------------
    # 使用量の更新
    # ------------------------------------------------------------------
    def add_usage(self, used_tokens: int) -> None:
        """
        推定トークン使用量を加算する。

        実際のトークン数が厳密でなくてもよい。
        プロンプト長 + 応答長の概算値で十分。
        """
        if used_tokens < 0:
            used_tokens = 0
        self._q["total_used_tokens"] += used_tokens

    # ------------------------------------------------------------------
    # 429 エラー時の処理
    # ------------------------------------------------------------------
    def register_429(self, message: Optional[str] = None) -> None:
        """
        429(Resource Exhausted) を検出したときに呼び出す。

        - last_429_at を現在時刻(UTC)で更新
        - last_error にメッセージを保存
        - この時点の total_used_tokens をもとに estimated_limit_tokens を更新
          (今までの推定より大きければ上書きする)
        """
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._q["last_429_at"] = now_iso
        if message:
            self._q["last_error"] = message

        total = self._q.get("total_used_tokens", 0)
        limit = self._q.get("estimated_limit_tokens")

        # まだ上限が無い、あるいは前回推定より多い使用量で 429 が出た場合、
        # 「新たに観測された上限」として更新する。
        if limit is None or (isinstance(limit, (int, float)) and total > limit):
            self._q["estimated_limit_tokens"] = total

    # ------------------------------------------------------------------
    # 一般エラー
    # ------------------------------------------------------------------
    def register_error(self, message: str) -> None:
        """
        429 以外のエラーでも、様子を記録したい場合に利用する。
        """
        self._q["last_error"] = message

    # ------------------------------------------------------------------
    # 状態参照
    # ------------------------------------------------------------------
    def get_status(self) -> Dict[str, Any]:
        """
        UI や app.py から参照するための状態サマリ。
        """
        return {
            "total_used_tokens": self._q.get("total_used_tokens", 0),
            "estimated_limit_tokens": self._q.get("estimated_limit_tokens"),
            "last_429_at": self._q.get("last_429_at"),
            "last_error": self._q.get("last_error"),
        }

    def get_remaining_ratio(self) -> Optional[float]:
        """
        残りクォータの割合を 0.0〜1.0 で返す。
        estimated_limit_tokens が未確定の場合は None を返す。
        """
        limit = self._q.get("estimated_limit_tokens")
        total = self._q.get("total_used_tokens", 0)

        if not isinstance(limit, (int, float)) or limit <= 0:
            return None

        remaining = max(limit - total, 0)
        return remaining / float(limit)

    def is_near_limit(self, threshold: float = 0.9) -> bool:
        """
        「そろそろ上限が近いか？」を判定する。

        threshold: total_used_tokens / estimated_limit_tokens が
                   この値以上なら「近い」とみなす。
        """
        limit = self._q.get("estimated_limit_tokens")
        total = self._q.get("total_used_tokens", 0)

        if not isinstance(limit, (int, float)) or limit <= 0:
            return False

        ratio = total / float(limit)
        return ratio >= threshold
