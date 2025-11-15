"""
models.py
======================

Google Gemini API のモデル管理クラス。

要件:
- 利用可能なモデル一覧を API から動的に取得
- 最新モデルを自動選択 (名前・日付で優先度判定)
- モデル呼び出しに失敗した場合は順番にフェールオーバー
- すべてのオンラインモデルで失敗した場合はオフラインモードへ切替
- app.py からは ModelManager だけ使えばよいように設計
"""

from __future__ import annotations
import time
from typing import List, Optional, Dict, Any

import google.generativeai as genai
from google.api_core.exceptions import GoogleAPIError, ResourceExhausted


class ModelManager:
    """
    Gemini モデルの管理クラス。

    主な機能:
    - list_models(): 利用可能モデル一覧を取得
    - select_best_model(): 最新モデルを自動判定
    - generate(): モデル呼び出し (フェールオーバー付き)
    """

    def __init__(self, api_key: str):
        self.api_key = api_key
        genai.configure(api_key=api_key)
        self._cached_models: List[str] = []
        self._last_selected_model: Optional[str] = None

    # ------------------------------------------------------------
    # モデル一覧取得
    # ------------------------------------------------------------
    def list_models(self) -> List[str]:
        """
        Gemini API から利用可能なモデル一覧を取得し、文字列リストで返す。

        名前の例:
        - gemini-2.0-flash
        - gemini-2.0-pro
        - gemini-1.5-flash
        """
        try:
            response = genai.list_models()
        except Exception:
            return []

        models = []
        for m in response:
            name = m.name
            # text-generation / generateContent が使えるモデルだけフィルタする
            if hasattr(m, "supported_generation_methods"):
                if "generateContent" in m.supported_generation_methods:
                    models.append(name)

        # キャッシュ
        if models:
            self._cached_models = models

        return models

    # ------------------------------------------------------------
    # 最新モデルの自動選択
    # ------------------------------------------------------------
    def select_best_model(self) -> Optional[str]:
        """
        モデル名に含まれる数字 (バージョン) と flash/pro の優先度を元に最新モデルを選択。
        例: gemini-2.0-pro > gemini-2.0-flash > gemini-1.5-pro
        """
        models = self.list_models()
        if not models:
            return None

        def score(model_name: str) -> tuple:
            # 数字部分を抽出（例: gemini-2.0-pro → (2, 0)）
            try:
                version_str = model_name.split("-")[1]  # 2.0
                major, minor = version_str.split(".")
                major = int(major)
                minor = int(minor)
            except Exception:
                major, minor = (0, 0)

            # pro > flash
            priority = 1 if "pro" in model_name else 0

            return (major, minor, priority)

        # 最高スコアのモデルが最新扱い
        models_sorted = sorted(models, key=score, reverse=True)
        best = models_sorted[0]
        self._last_selected_model = best
        return best

    # ------------------------------------------------------------
    # generate() — フェールオーバーつき生成
    # ------------------------------------------------------------
    def generate(self, prompt: str) -> Dict[str, Any]:
        """
        モデルを自動選択し、失敗した場合は次候補へフェールオーバーする。
        すべてのモデル失敗時は {"offline": True} を返す。
        """
        models = self.list_models()
        if not models:
            return {"offline": True}

        # 最新モデルから順に試す
        ordered = sorted(models, key=lambda n: n, reverse=True)

        for model_name in ordered:
            try:
                model = genai.GenerativeModel(model_name)
                response = model.generate_content(prompt)
                return {
                    "model": model_name,
                    "text": response.text,
                    "raw": response,
                    "offline": False,
                }
            except ResourceExhausted:
                # クォータ上限（429）
                return {
                    "model": model_name,
                    "error": "429",
                    "offline": True,
                }
            except GoogleAPIError:
                # API エラー → 次のモデルへフェールオーバー
                time.sleep(0.3)
                continue
            except Exception:
                # その他エラー → 次のモデルへ
                continue

        # 全てのモデルでエラー
        return {"offline": True}
