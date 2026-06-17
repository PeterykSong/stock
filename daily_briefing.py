#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
daily_briefing.py

1) GitHub의 stock_prices_result.md 를 읽어 관심 종목(watchlist)을 추출
2) Google 뉴스 RSS 에서 국내/국제/미국/종목 뉴스를 수집
3) Anthropic API(Claude)로 카테고리별 10건씩 요약
4) daily_briefing.md 생성 (옵션: git 자동 커밋/푸시)

필요 패키지:  pip install anthropic   (선택: python-dotenv)
환경설정:     스크립트와 같은 폴더의 .env 파일 또는 OS 환경변수
              (ANTHROPIC_API_KEY 등). 둘 다 있으면 OS 환경변수가 우선.
"""

import csv
import os
import sys
import html
import datetime
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import anthropic


# ───────────────────────── .env 로드 ─────────────────────────
def _load_env_file(path: str) -> None:
    """python-dotenv가 있으면 사용, 없으면 내장 파서로 .env를 읽는다.
    이미 설정된 OS 환경변수는 덮어쓰지 않는다(우선순위: OS > .env)."""
    if not os.path.exists(path):
        return
    try:
        from dotenv import load_dotenv  # python-dotenv (선택 의존성)
        load_dotenv(path, override=False)
        return
    except ImportError:
        pass
    # ── 내장 폴백 파서 ──
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            # 따옴표 및 인라인 주석 정리
            val = val.split(" #", 1)[0].strip().strip('"').strip("'")
            if key:
                os.environ.setdefault(key, val)


# 스크립트와 같은 폴더의 .env 를 먼저 로드 (설정값을 읽기 전에 실행)
_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
_load_env_file(_ENV_PATH)


# ───────────────────────── 설정 ─────────────────────────
GITHUB_RAW = os.environ.get(
    "STOCK_SOURCE_URL",
    "https://raw.githubusercontent.com/PeterykSong/stock/main/stock_prices_result.md",
)
OUTPUT_PATH = os.environ.get("BRIEFING_OUTPUT", "daily_briefing.md")
SCREENER_CSV = os.environ.get(
    "SCREENER_CSV",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "kospi_screener.csv"),
)
MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")  # opus-4-8 / haiku-4-5 도 가능
KST = datetime.timezone(datetime.timedelta(hours=9))

# 카테고리별 Google 뉴스 RSS (토픽 헤드라인)
TOPIC_FEEDS = {
    "국내 주요뉴스": "https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko",
    "국제 주요뉴스": "https://news.google.com/rss/headlines/section/topic/WORLD?hl=ko&gl=KR&ceid=KR:ko",
    "미국 주요뉴스": "https://news.google.com/rss/headlines/section/topic/NATION?hl=en-US&gl=US&ceid=US:en",
}
SEARCH_RSS = "https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko"

UA = {"User-Agent": "Mozilla/5.0 (compatible; daily-briefing-bot/1.0)"}


# ───────────────────────── 유틸 ─────────────────────────
def fetch(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def parse_rss(xml_text: str, limit: int = 15) -> list:
    """Google 뉴스 RSS → [{title, link, source, pub}]"""
    items = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return items
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        if not title:
            continue
        src_el = it.find("source")
        items.append(
            {
                "title": html.unescape(title),
                "link": (it.findtext("link") or "").strip(),
                "source": (src_el.text.strip() if src_el is not None and src_el.text else ""),
                "pub": (it.findtext("pubDate") or "").strip(),
            }
        )
        if len(items) >= limit:
            break
    return items


def get_watchlist(md_text: str) -> list:
    """stock_prices_result.md 의 표에서 (종목명, 티커) 추출"""
    pairs = []
    for line in md_text.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 2:
            continue
        name, ticker = cells[0], cells[1]
        if name in ("종목", "") or set(name) <= set("-: "):
            continue
        pairs.append((name, ticker))
    return pairs


def parse_stock_table(md_text: str) -> list:
    """stock_prices_result.md 전체 행 파싱 → [{name, ticker, price, change, currency, date}]"""
    rows = []
    for line in md_text.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 6:
            continue
        name = cells[0]
        if name in ("종목", "") or set(name) <= set("-: "):
            continue
        rows.append({
            "name": name,
            "ticker": cells[1],
            "price": cells[2],
            "change": cells[3],
            "currency": cells[4],
            "date": cells[5],
        })
    return rows


def format_stock_table(rows: list) -> str:
    """주가 데이터를 마크다운 테이블로 포맷"""
    if not rows:
        return "_(주가 데이터 없음)_"
    lines = ["| 종목 | 티커 | 종가 | 등락률 | 통화 |",
             "|---|---|---:|---:|---|"]
    for r in rows:
        try:
            chg = float(r["change"])
            chg_str = f"{chg:+.2f}%" if chg != 0 else "0.00%"
        except ValueError:
            chg_str = r["change"]
        lines.append(f"| {r['name']} | {r['ticker']} | {r['price']} | {chg_str} | {r['currency']} |")
    return "\n".join(lines)


def get_top_screener_stocks(csv_path: str, top_n: int = 10) -> list:
    """kospi_screener.csv 상위 top_n 종목의 (Name, Symbol) 목록을 반환"""
    if not os.path.exists(csv_path):
        return []
    pairs = []
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            name, symbol = row.get("Name"), row.get("Symbol")
            if name and symbol:
                pairs.append((name, symbol))
            if len(pairs) >= top_n:
                break
    return pairs


def collect_screener_news(stocks: list) -> list:
    """스크리너 상위 종목별로 뉴스 1건씩 검색"""
    items = []
    for name, symbol in stocks:
        url = SEARCH_RSS.format(q=urllib.parse.quote(name))
        try:
            articles = parse_rss(fetch(url), limit=1)
        except Exception as e:
            print(f"[warn] '{name}' 스크리너 뉴스 수집 실패: {e}", file=sys.stderr)
            articles = []
        article = articles[0] if articles else None
        items.append({"name": name, "symbol": symbol, "article": article})
    return items


def format_screener_news(items: list) -> str:
    """스크리너 상위 종목 뉴스를 마크다운 목록으로 포맷"""
    if not items:
        return "_(스크리너 결과가 없습니다)_"
    lines = []
    for it in items:
        art = it["article"]
        if art:
            src = f" ({art['source']})" if art.get("source") else ""
            lines.append(f"- **{it['name']}({it['symbol']})**: [{art['title']}]({art['link']}){src}")
        else:
            lines.append(f"- **{it['name']}({it['symbol']})**: _(관련 뉴스 없음)_")
    return "\n".join(lines)


def collect_topic(label: str, url: str) -> list:
    try:
        return parse_rss(fetch(url), limit=15)
    except Exception as e:
        print(f"[warn] '{label}' 수집 실패: {e}", file=sys.stderr)
        return []


def collect_stock_news(watchlist: list) -> list:
    """관심 종목별로 검색 RSS 수집 후 합침"""
    merged, seen = [], set()
    for name, ticker in watchlist:
        # 한국 종목명은 그대로, 미국 티커는 'TICKER stock'으로 검색
        query = name if any("\uac00" <= ch <= "\ud7a3" for ch in name) else f"{ticker} stock"
        url = SEARCH_RSS.format(q=urllib.parse.quote(query))
        try:
            for art in parse_rss(fetch(url), limit=4):
                key = art["title"]
                if key not in seen:
                    seen.add(key)
                    art["_watch"] = f"{name}({ticker})"
                    merged.append(art)
        except Exception as e:
            print(f"[warn] '{name}' 뉴스 수집 실패: {e}", file=sys.stderr)
    return merged


# ───────────────────────── 요약 ─────────────────────────
def summarize(client, label: str, articles: list, count: int = 10) -> str:
    if not articles:
        return "_(수집된 뉴스가 없습니다)_"
    headlines = "\n".join(
        f"- {a['title']}"
        + (f" [{a.get('_watch')}]" if a.get("_watch") else "")
        + (f" ({a['source']})" if a.get("source") else "")
        for a in articles
    )
    prompt = f"""다음은 '{label}' 관련 Google 뉴스 헤드라인 모음입니다.
중복·광고·운세·연예가십·낚시성 항목은 제외하고, 중요도가 높은 순으로 정확히 {count}건을 선정해
각 항목을 한국어 한 문장(40자 내외)으로 요약하세요.

규칙:
- 출력은 번호 매긴 목록만. 머리말/맺음말 금지.
- 형식: `N. 요약 — (출처)`
- 헤드라인을 그대로 베끼지 말고 핵심만 자연스럽게 재서술.

[헤드라인]
{headlines}
"""
    msg = client.messages.create(
        model=MODEL,
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in msg.content if b.type == "text").strip()


# ───────────────────────── 메인 ─────────────────────────
def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit(
            "[error] ANTHROPIC_API_KEY 가 없습니다. "
            f"스크립트 폴더의 .env 파일({_ENV_PATH})에 "
            "ANTHROPIC_API_KEY=sk-ant-... 를 추가하거나 OS 환경변수로 설정하세요."
        )
    client = anthropic.Anthropic(api_key=api_key)

    now = datetime.datetime.now(KST)
    print(f"[info] 브리핑 생성 시작: {now:%Y-%m-%d %H:%M} KST")

    # 1) 종목 표 로드
    try:
        stock_md = fetch(GITHUB_RAW)
        watchlist = get_watchlist(stock_md)
        stock_rows = parse_stock_table(stock_md)
    except Exception as e:
        print(f"[warn] 종목 파일 로드 실패({e}) — 종목 뉴스는 건너뜁니다.", file=sys.stderr)
        stock_md, watchlist, stock_rows = "", [], []
    print(f"[info] 관심 종목 {len(watchlist)}개: {', '.join(n for n, _ in watchlist)}")

    # 2) 뉴스 수집
    sections = {}
    for label, url in TOPIC_FEEDS.items():
        sections[label] = collect_topic(label, url)
    sections["주식 종목관련 주요뉴스"] = collect_stock_news(watchlist)

    # 3) 카테고리별 요약
    parts = []
    icons = {
        "국내 주요뉴스": "🇰🇷",
        "국제 주요뉴스": "🌍",
        "미국 주요뉴스": "🇺🇸",
        "주식 종목관련 주요뉴스": "📈",
    }
    order = ["국내 주요뉴스", "국제 주요뉴스", "미국 주요뉴스", "주식 종목관련 주요뉴스"]
    for label in order:
        print(f"[info] 요약 중: {label} ({len(sections[label])}건 수집)")
        summary = summarize(client, label, sections[label], count=10)
        parts.append(f"## {icons.get(label,'')} {label}\n\n{summary}\n")

    # 4) 스크리너 상위 종목 뉴스
    top_screener_stocks = get_top_screener_stocks(SCREENER_CSV, top_n=10)
    print(f"[info] 스크리너 상위 종목 {len(top_screener_stocks)}개 뉴스 검색 중")
    screener_news = collect_screener_news(top_screener_stocks)
    screener_news_md = format_screener_news(screener_news)

    # 5) 마크다운 작성
    stock_table = format_stock_table(stock_rows)
    header = (
        f"# 📰 데일리 브리핑 ({now:%Y-%m-%d} KST)\n\n"
        f"> 생성 시각: {now:%Y-%m-%d %H:%M} KST / 뉴스 소스: Google 뉴스\n\n"
        f"## 📊 관심 종목 주가\n\n{stock_table}\n\n---\n\n"
        f"## 🏆 KOSPI 스크리너 상위 종목 뉴스\n\n{screener_news_md}\n\n---\n\n"
    )
    footer = (
        "\n---\n*본 브리핑은 Google 뉴스 헤드라인을 Claude로 자동 요약한 것으로, "
        "투자 판단의 책임은 이용자에게 있습니다.*\n"
    )
    md = header + "\n".join(parts) + footer

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"[done] 저장 완료 → {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
