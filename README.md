# キャリアアドバイザー向け 営業ニュース配信システム

人材紹介業向けの「毎日の営業トーク（求職者・企業へのアプローチ）に使えるニュース」を自動抽出し、Slackへ配信するシステムです。

## 構成
- **GAS (Google Apps Script)**: 毎日9:00にGitHub Actionsをキックするトリガー。デフォルトの実行時間のブレを無くすため、2段階トリガー方式を採用しています。
- **GitHub Actions**: Pythonプログラムの実行基盤（毎日・手動実行用）。
- **Python スクリプト**: Google News RSSのスクレイピング、Gemini APIによる記事選定・文章生成、Slackへの投稿。

## セットアップ手順

### 1. 外部サービスの準備
事前に以下のAPIキーやトークンなどを準備してください。
1. **Gemini API Key**
   - [Google AI Studio](https://aistudio.google.com/) からAPIキーを発行します。
2. **Slack Incoming Webhook URL**
   - Slackアプリの「Incoming WebHooks」を作成・追加し、投稿先チャンネルを指定してWebhook URLを取得します。
3. **GitHub Personal Access Token (PAT)**
   - GitHubの [Personal Access Tokens](https://github.com/settings/tokens) ページでトークン（classic推奨、またはFine-grained）を発行します。
   - スコープとして `workflow` （または `repo` 全員）にチェックを入れてください。

### 2. GitHub リポジトリの設定
1. 本コード一式をGitHubの新規リポジトリにPushします。
2. リポジトリの `Settings > Secrets and variables > Actions` を開き、以下の2つの **Repository secrets** を追加します。
   - `GEMINI_API_KEY`: 取得したGeminiのAPIキー
   - `SLACK_WEBHOOK_URL`: SlackのWebhook URL

### 3. GAS (Google Apps Script) の設定とデプロイ
1. Google Driveから新規のGoogle Apps Scriptプロジェクトを作成します。
2. `gas_trigger.gs` の内容をコピーしてGAS側（例: `コード.gs`）に貼り付けて保存します。
3. GASの左メニューの `プロジェクトの設定（歯車アイコン） > スクリプト プロパティ` を開き、以下の3つを追加します。
   - `GITHUB_PAT`: GitHubで発行したPAT
   - `REPO_OWNER`: GitHubのユーザー名（またはOrganization名）
   - `REPO_NAME`: 本システムをPushしたリポジトリ名 (例: `daily_news`)
4. 初回のトリガー設定を行います。
   - GAS左メニューの `トリガー（時計アイコン）` をクリック。
   - `トリガーを追加` ボタンを押す。
   - 実行する関数: `setTrigger`
   - イベントのソース: `時間主導型`
   - 時間ベースのトリガーのタイプ: `日付ベースのタイマー`
   - 時刻を選択: `午前1時〜2時`（好きな深夜の時間帯で可）
   - 保存してアクセス権限を許可します。
   
これで設定は完了です。毎日指定の深夜時間帯に `setTrigger` が起動し、自動で当日のピッタリ9:00にGitHub Actionsを起動するワンタイムトリガーを生成します。

## 手動での実行テスト
1. GitHubの対象リポジトリから `Actions` タブを開きます。
2. 左メニューから `Daily News Delivery to Slack` を選択します。
3. `Run workflow` をクリックすると即座に処理が実行されます（Slackへの投稿テストが可能です）。
