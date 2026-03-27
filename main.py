import os
import sys
import datetime
import pytz
import feedparser
import requests
import google.generativeai as genai

# 環境変数の読み込み
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")

if not GEMINI_API_KEY or not SLACK_WEBHOOK_URL:
    print("Error: GEMINI_API_KEY or SLACK_WEBHOOK_URL is not set.")
    sys.exit(1)

# APIキーの設定
genai.configure(api_key=GEMINI_API_KEY)

# 検索クエリ
QUERY = "人材紹介 OR 転職市場 OR 営業ノウハウ"

def fetch_news():
    """Google News RSSから直近24時間のニュースを取得する"""
    print("Fetching news from Google News RSS...")
    # RSSのURL（hl=ja, gl=JP, ceid=JP:ja）
    url = f"https://news.google.com/rss/search?q={requests.utils.quote(QUERY)}+when:1d&hl=ja&gl=JP&ceid=JP:ja"
    
    feed = feedparser.parse(url)
    entries = feed.entries
    
    if not entries:
        print("No news found in the last 24 hours.")
        return []
        
    news_list = []
    # Geminiの入力制限を考慮し、最大20件程度に絞る
    for i, entry in enumerate(entries[:20]):
        title = entry.title
        link = entry.link
        news_list.append(f"[{i+1}] タイトル: {title}\nURL: {link}\n")
        
    return news_list

def analyze_news(news_list):
    """取得したニュースリストから最も営業に使える1件をAIに選定・要約させる"""
    print("Analyzing news with Gemini API...")
    if not news_list:
        return None
        
    news_text = "\n".join(news_list)
    
    prompt = f"""
あなたは人材紹介業の優秀なマネージャーです。以下のニュース一覧から、キャリアアドバイザー（CA）が求職者との面談で最も使える記事を1つ選び、以下の【出力フォーマット】に厳密に従って出力してください。

【出力フォーマット】
*1.タイトル: [記事のタイトル]*

*2.URL:* [記事のURL]

*3.3行要約:*
> ・[要約1行目]
> ・[要約2行目]
> ・[要約3行目]

*4.営業トークへの活用例:*
> ・【求職者面談（CA向け）切り口①：〇〇な求職者へ】
> [トークスクリプト1]
> 
> ・【求職者面談（CA向け）切り口②：〇〇な求職者へ】
> [トークスクリプト2]

【厳守するルール】
・見出しの1〜4は必ず前後にアスタリスクをつけて太字（*テキスト*）にしてください。
・各見出し（1, 2, 3, 4）の間には、必ず1行の空白行（空行）を入れて見やすくしてください。
・「3.3行要約」と「4.営業トークへの活用例」の本文の先頭には、必ず半角の「> 」（引用タグ）をつけてください。切り口①と②の間の空行にも「> 」をつけ、引用ブロックが途切れないようにしてください。
・企業開拓（RA向け）の視点は一切不要です。
・営業トークは求職者面談（CA向け）に特化し、「転職を迷っている人向け」「市場価値を確かめたい人向け」など、異なる状況・感情の求職者を想定した【2つの違う切り口】で出力してください。

【ニュース一覧】
{news_text}
"""
    
    # モデルの初期化 (gemini-2.5-flashを使用)
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"Error during Gemini API call: {e}")
        return None

def post_to_slack(content):
    """Slack Incoming Webhook経由で通知する"""
    print("Posting to Slack...")
    if not content:
        print("No content to post.")
        return
        
    # JSTの現在時刻を取得
    jst = pytz.timezone('Asia/Tokyo')
    today_str = datetime.datetime.now(jst).strftime("%Y年%m月%d日")
    
    # Slackメッセージの整形
    payload = {
        "text": f"📰 *本日の営業に使えるニュース ({today_str})*\n\n{content}"
    }
    
    response = requests.post(SLACK_WEBHOOK_URL, json=payload)
    if response.status_code != 200:
        print(f"Error posting to Slack: {response.status_code}, {response.text}")
    else:
        print("Successfully posted to Slack!")

def main():
    print("Starting process...")
    news_list = fetch_news()
    if not news_list:
        print("News extraction skipped due to empty list.")
        return
        
    content = analyze_news(news_list)
    if not content:
        print("Analysis failed.")
        return
        
    post_to_slack(content)
    print("Process completed.")

if __name__ == "__main__":
    main()
