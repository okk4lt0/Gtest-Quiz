"""
ui.py
======================

Streamlit ベースの UI コンポーネントをまとめたモジュール。

責務:
- iPhone Safari を主ターゲットとしたレイアウトとスタイル
- 問題画面の描画（質問・選択肢・解説）
- ヘッダー（シラバス情報・クォータメーター・テーマ切替）
- ナビゲーションボタン（前へ / 次へ / 章変更）

ここでは「見た目」と「ユーザー操作の入力」を扱い、
問題選択ロジックやメタ情報更新などのビジネスロジックは app.py 側に任せる。

戻り値として「何が押されたか」「どの選択肢が新たに選ばれたか」を返す。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import streamlit as st

from .models import SessionState, Question

# ----------------------------------------------------------------------
#  テーマ定義（iPhone Safari 向け）
# ----------------------------------------------------------------------


THEMES: Dict[str, Dict[str, str]] = {
    "light": {
        "bg": "#ffffff",
        "text": "#1c1c1e",
        "surface": "#f2f2f7",
        "surface_alt": "#ffffff",
        "border": "#d1d1d6",
        "primary": "#007aff",  # iOS ブルー
        "correct": "#34c759",
        "incorrect": "#ff3b30",
    },
    "dark": {
        "bg": "#000000",
        "text": "#f5f5f7",
        "surface": "#1c1c1e",
        "surface_alt": "#2c2c2e",
        "border": "#3a3a3c",
        "primary": "#0a84ff",
        "correct": "#30d158",
        "incorrect": "#ff453a",
    },
    "blue": {
        "bg": "#f5f9ff",
        "text": "#0a1a2f",
        "surface": "#e8f0ff",
        "surface_alt": "#ffffff",
        "border": "#c9d6e8",
        "primary": "#0066cc",
        "correct": "#1f9d55",
        "incorrect": "#d64545",
    },
}


# ----------------------------------------------------------------------
#  CSS 生成
# ----------------------------------------------------------------------
def _generate_css(theme: Dict[str, str]) -> str:
    """テーマに応じたグローバル CSS を生成する。"""

    return f"""
    <style>
    html, body {{
        margin: 0;
        padding: 0;
        background: {theme['bg']};
        color: {theme['text']};
        -webkit-text-size-adjust: 100%;
        touch-action: manipulation;
        -webkit-tap-highlight-color: rgba(0,0,0,0);
        font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text",
                     "Helvetica Neue", Arial, sans-serif;
    }}

    .gq-container {{
        max-width: 700px;
        margin: 0 auto;
        padding: 1rem;
    }}

    .gq-header {{
        display: flex;
        flex-direction: column;
        gap: 0.4rem;
        margin-bottom: 0.5rem;
    }}

    .gq-title-row {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 0.5rem;
    }}

    .gq-app-title {{
        font-weight: 600;
        font-size: 1.15rem;
    }}

    .gq-mode-badge {{
        padding: 0.1rem 0.5rem;
        border-radius: 999px;
        border: 1px solid {theme['border']};
        font-size: 0.75rem;
        white-space: nowrap;
    }}

    .gq-chapter-tags {{
        display: flex;
        flex-wrap: wrap;
        gap: 0.25rem;
        font-size: 0.8rem;
    }}

    .gq-tag {{
        padding: 0.1rem 0.5rem;
        border-radius: 999px;
        background: {theme['surface']};
        border: 1px solid {theme['border']};
    }}

    /* クォータメーター */
    .gq-quota {{
        display: flex;
        align-items: center;
        gap: 0.5rem;
        font-size: 0.75rem;
        margin-top: 0.25rem;
    }}

    .gq-quota-label {{
        white-space: nowrap;
    }}

    .gq-quota-bar {{
        flex: 1;
        height: 8px;
        background: {theme['border']}55;
        border-radius: 4px;
        overflow: hidden;
    }}

    .gq-quota-fill {{
        height: 8px;
        background: {theme['primary']};
        width: 0%;
        border-radius: 4px;
        transition: width 0.3s ease-out;
    }}

    .gq-question-box {{
        background: {theme['surface_alt']};
        padding: 1rem;
        border-radius: 12px;
        border: 1px solid {theme['border']};
        font-size: 1.1rem;
        line-height: 1.6;
        margin-top: 0.5rem;
        margin-bottom: 0.75rem;
    }}

    .gq-choice-btn {{
        width: 100%;
        padding: 0.9rem 0.9rem;
        font-size: 1rem;
        border-radius: 10px;
        margin-bottom: 0.45rem;
        border: 1px solid {theme['border']};
        background: {theme['surface_alt']};
        text-align: left;
        transition: background 0.15s ease-out, border-color 0.15s ease-out;
    }}

    .gq-choice-btn:active {{
        background: {theme['surface']};
    }}

    .gq-choice-correct {{
        background: {theme['correct']}22 !important;
        border-color: {theme['correct']} !important;
    }}

    .gq-choice-incorrect {{
        background: {theme['incorrect']}22 !important;
        border-color: {theme['incorrect']} !important;
    }}

    .gq-explanation-box {{
        padding: 0.9rem;
        border-radius: 10px;
        background: {theme['surface_alt']};
        border: 1px solid {theme['border']};
        font-size: 0.95rem;
        line-height: 1.6;
    }}

    .gq-footer {{
        margin-top: 0.75rem;
        display: flex;
        justify-content: space-between;
        align-items: center;
        font-size: 0.8rem;
        color: {theme['text']}aa;
    }}

    .gq-nav-row {{
        margin-top: 0.5rem;
        display: flex;
        gap: 0.5rem;
    }}

    .gq-nav-btn {{
        flex: 1;
        padding: 0.75rem;
        font-size: 0.95rem;
        border-radius: 10px;
        border: 1px solid {theme['primary']};
        background: {theme['primary']}11;
        color: {theme['primary']};
    }}

    .gq-nav-btn:active {{
        background: {theme['primary']}22;
    }}

    .gq-safe-bottom {{
        height: 80px; /* iPhone Safari 下部 UI に埋もれないための余白 */
    }}
    </style>
    """


# ----------------------------------------------------------------------
#  テーマ関連
# ----------------------------------------------------------------------
def _ensure_theme() -> str:
    """セッションに theme キーを用意し、現在のテーマキーを返す。"""
    if "theme" not in st.session_state:
        st.session_state["theme"] = "light"
    theme_key = st.session_state.get("theme", "light")
    if theme_key not in THEMES:
        theme_key = "light"
        st.session_state["theme"] = "light"
    return theme_key


def _render_theme_selector(theme_key: str) -> str:
    """ヘッダーの右上あたりにテーマ切替を表示し、選択されたテーマキーを返す。"""
    # Streamlit の radio を横並びで使用
    options = ["light", "dark", "blue"]
    labels = {"light": "Light", "dark": "Dark", "blue": "Blue"}

    idx = options.index(theme_key) if theme_key in options else 0
    selected = st.radio(
        "テーマ",
        options,
        index=idx,
        horizontal=True,
        label_visibility="collapsed",
        format_func=lambda k: labels.get(k, k),
    )
    st.session_state["theme"] = selected
    return selected


# ----------------------------------------------------------------------
#  公開 API: クイズページの描画
# ----------------------------------------------------------------------
def render_quiz_page(
    session: SessionState,
    *,
    progress_ratio: Optional[float] = None,
    quota_status: Optional[Dict[str, Any]] = None,
    mode_label: str = "AUTO",
) -> Dict[str, Any]:
    """
    クイズページ全体を描画し、ユーザー操作の結果を返す。

    引数:
        session:
            models.SessionState のインスタンス。
            - current_question に Question が入っている前提。
        progress_ratio:
            章内の進捗 (0.0〜1.0)。None の場合は表示しない。
        quota_status:
            MetaManager.get_quota_status() の戻り値を想定。
            total_used_tokens / estimated_limit_tokens / last_429_at / last_error
        mode_label:
            画面上に表示するモード表記 (例: "ONLINE", "OFFLINE", "AUTO")。

    戻り値:
        {
          "selected_choice": Optional[int],   # 新たに押された選択肢 index (なければ None)
          "clicked_next": bool,
          "clicked_prev": bool,
          "clicked_change_chapter": bool,
          "theme": str,                       # 現在のテーマキー
        }
    """
    # セーフティ: 問題がない場合
    if not isinstance(session.current_question, Question):
        st.error("問題がまだ選択されていません。")
        return {
            "selected_choice": None,
            "clicked_next": False,
            "clicked_prev": False,
            "clicked_change_chapter": False,
            "theme": _ensure_theme(),
        }

    # テーマ決定と CSS 注入
    theme_key = _ensure_theme()
    theme = THEMES[theme_key]
    st.markdown(_generate_css(theme), unsafe_allow_html=True)

    # 操作結果の初期値
    selected_choice: Optional[int] = None
    clicked_next = False
    clicked_prev = False
    clicked_change_chapter = False

    q = session.current_question

    # ----------------------------------------
    # コンテナ開始
    # ----------------------------------------
    st.markdown("<div class='gq-container'>", unsafe_allow_html=True)

    # ----------------------------------------
    # ヘッダー
    # ----------------------------------------
    with st.container():
        st.markdown("<div class='gq-header'>", unsafe_allow_html=True)

        col_left, col_right = st.columns([2.2, 1.8])

        with col_left:
            st.markdown(
                "<div class='gq-title-row'>"
                "<div class='gq-app-title'>G検定クイズ</div>"
                "</div>",
                unsafe_allow_html=True,
            )

            # 章ラベルタグ
            tags_html = [
                f"<span class='gq-tag'>{q.chapter_group}</span>",
                f"<span class='gq-tag'>{q.chapter_id}</span>",
                f"<span class='gq-tag'>難易度: {q.difficulty}</span>",
            ]
            st.markdown(
                "<div class='gq-chapter-tags'>" + "".join(tags_html) + "</div>",
                unsafe_allow_html=True,
            )

        with col_right:
            # モードバッジ
            mode_html = (
                f"<div style='text-align:right;'>"
                f"<span class='gq-mode-badge'>{mode_label}</span>"
                f"</div>"
            )
            st.markdown(mode_html, unsafe_allow_html=True)
            _render_theme_selector(theme_key)

        # クォータメーター
        if quota_status is not None:
            _render_quota_meter(theme, quota_status)

        # 進捗バー（章内）
        if progress_ratio is not None:
            pr = min(max(progress_ratio, 0.0), 1.0)
            percent = int(pr * 100)
            bar_html = (
                "<div class='gq-quota' style='margin-top:0.3rem;'>"
                "<div class='gq-quota-label'>章の進捗</div>"
                "<div class='gq-quota-bar'>"
                f"<div class='gq-quota-fill' style='width:{percent}%'></div>"
                "</div>"
                f"<div style='font-size:0.75rem; white-space:nowrap;'>{percent}%</div>"
                "</div>"
            )
            st.markdown(bar_html, unsafe_allow_html=True)

        st.markdown("</div>", unsafe_allow_html=True)

    # ----------------------------------------
    # 問題文
    # ----------------------------------------
    st.markdown(
        f"<div class='gq-question-box'>{q.question}</div>",
        unsafe_allow_html=True,
    )

    # ----------------------------------------
    # 選択肢
    # ----------------------------------------
    # すでに回答済みかどうか
    answered_index = session.selected_index
    correct_index = q.correct_index if session.is_correct is not None else None

    for idx, choice_text in enumerate(q.choices):
        classes = ["gq-choice-btn"]

        if answered_index is not None and correct_index is not None:
            if idx == correct_index:
                classes.append("gq-choice-correct")
            elif idx == answered_index and answered_index != correct_index:
                classes.append("gq-choice-incorrect")

        class_attr = " ".join(classes)
        button_html = f"<button class='{class_attr}'>{choice_text}</button>"

        if st.button(
            choice_text,
            key=f"gq_choice_{idx}",
            use_container_width=True,
        ):
            # 未回答時のみ「新たな選択」として扱う
            if answered_index is None:
                selected_choice = idx

        # 上記 st.button 用に class を当てるための HTML を後追いで描画（視覚のみ）
        st.markdown(
            f"<div style='margin-top:-3.1rem; pointer-events:none;'>{button_html}</div>",
            unsafe_allow_html=True,
        )

    # ----------------------------------------
    # 解説（回答済みの場合のみ）
    # ----------------------------------------
    if answered_index is not None:
        with st.expander("解説"):
            st.markdown(
                f"<div class='gq-explanation-box'>{q.explanation}</div>",
                unsafe_allow_html=True,
            )

    # ----------------------------------------
    # ナビゲーション
    # ----------------------------------------
    col_prev, col_next = st.columns(2)
    with col_prev:
        if st.button("◀ ひとつ前", key="gq_prev", use_container_width=True):
            clicked_prev = True
    with col_next:
        if st.button("次の問題 ▶", key="gq_next", use_container_width=True):
            clicked_next = True

    col_change, col_dummy = st.columns([1, 1])
    with col_change:
        if st.button("章を変える", key="gq_change_chapter", use_container_width=True):
            clicked_change_chapter = True

    # フッター
    st.markdown(
        "<div class='gq-footer'>"
        "<div>G検定対策用クイズアプリ</div>"
        "<div>© Gtest-Quiz</div>"
        "</div>",
        unsafe_allow_html=True,
    )

    st.markdown("<div class='gq-safe-bottom'></div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    return {
        "selected_choice": selected_choice,
        "clicked_next": clicked_next,
        "clicked_prev": clicked_prev,
        "clicked_change_chapter": clicked_change_chapter,
        "theme": st.session_state.get("theme", theme_key),
    }


# ----------------------------------------------------------------------
#  クォータメーター描画
# ----------------------------------------------------------------------
def _render_quota_meter(theme: Dict[str, str], quota_status: Dict[str, Any]) -> None:
    """推定クォータメーターを描画する。"""

    total = int(quota_status.get("total_used_tokens", 0))
    limit = quota_status.get("estimated_limit_tokens")
    last_429_at = quota_status.get("last_429_at")

    if isinstance(limit, (int, float)) and limit > 0:
        ratio = max(min(total / float(limit), 1.0), 0.0)
        percent = int(ratio * 100)
        label_text = f"推定クォータ {total}/{int(limit)} tokens"
    else:
        ratio = 0.0
        percent = 0
        label_text = "推定クォータ 学習中"

    extra = ""
    if last_429_at:
        extra = f"・最終 429: {last_429_at}"

    html = (
        "<div class='gq-quota'>"
        f"<div class='gq-quota-label'>{label_text}{extra}</div>"
        "<div class='gq-quota-bar'>"
        f"<div class='gq-quota-fill' style='width:{percent}%'></div>"
        "</div>"
        "</div>"
    )
    st.markdown(html, unsafe_allow_html=True)
