# ui.py — iPhone Safari 最適化 UI（最先端デザイン）

import streamlit as st
from gtest_quiz.question_bank import QuestionBank
from gtest_quiz.models import UserState


# ----------------------------------------------------------
#  テーマ設定（iOS標準 Light / Dark / Blue）
# ----------------------------------------------------------
THEMES = {
    "light": {
        "bg": "#ffffff",
        "text": "#1c1c1e",
        "surface": "#f2f2f7",
        "border": "#d1d1d6",
        "primary": "#007aff",  # iOSブルー
        "correct": "#34c759",
        "incorrect": "#ff3b30",
    },
    "dark": {
        "bg": "#000000",
        "text": "#f5f5f7",
        "surface": "#1c1c1e",
        "border": "#3a3a3c",
        "primary": "#0a84ff",
        "correct": "#30d158",
        "incorrect": "#ff453a",
    },
    "blue": {
        "bg": "#f5f9ff",
        "text": "#0a1a2f",
        "surface": "#ffffff",
        "border": "#c9d6e8",
        "primary": "#0066cc",
        "correct": "#1f9d55",
        "incorrect": "#d64545",
    }
}


# ----------------------------------------------------------
#  CSS生成関数（テーマに応じて動的生成）
# ----------------------------------------------------------
def generate_css(theme):

    return f"""
    <style>

    html, body {{
        background: {theme['bg']};
        color: {theme['text']};
        -webkit-text-size-adjust: 100%;
        margin: 0;
        padding: 0;
        touch-action: manipulation;
        -webkit-tap-highlight-color: rgba(0,0,0,0);
        font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue";
    }}

    .container {{
        max-width: 680px;
        margin: 0 auto;
        padding: 1rem;
    }}

    .question-box {{
        background: {theme['surface']};
        padding: 1rem;
        border-radius: 12px;
        border: 1px solid {theme['border']};
        font-size: 1.15rem;
        line-height: 1.6;
        margin-bottom: 1rem;
    }}

    .choice-btn {{
        width: 100%;
        padding: 0.85rem 1rem;
        font-size: 1.05rem;
        border-radius: 10px;
        margin-bottom: 0.5rem;
        background: #fff;
        color: {theme['text']};
        text-align: left;
        border: 1px solid {theme['border']};
        transition: background 0.2s ease;
    }}

    .choice-btn:active {{
        background: {theme['surface']};
    }}

    .correct {{
        background: {theme['correct']}33 !important;
        border-color: {theme['correct']} !important;
    }}

    .incorrect {{
        background: {theme['incorrect']}33 !important;
        border-color: {theme['incorrect']} !important;
    }}

    .explanation-box {{
        padding: 1rem;
        font-size: 1rem;
        line-height: 1.6;
        background: {theme['surface']};
        border: 1px solid {theme['border']};
        border-radius: 10px;
    }}

    /* 進捗バー（iOS風） */
    .progress-container {{
        width: 100%;
        height: 10px;
        background: {theme['border']}55;
        border-radius: 5px;
        margin-bottom: 1rem;
        overflow: hidden;
    }}

    .progress-bar {{
        height: 10px;
        background: {theme['primary']};
        width: 0%;
        border-radius: 5px;
        transition: width 0.4s ease-out;
    }}

    .nav-btn {{
        width: 48%;
        padding: 0.9rem;
        font-size: 1rem;
        border-radius: 10px;
        background: {theme['primary']}22;
        border: 1px solid {theme['primary']};
        color: {theme['primary']};
    }}

    .nav-btn:active {{
        background: {theme['primary']}33;
    }}

    .safe-bottom {{
        height: 100px;
    }}
    </style>
    """


# ----------------------------------------------------------
#  UI本体
# ----------------------------------------------------------
class QuizUI:

    def __init__(self):
        self.bank = QuestionBank()
        self.state = UserState.load()

    def render(self):

        # テーマ選択（ユーザーによる切替用）
        theme_key = st.session_state.get("theme", "light")
        theme = THEMES[theme_key]

        st.markdown(generate_css(theme), unsafe_allow_html=True)
        st.markdown("<div class='container'>", unsafe_allow_html=True)

        chapter = self.state.current_chapter
        idx = self.state.current_index
        q = self.bank.get_question(chapter, idx)

        if q is None:
            st.error("問題が見つかりません。")
            return

        # --------------------------------------------------
        #  進捗バー（iPhone最適アニメーション）
        # --------------------------------------------------
        progress = self.bank.get_progress_ratio(chapter, idx)

        st.markdown(
            f"""
            <div class="progress-container">
                <div class="progress-bar" style="width:{progress}%"></div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # --------------------------------------------------
        #  見出し
        # --------------------------------------------------
        st.write(f"### {q['chapter_group']}")
        st.write(f"**{q['chapter_id']}**")
        st.write("---")

        # --------------------------------------------------
        #  問題文
        # --------------------------------------------------
        st.markdown(
            f"<div class='question-box'>{q['question']}</div>",
            unsafe_allow_html=True,
        )

        # --------------------------------------------------
        #  選択肢
        # --------------------------------------------------
        selected = st.session_state.get("selected_choice", None)

        for i, c in enumerate(q["choices"]):

            class_name = "choice-btn"
            if selected is not None:
                if i == q["correct_index"]:
                    class_name += " correct"
                elif selected == i:
                    class_name += " incorrect"

            if st.button(c, key=f"c_{i}", use_container_width=True):
                if selected is None:
                    st.session_state["selected_choice"] = i

        # --------------------------------------------------
        #  解説
        # --------------------------------------------------
        if selected is not None:
            with st.expander("解説を見る"):
                st.markdown(
                    f"<div class='explanation-box'>{q['explanation']}</div>",
                    unsafe_allow_html=True
                )

        # --------------------------------------------------
        #  ナビゲーション
        # --------------------------------------------------
        left, right = st.columns(2)

        if left.button("◀ 前へ", use_container_width=True):
            st.session_state["selected_choice"] = None
            self.state.previous()

        if right.button("次へ ▶", use_container_width=True):
            st.session_state["selected_choice"] = None
            self.state.next(self.bank)

        st.markdown("<div class='safe-bottom'></div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

        self.state.save()
