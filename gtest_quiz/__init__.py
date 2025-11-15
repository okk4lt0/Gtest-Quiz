"""
gtest_quiz パッケージ
======================

このパッケージは、G検定対策クイズアプリの内部ロジックを提供する。

主な役割:
- 設定管理（config）
- シラバス構造の読み込み・章管理（syllabus）
- オフライン問題バンク管理（question_bank）
- Gemini API モデル管理（models）
- 推定クォータメーター（quota）
- 章の偏りを抑える出題制御（meta）
- UI コンポーネント（ui）

app.py は Streamlit UI のみを担当し、内部ロジックはすべて本パッケージから呼ぶ。
"""

from .config import AppConfig
from .syllabus import Syllabus, load_syllabus_structure
from .question_bank import QuestionBank
from .meta import ChapterMetaManager
from .models import ModelManager
from .quota import QuotaEstimator
from .ui import (
    render_header,
    render_footer,
    render_quota_meter,
    render_question_block,
)

__all__ = [
    "AppConfig",
    "Syllabus",
    "load_syllabus_structure",
    "QuestionBank",
    "ChapterMetaManager",
    "ModelManager",
    "QuotaEstimator",
    "render_header",
    "render_footer",
    "render_quota_meter",
    "render_question_block",
]
