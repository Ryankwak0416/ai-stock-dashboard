# 진단용 3차 — stock.naver.com 새 API 경로와 호출 형식 (수정 후 삭제)
import re, requests
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
     "Accept": "*/*", "Referer": "https://stock.naver.com/"}
PAT = re.compile(r'["\'`]((?:https://[a-z.]*naver\.com)?/(?:front-)?api/[^"\'`\s<>]{3,140})')
CTX = ["investor-trend", "rankings/v2/domestic", "chart/domestic", "securityService/chart", "tradingValue", "TradingValue", "dealTrend"]
pages = ["https://stock.naver.com/market/stock/kr", "https://stock.naver.com/domestic/index/KOSPI",
         "https://stock.naver.com/domestic/index/KOSPI/total", "https://stock.naver.com/market/stock/kr/investor"]
alljs, found, seen = [], set(), set()
for base in pages:
    try:
        r = requests.get(base, headers=H, timeout=20)
        print(f"page {base} status={r.status_code} len={len(r.text)}")
        html = r.text
    except Exception as e:
        print("page ERROR", base, e); continue
    found |= set(PAT.findall(html))
    alljs.append(html)
    for s in re.findall(r'<script[^>]+src="([^"]+)"', html):
        if s.startswith("//"): s = "https:" + s
        elif s.startswith("/"): s = "https://stock.naver.com" + s
        if s in seen: continue
        seen.add(s)
        try:
            js = requests.get(s, headers=H, timeout=20).text
        except Exception:
            continue
        alljs.append(js); found |= set(PAT.findall(js))
print(f"\n=== all api paths ({len(found)})")
for p in sorted(found): print("  ", p)
print("\n=== contexts")
for kw in CTX:
    n = 0
    for js in alljs:
        for m in re.finditer(re.escape(kw), js):
            print(f"--- [{kw}] ...{js[max(0,m.start()-350):m.end()+350]}...")
            n += 1
            if n >= 4: break
        if n >= 4: break
