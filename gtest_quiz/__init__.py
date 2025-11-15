"""
gtest_quiz パッケージ

Streamlit 製 G検定クイズアプリの内部モジュールをまとめるパッケージです。
ここでは副作用のある import は行わず、必要なサブモジュールは
利用側が明示的に import する方針にしています。

例:
    from gtest_quiz.meta import MetaManager
    from gtest_quiz.question_bank import QuestionBank
    from gtest_quiz.ui import render_app
"""

# パッケージとして公開しているサブモジュール名
__all__ = [
    "meta",
    "models",
    "question_bank",
    "quota",
    "syllabus",
    "ui",
]
