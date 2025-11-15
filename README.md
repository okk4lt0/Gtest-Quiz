# G検定問題集
G検定（JDLA Deep Learning for GENERAL）の学習用に、  
公式シラバス準拠の四択クイズをオンライン・オフラインで出題するアプリケーションです。

本ツールは OpenAI Gemini API（任意設定）を利用したオンライン出題と、  
ローカルの問題集（question_bank.jsonl）によるオフライン出題の両方に対応しています。

---

## 特徴

- **公式シラバス（2024 v1.3）に準拠した構成**
- **Gemini API によるオンライン問題生成（任意）**
- **限界到達時は自動的にオフライン問題に切り替え**
- **問題バンクの自動補充（GitHub Actions / auto_refill）**
- **章の偏りが少ない出題最適化**
- iPhone（Safari）にも対応した UI

---

## デモ・スクリーンショット
※ 初版では画像は未掲載（追加可能）

---

## 必要環境

- **Python 3.10 以上**
- （任意）Google Gemini API キー  
  → 環境変数 `GEMINI_API_KEY` に設定してください。

---

## インストール

```bash
git clone https://github.com/okk4lt0/Gtest-Quiz.git
cd Gtest-Quiz
pip install -r requirements.txt
