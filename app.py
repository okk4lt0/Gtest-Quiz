"""
app.py
======================

G検定対策クイズアプリ（Streamlit）エントリーポイント。

特徴:
- ホーム画面 + メニュー構成（C案）
- クイズ / 間違い復習 / 学習統計 / 設定 / 使い方
- オンライン( Gemini ) / オフライン問題の両対応
- 偏りを抑えた章選択（MetaManager）
- 推定クォータメーター表示（QuotaManager + ui.py）

前提:
- bank/question_bank.jsonl にサンプル問題が格納されている
- bank/meta.json が存在する（なければ自動で初期化される）
- 環境変数 GEMINI_API_KEY が設定されていればオンライン出題が有効
"""

from __future__ import annotations

import os
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import streamlit as st

from gtest_quiz.meta import MetaManager
from gtest_quiz.models import SessionState, Question
from gtest_quiz.question_bank import (
    get_all_questions,
    get_questions_by_chapter,
    pick_random_from_chapter,
    pick_random_question,
    get_question_by_id,
)
from gtest_quiz.ui import render_quiz_page

# google-generativeai は存在しない環境でも動くように、遅延インポート + フォールバック
try:
    import google.generativeai as genai  # type: ignore[import]
    HAS_GEMINI = True
except Exception:
    genai = None  # type: ignore[assignment]
    HAS_GEMINI = False

# toml は config.toml が無くても動くように optional に扱う
try:
    import toml  # type: ignore[import]
    HAS_TOML = True
except Exception:
    toml = None  # type: ignore[assignment]
    HAS_TOML = False


# ----------------------------------------------------------------------
#  アプリ設定読み込み
# ----------------------------------------------------------------------
def load_app_config() -> Dict[str, Any]:
    """
    ルート config.toml を読み込む。
    読み込みに失敗しても空 dict を返す。
    """
    if "app_config" in st.session_state:
        return st.session_state["app_config"]

    cfg: Dict[str, Any] = {}
    path = "config.toml"

    if HAS_TOML and os.path.exists(path):
        try:
            cfg = toml.load(path)  # type: ignore[arg-type]
        except Exception:
            cfg = {}

    st.session_state["app_config"] = cfg
    return cfg


# ----------------------------------------------------------------------
#  MetaManager / SessionState のラッパー
# ----------------------------------------------------------------------
def get_meta_manager() -> MetaManager:
    """MetaManager をセッションに保持して返す。"""
    if "meta_manager" not in st.session_state:
        mm = MetaManager("bank/meta.json")
        mm.load()
        st.session_state["meta_manager"] = mm
    return st.session_state["meta_manager"]  # type: ignore[return-value]


def get_session_state() -> SessionState:
    """Quiz用の SessionState をセッションに保持して返す。"""
    if "quiz_session" not in st.session_state:
        cfg = load_app_config()
        default_mode = (
            cfg.get("app", {}).get("default_mode", "auto")
            if isinstance(cfg.get("app"), dict)
            else "auto"
        )
        st.session_state["quiz_session"] = SessionState(mode=default_mode)
    return st.session_state["quiz_session"]  # type: ignore[return-value]


def set_page(page: str) -> None:
    st.session_state["page"] = page


def get_page() -> str:
    return st.session_state.get("page", "home")


# ----------------------------------------------------------------------
#  Gemini 関連
# ----------------------------------------------------------------------
def init_gemini_if_needed() -> None:
    """GEMINI_API_KEY があれば設定する（なければ何もしない）。"""
    if not HAS_GEMINI:
        return
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return
    try:
        genai.configure(api_key=api_key)  # type: ignore[call-arg]
    except Exception:
        # APIキー不正などはあとでオンライン出題が失敗してオフラインへフォールバック
        pass


def list_gemini_models() -> List[str]:
    """
    利用可能な Gemini モデル一覧を返す。
    generateContent に対応しているものだけを対象にし、名前逆ソート。
    """
    if not HAS_GEMINI:
        return []

    try:
        models = genai.list_models()  # type: ignore[call-arg]
    except Exception:
        return []

    names: List[str] = []
    for m in models:
        methods = getattr(m, "supported_generation_methods", [])
        if "generateContent" in methods:
            names.append(m.name)
    return sorted(names, reverse=True)


def get_preferred_model_name() -> Optional[str]:
    """
    設定画面・config.toml を踏まえて「優先モデル名」を返す。
    実際に使えるかはオンライン出題時に再度確認する。
    """
    # 設定画面で指定されている場合を優先
    preferred = st.session_state.get("preferred_model")
    if isinstance(preferred, str) and preferred:
        return preferred

    # config.toml の [gemini].preferred_model
    cfg = load_app_config()
    gem_cfg = cfg.get("gemini")
    if isinstance(gem_cfg, dict):
        p = gem_cfg.get("preferred_model")
        if isinstance(p, str) and p:
            return p

    return None


def choose_model_with_fallback() -> Optional[str]:
    """
    利用可能なモデル一覧から 1 つ選ぶ。
    - preferred_model が利用可能ならそれ
    - それ以外なら一覧の先頭（新しいとみなす）
    - 1つもなければ None
    """
    if not HAS_GEMINI:
        return None

    available = list_gemini_models()
    if not available:
        return None

    preferred = get_preferred_model_name()
    if preferred and preferred in available:
        return preferred

    return available[0]


def build_online_prompt(chapter_label: str, chapter_group: str) -> str:
    """オンライン出題用プロンプト（auto_refill.py と同系統）。"""
    return f"""
あなたは日本語で G検定(JDLA Deep Learning for GENERAL) の高品質な四択問題を作る専門家です。

以下の制約を厳密に守って、指定されたシラバス項目に対応する四択問題を 1 問だけ生成してください。

# シラバス情報
- 分野: {chapter_group}
- 中項目: {chapter_label}

# 出力条件
- G検定本試験レベルの知識を問う。
- 純粋な知識問題・概念理解問題・応用イメージ問題をバランス良く含める。
- 選択肢は必ず 4 つ。紛らわしいが、1つだけ明確に正しい選択肢を含める。
- 難易度は basic / standard / advanced のいずれか。

# 出力フォーマット (JSON 1オブジェクトのみ)
以下のキーを含む JSON オブジェクトとして出力してください:

{{
  "question": "問題文",
  "choices": ["選択肢1", "選択肢2", "選択肢3", "選択肢4"],
  "correct_index": 0,
  "explanation": "正解の理由と他の選択肢が誤りである理由を丁寧に解説する。",
  "difficulty": "basic|standard|advanced"
}}

絶対に JSON 以外の文字列は出力しないでください。
"""


def can_use_online(meta: MetaManager) -> bool:
    """
    オンライン出題を試みてよいかどうかを判定する。
    - GEMINI_API_KEY があるか
    - Quota の remaining_ratio が十分残っているか
    """
    if not HAS_GEMINI:
        return False
    if not os.getenv("GEMINI_API_KEY"):
        return False

    quota = meta.get_quota_manager()
    remaining = quota.get_remaining_ratio()
    # まだ上限未推定なら一旦 OK、とする
    if remaining is None:
        return True

    # config.toml の [quota].near_limit_ratio を参照
    cfg = load_app_config()
    near_ratio = 0.9
    qcfg = cfg.get("quota")
    if isinstance(qcfg, dict):
        r = qcfg.get("near_limit_ratio")
        try:
            near_ratio = float(r)
        except Exception:
            near_ratio = 0.9

    # 残りが 0 に近ければオンラインはやめておく
    return remaining > (1.0 - near_ratio)


def generate_online_question(
    meta: MetaManager,
    chapter_label: str,
) -> Optional[Question]:
    """
    指定された章ラベルからオンライン問題を 1問生成する。
    失敗した場合は None を返し、呼び出し側でオフラインへフォールバックする。
    """
    if not can_use_online(meta):
        return None

    model_name = choose_model_with_fallback()
    if not model_name:
        return None

    chapters = meta.meta.get("chapters", {})
    chapter_group = "ディープラーニング"
    # シラバス情報から group label をざっくり取得
    if isinstance(chapters, dict):
        for _gk, gv in chapters.items():
            sub = gv.get("subchapters", {})
            if not isinstance(sub, dict):
                continue
            for _sk, sv in sub.items():
                if sv.get("label") == chapter_label:
                    chapter_group = gv.get("label", chapter_group)
                    break

    prompt = build_online_prompt(chapter_label, chapter_group)
    approx_prompt_tokens = len(prompt) // 2
    quota = meta.get_quota_manager()

    try:
        model = genai.GenerativeModel(model_name)  # type: ignore[call-arg]
        response = model.generate_content(prompt)  # type: ignore[call-arg]
        text = response.text.strip() if hasattr(response, "text") else ""
        data = json.loads(text)
    except Exception as e:
        msg = str(e)
        if "429" in msg or "Resource exhausted" in msg:
            quota.register_429(message=msg)
        else:
            quota.register_error(message=msg)
        return None

    approx_output_tokens = len(text) // 2
    quota.add_usage(approx_prompt_tokens + approx_output_tokens)

    # Question にマッピング
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    jq: Dict[str, Any] = {
        "id": f"Q_ONLINE_{created_at}",
        "source": "online_runtime",
        "created_at": created_at,
        "domain": "技術分野",  # 詳細に分けたい場合は infer_domain_and_group を共有しても良い
        "chapter_group": chapter_group,
        "chapter_id": chapter_label,
        "difficulty": data.get("difficulty", "standard"),
        "question": data.get("question", "").strip(),
        "choices": data.get("choices", []),
        "correct_index": int(data.get("correct_index", 0)),
        "explanation": data.get("explanation", "").strip(),
        "syllabus": "G2024_v1.3",
    }

    if (
        not jq["question"]
        or not isinstance(jq["choices"], list)
        or len(jq["choices"]) != 4
    ):
        return None

    return Question.from_dict(jq)


# ----------------------------------------------------------------------
#  新しい問題のロード（オンライン/オフライン混在を統合）
# ----------------------------------------------------------------------
def load_new_question(session: SessionState, meta: MetaManager) -> None:
    """
    SessionState に新しい問題をセットする。
    - mode = "online" の場合はオンライン優先（失敗したらオフライン）
    - mode = "offline" の場合はオフラインのみ
    - mode = "auto" の場合はオンライン試行→失敗時オフライン
    いずれの場合も、MetaManager の choose_next_chapter により
    偏りを抑えた章選択を行う。
    """
    all_questions = get_all_questions()
    available_chapters = sorted({q.chapter_id for q in all_questions})
    if not available_chapters:
        st.error("問題バンクが空です。bank/question_bank.jsonl を確認してください。")
        return

    chapter_id = meta.choose_next_chapter(available_chapter_ids=available_chapters)
    if chapter_id is None:
        # フォールバックとしてランダム章
        chapter_id = list(available_chapters)[0]

    mode = session.mode

    # オンラインを試す条件か？
    def try_online() -> Optional[Question]:
        return generate_online_question(meta, chapter_label=chapter_id)

    def try_offline() -> Optional[Question]:
        q = pick_random_from_chapter(chapter_id)
        if q is None:
            q = pick_random_question()
        return q

    question: Optional[Question] = None
    source: str = "offline"

    if mode == "online":
        question = try_online()
        source = "online" if question is not None else "offline"
        if question is None:
            question = try_offline()
    elif mode == "offline":
        question = try_offline()
        source = "offline"
    else:  # auto
        question = try_online()
        source = "online" if question is not None else "offline"
        if question is None:
            question = try_offline()

    if question is None:
        st.error("新しい問題を取得できませんでした。")
        return

    # SessionState にセット
    session.start_new_question(
        question=question,
        source="online" if source == "online" else "offline",
        model_name=get_preferred_model_name() if source == "online" else None,
    )


# ----------------------------------------------------------------------
#  ページ: ホーム
# ----------------------------------------------------------------------
def render_home_page() -> None:
    st.markdown("## 🧠 G検定クイズへようこそ")

    meta = get_meta_manager()
    usage = meta.meta.get("usage", {})
    total = usage.get("total_questions", 0)
    online = usage.get("online_questions", 0)
    offline = usage.get("offline_questions", 0)

    st.write(f"- 累計解答数: **{total} 問**")
    st.write(f"- オンライン出題: **{online} 問**")
    st.write(f"- オフライン出題: **{offline} 問**")

    st.write("---")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("🚀 クイズを始める", use_container_width=True):
            set_page("quiz")
            st.experimental_rerun()
    with col2:
        if st.button("🔁 間違えた問題だけで復習", use_container_width=True):
            set_page("review")
            st.experimental_rerun()

    st.write("")
    col3, col4 = st.columns(2)
    with col3:
        if st.button("📊 学習統計を見る", use_container_width=True):
            set_page("stats")
            st.experimental_rerun()
    with col4:
        if st.button("⚙️ 設定", use_container_width=True):
            set_page("settings")
            st.experimental_rerun()

    st.write("")
    if st.button("❓ 使い方", use_container_width=True):
        set_page("help")
        st.experimental_rerun()


# ----------------------------------------------------------------------
#  ページ: クイズ
# ----------------------------------------------------------------------
def render_quiz_main_page() -> None:
    session = get_session_state()
    meta = get_meta_manager()

    # 問題が無ければ新規ロード
    if not isinstance(session.current_question, Question):
        load_new_question(session, meta)

    quota_status = meta.get_quota_status()
    # 進捗バーは現時点では未実装（None で非表示）
    progress_ratio = None

    # モード表示
    mode_label = session.mode.upper()

    ui_result = render_quiz_page(
        session=session,
        progress_ratio=progress_ratio,
        quota_status=quota_status,
        mode_label=mode_label,
    )

    # 新たに選択された場合のみ answer
    if ui_result["selected_choice"] is not None:
        idx = ui_result["selected_choice"]
        correct = session.answer(idx)
        # meta の usage 更新
        if session.current_question is not None:
            meta.record_usage(
                chapter_id=session.current_question.chapter_id,
                source=session.source,  # "online" / "offline"
            )
            meta.save()
        if correct:
            st.success("正解です！")
        else:
            st.warning("不正解です。解説を確認しましょう。")

    # ナビゲーション
    if ui_result["clicked_next"]:
        load_new_question(session, meta)
        st.experimental_rerun()
    elif ui_result["clicked_prev"]:
        # 履歴の最後の問題を再出題（解答状態はリセットして再挑戦）
        if session.history:
            last = session.history[-1]
            prev_q = get_question_by_id(last.question_id)
            if prev_q is not None:
                session.start_new_question(
                    question=prev_q,
                    source=last.source,
                    model_name=session.model_name,
                )
                st.experimental_rerun()
    elif ui_result["clicked_change_chapter"]:
        # last_chapter_id が更新されているので、choose_next_chapter が
        # 違う章を優先してくれる
        load_new_question(session, meta)
        st.experimental_rerun()

    # ホームに戻るリンク
    if st.button("🏠 ホームに戻る", use_container_width=True):
        set_page("home")
        st.experimental_rerun()


# ----------------------------------------------------------------------
#  ページ: 間違えた問題だけで復習
# ----------------------------------------------------------------------
def render_review_page() -> None:
    session = get_session_state()
    meta = get_meta_manager()

    st.markdown("## 🔁 間違えた問題だけで復習")

    wrongs = [r for r in session.history if not r.correct]
    if not wrongs:
        st.info("まだ間違えた問題の記録がありません。クイズを解いてから利用してください。")
    else:
        st.write(f"これまでに **{len(wrongs)} 問** 間違えています。")
        # 直近 10 件を表示
        rows = []
        for r in reversed(wrongs[-10:]):
            q = get_question_by_id(r.question_id)
            if q is None:
                continue
            rows.append(
                f"- [{q.chapter_id}] {q.question[:40]}..."
            )
        if rows:
            st.markdown("\n".join(rows))

        st.write("---")
        if st.button("ランダムに 1 問復習する", use_container_width=True):
            # 間違えた問題の中からランダムに 1問再出題
            import random

            r = random.choice(wrongs)
            q = get_question_by_id(r.question_id)
            if q is not None:
                # 復習も通常のクイズ画面で出す（オフライン扱いとする）
                session.start_new_question(question=q, source="offline", model_name=None)
                set_page("quiz")
                st.experimental_rerun()

    if st.button("🏠 ホームに戻る", use_container_width=True):
        set_page("home")
        st.experimental_rerun()


# ----------------------------------------------------------------------
#  ページ: 学習統計
# ----------------------------------------------------------------------
def render_stats_page() -> None:
    meta = get_meta_manager()
    st.markdown("## 📊 学習統計")

    usage = meta.meta.get("usage", {})
    total = usage.get("total_questions", 0)
    online = usage.get("online_questions", 0)
    offline = usage.get("offline_questions", 0)

    st.write(f"- 累計解答数: **{total} 問**")
    st.write(f"- オンライン出題: **{online} 問**")
    st.write(f"- オフライン出題: **{offline} 問**")

    st.write("---")
    st.markdown("### 章ごとの出題回数")

    chapter_stats = meta.meta.get("chapter_stats", {})
    if not isinstance(chapter_stats, dict) or not chapter_stats:
        st.info("まだ章ごとの出題統計はありません。")
    else:
        import pandas as pd

        rows = []
        for chap, stat in chapter_stats.items():
            if not isinstance(stat, dict):
                continue
            rows.append(
                {
                    "章": chap,
                    "合計": stat.get("total_questions", 0),
                    "オンライン": stat.get("online_questions", 0),
                    "オフライン": stat.get("offline_questions", 0),
                }
            )
        if rows:
            df = pd.DataFrame(rows).sort_values("合計", ascending=False)
            st.dataframe(df, use_container_width=True)

    if st.button("🏠 ホームに戻る", use_container_width=True):
        set_page("home")
        st.experimental_rerun()


# ----------------------------------------------------------------------
#  ページ: 設定
# ----------------------------------------------------------------------
def render_settings_page() -> None:
    st.markdown("## ⚙️ 設定")

    session = get_session_state()
    cfg = load_app_config()

    st.markdown("### 出題モード")

    mode_map = {"auto": "自動 (オンライン優先+フォールバック)", "online": "オンライン優先", "offline": "オフラインのみ"}
    modes = list(mode_map.keys())
    labels = [mode_map[m] for m in modes]

    try:
        index = modes.index(session.mode)
    except ValueError:
        index = 0

    selected_label = st.radio(
        "出題モード",
        labels,
        index=index,
    )
    selected_mode = modes[labels.index(selected_label)]
    session.mode = selected_mode

    st.write("---")
    st.markdown("### オンラインモデル")

    if not HAS_GEMINI or not os.getenv("GEMINI_API_KEY"):
        st.info("オンライン出題を利用するには GEMINI_API_KEY を環境変数に設定してください。")
    else:
        init_gemini_if_needed()
        models = list_gemini_models()
        if not models:
            st.warning("利用可能な Gemini モデルが取得できませんでした。")
        else:
            preferred = get_preferred_model_name()
            try:
                idx = models.index(preferred) if preferred in models else 0
            except ValueError:
                idx = 0
            selected = st.selectbox("優先的に使うモデル", models, index=idx)
            st.session_state["preferred_model"] = selected
            st.write(f"現在の優先モデル: `{selected}`")

    st.write("---")
    st.markdown("### アプリ情報")
    st.write(f"- アプリ名: **{cfg.get('app', {}).get('name', 'Gtest-Quiz')}**")
    st.write(f"- 言語: **{cfg.get('app', {}).get('language', 'ja')}**")

    if st.button("🏠 ホームに戻る", use_container_width=True):
        set_page("home")
        st.experimental_rerun()


# ----------------------------------------------------------------------
#  ページ: 使い方
# ----------------------------------------------------------------------
def render_help_page() -> None:
    st.markdown("## ❓ 使い方")

    st.markdown(
        """
1. ホーム画面の「🚀 クイズを始める」を押すと問題が出題されます。
2. 四択から 1 つ選ぶと、その場で正誤判定と解説が表示されます。
3. 画面下部の「次の問題 ▶」で次の問題へ進めます。
4. 「章を変える」を押すと、これまであまり出題されていない章が優先されます。
5. 上部のバーに推定クォータメーターが表示され、オンライン出題の使いすぎを防ぎます。
6. 「🔁 間違えた問題だけで復習」では、これまで間違えた問題の一覧やランダム復習ができます。
        """
    )

    st.markdown(
        """
### オンライン出題について

- GEMINI_API_KEY を設定している場合、出題モードが「自動」または「オンライン優先」のときにオンライン出題が行われます。
- 429 (Resource exhausted) が出た場合、その時点の使用量から推定クォータを学習します。
- 推定クォータがほぼ使い切られたと判断された場合、自動的にオフライン出題に切り替わります。
        """
    )

    if st.button("🏠 ホームに戻る", use_container_width=True):
        set_page("home")
        st.experimental_rerun()


# ----------------------------------------------------------------------
#  メイン
# ----------------------------------------------------------------------
def main() -> None:
    st.set_page_config(
        page_title="Gtest-Quiz",
        page_icon="🧠",
        layout="centered",
    )

    # コンフィグ & Gemini 初期化
    load_app_config()
    init_gemini_if_needed()

    # ページ選択
    page = get_page()

    if page == "quiz":
        render_quiz_main_page()
    elif page == "review":
        render_review_page()
    elif page == "stats":
        render_stats_page()
    elif page == "settings":
        render_settings_page()
    elif page == "help":
        render_help_page()
    else:
        # デフォルトはホーム
        set_page("home")
        render_home_page()


if __name__ == "__main__":
    main()
