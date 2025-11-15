"""
config.py
=========

アプリ全体で利用する設定値を一元管理する。
Streamlit、Gemini API、ファイルパス、モデルフェールオーバーなど
すべてこのクラスを通じて取得する。

本ファイルは app.py と tools/auto_refill.py の共通設定でもある。
"""

from dataclasses import dataclass
from pathlib import Path
import os
import json


# ------------------------------------------------------------
# 基本パス定義
# ------------------------------------------------------------

ROOT_DIR = Path(__file__).resolve().parent.parent
BANK_DIR = ROOT_DIR / "bank"
DATA_DIR = ROOT_DIR / "data"


# ------------------------------------------------------------
# AppConfig
# ------------------------------------------------------------

@dataclass
class AppConfig:
    """
    アプリ設定クラス。

    - APIキーの読み取り
    - QuestionBank / Meta のパス
    - モデル一覧 API
    - フェールオーバー順
    """

    # ---------- API ----------
    gemini_api_key: str = ""
    gemini_model_list_url: str = (
        "https://generativelanguage.googleapis.com/v1beta/models"
    )

    # ---------- ファイルパス ----------
    question_bank_path: Path = BANK_DIR / "question_bank.jsonl"
    meta_json_path: Path = BANK_DIR / "meta.json"
    syllabus_pdf_path: Path = DATA_DIR / "JDLA_Gtest_Syllabus_2024_v1.3_JP.pdf"

    # ---------- モデルフェールオーバー設定 ----------
    model_failover_priority: list = None

    # ---------- 自動生成設定 ----------
    auto_refill_seed_prompt: str = (
        "シラバスに基づき、G検定の四択問題を1問生成してください。"
    )

    # ============================================================
    # 初期化処理
    # ============================================================

    def __post_init__(self):
        # APIキーのロード
        self.gemini_api_key = self._load_api_key()

        # 最新モデル → fallback → fallback の順で探索
        self.model_failover_priority = [
            # 最新モデルは実行時に ModelManager が API 動的取得
            "latest",
            # 以下は保険のフェールオーバー
            "gemini-pro",
            "gemini-1.5-pro",
            "gemini-1.0-pro",
        ]

    # ============================================================
    # 内部関数
    # ============================================================

    def _load_api_key(self) -> str:
        """
        Streamlit Cloud / GitHub Actions / ローカルすべてで
        GEMINI_API_KEY が使えるようにする。
        """

        key = os.environ.get("GEMINI_API_KEY")
        if key:
            return key

        # ローカル開発などで .env を使いたい場合にも対応
        env_path = ROOT_DIR / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("GEMINI_API_KEY="):
                    return line.split("=", 1)[1].strip()

        return ""  # キーなし → オフラインモードへ

    # ============================================================
    # JSON 読み取りユーティリティ
    # ============================================================

    @staticmethod
    def read_json(path: Path):
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def write_json(path: Path, data: dict):
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
