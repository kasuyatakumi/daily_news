import os
import re
import sys
import datetime
import difflib
import concurrent.futures

import pytz
import feedparser
import requests
import trafilatura
import google.generativeai as genai

# 環境変数の読み込み
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_CHANNEL_ID = os.getenv("SLACK_CHANNEL_ID")
AI_INSIGHT = os.getenv("AI_INSIGHT", "")

if not GEMINI_API_KEY or not SLACK_BOT_TOKEN or not SLACK_CHANNEL_ID:
    print("Error: GEMINI_API_KEY, SLACK_BOT_TOKEN, or SLACK_CHANNEL_ID is not set.")
    sys.exit(1)

# APIキーの設定
genai.configure(api_key=GEMINI_API_KEY)

# 検索クエリ（営業スキル・営業の考え方・転職市場・CAに活かせる内容を狙う）
# ※「営業」単独は「営業再開/営業運転」など店舗営業のノイズを拾うため、具体語に限定
QUERY = "人材紹介 OR 人材業界 OR 転職市場 OR 求人倍率 OR 労働市場 OR 営業ノウハウ OR 営業スキル OR キャリアアドバイザー OR リスキリング"

# 候補数・本文取得の調整パラメータ
MAX_ENTRIES = 40        # RSSから取得する最大件数
MAX_FETCH_BODIES = 12   # 本文を取得して選定に使う上位件数
BODY_MAX_CHARS = 1000   # AIに渡す本文の最大文字数

# 記事取得用の共通ヘッダ
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
}


def _normalize_title(title):
    """重複判定用にタイトルを正規化する（末尾の媒体名・記号を除去）"""
    # Google Newsのタイトルは「記事タイトル - 媒体名」形式が多い
    base = re.sub(r"\s*[-|｜].*$", "", title)
    base = re.sub(r"[^0-9a-zA-Z぀-ヿ一-鿿]", "", base)
    return base.lower()


def fetch_news():
    """Google News RSSから直近48時間のニュース候補を取得し、重複を除いて返す"""
    print("Fetching news from Google News RSS...")
    url = (
        f"https://news.google.com/rss/search?q={requests.utils.quote(QUERY)}"
        f"+when:2d&hl=ja&gl=JP&ceid=JP:ja"
    )

    feed = feedparser.parse(url)
    entries = feed.entries

    if not entries:
        print("No news found in the last 48 hours.")
        return []

    candidates = []
    seen_titles = []
    for entry in entries[:MAX_ENTRIES]:
        title = entry.get("title", "").strip()
        link = entry.get("link", "").strip()
        if not title or not link:
            continue

        # 近似重複の排除
        norm = _normalize_title(title)
        if any(difflib.SequenceMatcher(None, norm, s).ratio() > 0.85 for s in seen_titles):
            continue
        seen_titles.append(norm)

        source = ""
        if entry.get("source") and entry.source.get("title"):
            source = entry.source.title
        published = entry.get("published", "")

        candidates.append({
            "title": title,
            "link": link,
            "source": source,
            "published": published,
            "summary": re.sub(r"<[^>]+>", "", entry.get("summary", "")).strip(),
            "body": "",
        })

    print(f"Collected {len(candidates)} unique candidates.")
    return candidates


def fetch_article_text(url):
    """記事URL（Google Newsのリダイレクト含む）から本文と最終URLを取得する"""
    try:
        res = requests.get(url, headers=HTTP_HEADERS, timeout=8, allow_redirects=True)
        final_url = res.url
        text = trafilatura.extract(res.text) or ""
        return text.strip()[:BODY_MAX_CHARS], final_url
    except Exception as e:
        print(f"Article fetch error: {e}")
        return "", url


def enrich_with_bodies(candidates):
    """上位候補の本文を並列取得して付与する"""
    targets = candidates[:MAX_FETCH_BODIES]
    print(f"Fetching article bodies for top {len(targets)} candidates...")

    def _work(c):
        body, final_url = fetch_article_text(c["link"])
        c["body"] = body
        c["final_url"] = final_url
        return c

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(_work, targets))

    return targets


def shorten_url(url):
    """is.gd APIで短縮URLに変換する（失敗時は元URLを返す）"""
    try:
        res = requests.get(
            "https://is.gd/create.php",
            params={"format": "simple", "url": url},
            timeout=5,
        )
        if res.status_code == 200 and res.text.startswith("http"):
            return res.text
    except Exception as e:
        print(f"URL shortener error: {e}")
    return url


def analyze_news(candidates, ai_insight=""):
    """候補から最も営業・CAに使える1件をAIに選定させ、要約・トークを生成する"""
    print("Analyzing news with Gemini API...")
    if not candidates:
        return None

    # AIに渡す候補一覧（本文 or RSS要約 を根拠として提示）
    lines = []
    for i, c in enumerate(candidates):
        context = c["body"] or c["summary"] or "(本文取得不可。タイトルのみで判断)"
        lines.append(
            f"[{i+1}] タイトル: {c['title']}\n"
            f"ソース: {c['source']} / 日付: {c['published']}\n"
            f"本文: {context}\n"
        )
    news_text = "\n".join(lines)

    insight_prompt = ""
    if ai_insight:
        insight_prompt = f"""
過去の評価データに基づいた最新の選定基準： {ai_insight}
上記の知見を最大限に考慮し、サイグナス信託のCA（キャリアアドバイザー）に最も刺さる記事を選定してください。
"""

    prompt = f"""
あなたは人材紹介業の優秀なマネージャーです。以下のニュース候補一覧から、キャリアアドバイザー（CA）が求職者との面談で最も使える記事を1つ選んでください。
各候補には本文（または要約）を添えています。必ず本文の中身を根拠に判断し、推測で要約しないでください。
{insight_prompt}
【選定の最優先観点】
・営業スキル・営業の考え方・転職市場の動向・キャリアアドバイザーの面談に活かせる内容であること。
・同じような記事が複数ある場合は、最も具体的で信頼できるソースを優先すること。

【出力ルール】
1行目に、選んだ候補の番号だけを「SELECTED: 数字」の形式で出力してください。
2行目に、選定理由を「REASON: 〜」で1行出力してください。
3行目以降は、以下の【出力フォーマット】に厳密に従って出力してください（タイトルとURLの行は出力しないでください）。

【出力フォーマット】
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
・見出しの3〜4は必ず前後にアスタリスクをつけて太字（*テキスト*）にしてください。
・見出し3と4の間には、必ず1行の空白行（空行）を入れて見やすくしてください。
・「3.3行要約」と「4.営業トークへの活用例」の本文の先頭には、必ず半角の「> 」（引用タグ）をつけてください。切り口①と②の間の空行にも「> 」をつけ、引用ブロックが途切れないようにしてください。
・企業開拓（RA向け）の視点は一切不要です。
・営業トークは求職者面談（CA向け）に特化し、「転職を迷っている人向け」「市場価値を確かめたい人向け」など、異なる状況・感情の求職者を想定した【2つの違う切り口】で出力してください。

【ニュース候補一覧】
{news_text}
"""

    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        response = model.generate_content(prompt)
        raw = response.text
    except Exception as e:
        print(f"Error during Gemini API call: {e}")
        return None

    # 選定番号・理由・本文ブロックを分離
    selected_index = 0
    reason = ""
    body_lines = []
    for line in raw.splitlines():
        m_sel = re.match(r"\s*SELECTED\s*[:：]\s*(\d+)", line)
        m_rea = re.match(r"\s*REASON\s*[:：]\s*(.*)", line)
        if m_sel:
            selected_index = int(m_sel.group(1)) - 1
            continue
        if m_rea:
            reason = m_rea.group(1).strip()
            continue
        body_lines.append(line)

    if selected_index < 0 or selected_index >= len(candidates):
        print(f"Warning: invalid SELECTED index ({selected_index+1}). Falling back to 1st candidate.")
        selected_index = 0

    selected = candidates[selected_index]
    print(f"Selected: [{selected_index+1}] {selected['title']}")
    print(f"Reason: {reason}")

    # 先頭の空行を除去して要約・トーク本文を整える
    section_3_4 = "\n".join(body_lines).strip()

    # URLは選定後の1件だけ短縮（リダイレクト解決後の実URLを優先）
    target_url = selected.get("final_url") or selected["link"]
    short_url = shorten_url(target_url)

    # 既存のSlackレイアウトを完全に踏襲して再構成（1.タイトル / 2.URL はPython側で確定）
    content = (
        f"*1.タイトル: {selected['title']}*\n\n"
        f"*2.URL:* {short_url}\n\n"
        f"{section_3_4}"
    )
    return content


def post_to_slack(content):
    """Slack Bot APIを利用して通知し、評価用リアクションを付与する"""
    print("Posting to Slack...")
    if not content:
        print("No content to post.")
        return

    # JSTの現在時刻を取得
    jst = pytz.timezone('Asia/Tokyo')
    today_str = datetime.datetime.now(jst).strftime("%Y年%m月%d日")

    evaluation_text = """```
【📊 今日のニュース評価】
今後の配信精度向上のため、ポチッと評価をお願いします！
🔥：最高！（面談で即出しレベル）
👍：参考になる！（知識としてストック）
🤔：うーん…（現場では使いにくいかも）
```"""

    # Slackメッセージの整形
    post_text = f"📰 *本日の営業に使えるニュース ({today_str})*\n\n{content}\n\n{evaluation_text}"

    headers = {
        "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
        "Content-Type": "application/json; charset=utf-8"
    }

    payload = {
        "channel": SLACK_CHANNEL_ID,
        "text": post_text,
        "unfurl_links": False,
        "unfurl_media": False
    }

    post_url = "https://slack.com/api/chat.postMessage"
    response = requests.post(post_url, headers=headers, json=payload)

    if response.status_code != 200:
        print(f"Error posting to Slack: {response.status_code}, {response.text}")
        return

    res_json = response.json()
    if not res_json.get("ok"):
        print(f"Slack API error: {res_json.get('error')}")
        return

    print("Successfully posted to Slack!")
    ts = res_json.get("ts")

    # リアクション（スタンプ）を自動付与
    reactions = ["fire", "+1", "thinking_face"]
    reaction_url = "https://slack.com/api/reactions.add"

    for reaction in reactions:
        reaction_payload = {
            "channel": SLACK_CHANNEL_ID,
            "timestamp": ts,
            "name": reaction
        }
        reaction_res = requests.post(reaction_url, headers=headers, json=reaction_payload)
        reaction_json = reaction_res.json()
        if not reaction_json.get("ok"):
            print(f"Failed to add reaction '{reaction}': {reaction_json.get('error')}")

def main():
    print("Starting process...")
    candidates = fetch_news()
    if not candidates:
        print("News extraction skipped due to empty list.")
        return

    candidates = enrich_with_bodies(candidates)

    content = analyze_news(candidates, AI_INSIGHT)
    if not content:
        print("Analysis failed.")
        return

    post_to_slack(content)
    print("Process completed.")

if __name__ == "__main__":
    main()
