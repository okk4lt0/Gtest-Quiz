"""
models.py
======================

アプリ全体で共通して使う「データモデル」だけを定義するモジュール。

ここでは以下を扱う:
- Question        : 1問分の問題データ（JSONLと1対1対応）
- AnswerRecord    : 1回の解答履歴
- SessionState    : 現在のクイズ状態（現在の問題・選択・履歴など）

※オンライン / オフラインやモデル選択などのロジックそのものは
  app.py や専用のモジュールに持たせる。
  models.py はあくまで「構造」を定義する役割に徹する。
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional


QuestionSource = Literal["online", "offline"]
QuestionDifficulty = Literal["basic", "standard", "advanced"]
ModeType = Literal["auto", "online", "offline"]


# ----------------------------------------------------------------------
#  1問分のモデル（question_bank.jsonl と 1:1 で対応）
# ----------------------------------------------------------------------
@dataclass
class Question:
    """
    JSONL 1行分と対応する問題モデル。

    JSONL の例:
    {
      "id": "Q_T_01_01_0001",
      "source": "sample_seed",
      "created_at": "2025-01-01T00:00:00Z",
      "domain": "技術分野",
      "chapter_group": "人工知能とは",
      "chapter_id": "1. 人工知能の定義",
      "difficulty": "basic",
      "question": "...",
      "choices": ["...", "...", "...", "..."],
      "correct_index": 1,
      "explanation": "...",
      "syllabus": "G2024_v1.3"
    }
    """

    id: str
    source: str
    created_at: str
    domain: str
    chapter_group: str
    chapter_id: str
    difficulty: str
    question: str
    choices: List[str]
    correct_index: int
    explanation: str
    syllabus: str

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Question":
        """辞書から Question を生成（不足キーがあれば例外をそのまま投げる）"""
        return cls(
            id=data["id"],
            source=data.get("source", "unknown"),
            created_at=data.get("created_at", ""),
            domain=data.get("domain", ""),
            chapter_group=data.get("chapter_group", ""),
            chapter_id=data.get("chapter_id", ""),
            difficulty=data.get("difficulty", "standard"),
            question=data.get("question", ""),
            choices=list(data.get("choices", [])),
            correct_index=int(data.get("correct_index", 0)),
            explanation=data.get("explanation", ""),
            syllabus=data.get("syllabus", ""),
        )

    def to_dict(self) -> Dict[str, Any]:
        """JSONL 互換の dict に変換"""
        return asdict(self)

    def is_correct(self, choice_index: int) -> bool:
        """選択肢インデックスが正解かどうか"""
        return choice_index == self.correct_index


# ----------------------------------------------------------------------
#  解答履歴 1 レコード
# ----------------------------------------------------------------------
@dataclass
class AnswerRecord:
    """
    1回分の解答結果を記録するモデル。
    meta.json の usage とは別に、セッション中の履歴として使う。
    """

    question_id: str
    chapter_id: str
    correct: bool
    source: QuestionSource
    answered_at: str

    @classmethod
    def create(
        cls,
        question: Question,
        correct: bool,
        source: QuestionSource,
        answered_at: Optional[datetime] = None,
    ) -> "AnswerRecord":
        if answered_at is None:
            answered_at = datetime.now(timezone.utc)
        return cls(
            question_id=question.id,
            chapter_id=question.chapter_id,
            correct=correct,
            source=source,
            answered_at=answered_at.isoformat(),
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AnswerRecord":
        return cls(
            question_id=data["question_id"],
            chapter_id=data.get("chapter_id", ""),
            correct=bool(data.get("correct", False)),
            source=data.get("source", "offline"),  # デフォルトは offline
            answered_at=data.get("answered_at", ""),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ----------------------------------------------------------------------
#  セッション状態
# ----------------------------------------------------------------------
@dataclass
class SessionState:
    """
    現在のクイズ状態を持つモデル。

    - mode              : auto / online / offline
    - current_question  : 今表示している問題
    - selected_index    : 選択済みの選択肢インデックス（未回答は None）
    - is_correct        : 正解なら True, 不正解なら False, 未回答は None
    - source            : 現在の問題が online / offline のどちら由来か
    - model_name        : online 時に使用したモデル名（オフラインなら None）
    - history           : セッション中の解答履歴
    """

    mode: ModeType = "auto"
    current_question: Optional[Question] = None
    selected_index: Optional[int] = None
    is_correct: Optional[bool] = None
    source: QuestionSource = "offline"
    model_name: Optional[str] = None
    history: List[AnswerRecord] = field(default_factory=list)

    # --------------------------------------------------
    #  セッション操作
    # --------------------------------------------------
    def start_new_question(
        self,
        question: Question,
        source: QuestionSource = "offline",
        model_name: Optional[str] = None,
    ) -> None:
        """
        新しい問題を表示する前に呼ぶ。
        以前の回答状態をリセットし、current_question を更新する。
        """
        self.current_question = question
        self.selected_index = None
        self.is_correct = None
        self.source = source
        self.model_name = model_name

    def answer(self, choice_index: int) -> bool:
        """
        現在の問題に対する解答を記録し、正誤を返す。
        current_question が無い場合は常に False を返す。
        """
        self.selected_index = choice_index

        if self.current_question is None:
            self.is_correct = False
            return False

        correct = self.current_question.is_correct(choice_index)
        self.is_correct = correct

        record = AnswerRecord.create(
            question=self.current_question,
            correct=correct,
            source=self.source,
        )
        self.history.append(record)
        return correct

    # --------------------------------------------------
    #  シリアライズ／デシリアライズ
    # --------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        """
        JSON や session_state に入れられる形の dict に変換。
        ネストしている dataclass も dict に展開する。
        """
        data: Dict[str, Any] = {
            "mode": self.mode,
            "selected_index": self.selected_index,
            "is_correct": self.is_correct,
            "source": self.source,
            "model_name": self.model_name,
            "current_question": (
                self.current_question.to_dict() if self.current_question else None
            ),
            "history": [r.to_dict() for r in self.history],
        }
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionState":
        """
        dict から SessionState を復元する。
        キー不足があっても安全に復元できるようにデフォルト値を使う。
        """
        q_data = data.get("current_question")
        question = Question.from_dict(q_data) if isinstance(q_data, dict) else None

        history_data = data.get("history", [])
        history: List[AnswerRecord] = []
        if isinstance(history_data, list):
            for item in history_data:
                if isinstance(item, dict):
                    history.append(AnswerRecord.from_dict(item))

        return cls(
            mode=data.get("mode", "auto"),
            current_question=question,
            selected_index=data.get("selected_index"),
            is_correct=data.get("is_correct"),
            source=data.get("source", "offline"),
            model_name=data.get("model_name"),
            history=history,
        )
