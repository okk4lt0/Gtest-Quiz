# G検定クイズアプリ（Gemini対応・自動問題補充）

G検定対策用の四択クイズアプリです。  
オンラインでは Google Gemini を利用して問題を生成し、失敗した場合はローカルの問題バンクから自動で出題します。  
GitHub Actions により、毎日シラバスからの自動問題生成とバンクへの追加が行われます。

---

## 機能概要

### 1. オンライン出題（Gemini API）
- Google Gemini API で新しい四択問題を生成  
- 利用可能なモデル一覧を API から取得し、最新モデルを優先使用  
- スキーマ検証により安全な JSON 出力のみ採用  
- 成功した問題は問題バンクに自動追加

### 2. オフライン出題（バンク）
- オンラインが失敗すると自動的にオフラインへフォールバック  
- bank/question_bank.jsonl から読み込み  
- 1 行 1 問の JSON Lines 形式  
- 最低限のデフォルト問題も内蔵されており、空でも動作可能

### 3. 自動問題補充（GitHub Actions）
- 毎日決まった時間（cron）に自動補充  
- PDF（JDLA Gtest Syllabus 2024 v1.3）からテキスト抽出  
- 生成した問題を bank/question_bank.jsonl に追記  
- 重複設問を避けるための既存チェック付き  
- ワークフロー: `.github/workflows/auto_refill.yml`  
- スクリプト: `tools/auto_refill.py`

### 4. 使用量メーター（クォータ推定）
- オンライン出題数を自動記録  
- bank/quota_stats.json を使用して履歴管理  
- Gemini の公式クォータは取得できないため「推定メーター」  
- 上限値（1 日、1 分）はユーザーが調整可能  
- 過去ログから学習し、より精度の高い推定が可能

---

## リポジトリ構成（主要ファイル）

•	Gtest-Quiz/
	•	app.py
	•	requirements.txt
	•	.streamlit/
	•	config.toml
	•	data/
	•	JDLA_Gtest_Syllabus_2024_v1.3_JP.pdf
	•	bank/
	•	.gitignore
	•	latest.json
	•	question_bank.jsonl
	•	quota_stats.json
	•	tools/
	•	auto_refill.py
	•	.github/
	•	workflows/
	•	auto_refill.yml

---

## セットアップ

### 必要なもの
- Python 3.11 以上  
- Google Gemini API Key  
- GitHub Actions を使う場合、Secrets に GEMINI_API_KEY を登録

### 依存パッケージのインストール
pip install -r requirements.txt

### 環境変数（ローカル実行の場合）
export GEMINI_API_KEY="あなたのAPIキー"

---

## アプリの起動（ローカル）

streamlit run app.py

---

## 使い方

1. アプリ起動後、利用可能な Gemini モデルが自動で取得されます  
2. 「AIで問題を作る」を押すとオンライン出題（成功すれば自動保存）  
3. 失敗したら自動でオフライン出題へ切り替え  
4. 回答すると正誤と解説が表示  
5. 「もう一問出す」で次の問題へ  
6. 画面右側などに使用量メーターが表示されます  
   （これは推定であり、公式クォータの代替ではありません）

---

## GitHub Actions 自動補充

### Secrets へ登録
- Repository Settings → Secrets → Actions  
- GEMINI_API_KEY を追加  

### 手動実行
- GitHub → Actions → Auto Refill Question Bank → Run workflow

### 自動補充の流れ
1. 毎日決まった時間に workflow が起動  
2. PDF を読み込み → Gemini に問題生成依頼  
3. 生成が成功（かつ重複なし）なら question_bank.jsonl に追記  
4. コミットして push

---

## 注意点

- 使用量メーターは Gemini 公式のクォータ API が存在しないため「推定」です  
- バンク内の問題は公開リポジトリでは第三者に読まれます  
- Gemini の使用量や課金状況は Google Cloud コンソールで必ず確認してください
