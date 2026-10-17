# 진단용 4차 — stock.naver.com 후보 호출 시험 (수정 후 삭제)
import re, requests
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
     "Accept": "application/json, */*", "Referer": "https://stock.naver.com/"}
B = "https://stock.naver.com"
def show(u, n=600):
    try:
        r = requests.get(u, headers=H, timeout=20, allow_redirects=False)
        print(f"=== {u}\nstatus={r.status_code} len={len(r.content)} ct={r.headers.get('content-type')}\n{re.sub(chr(10)+'|  +', ' ', r.text[:n])}\n")
    except Exception as e:
        print(f"=== {u} ERROR {e!r}\n")
for u in [
 "/api/domestic/indexSise/day?koreaIndexType=KOSPI",
 "/api/domestic/indexSise/day?koreaIndexType=KOSPI&page=1&pageSize=10",
 "/api/domestic/indexSise/time?koreaIndexType=KOSPI",
 "/api/securityService/chart/domestic/index/KOSPI?periodType=day",
 "/api/securityService/index/KOSPI",
 "/api/securityService/index/KOSPI/price?page=1&pageSize=5",
 "/api/stockSecurity/investor-trend/v2/domestic/KOSPI?exchangeType=KRX&size=5",
 "/api/stockSecurity/investor-trend/v2/domestic/KOSPI/paged?exchangeType=KRX&size=5",
 "/api/stockSecurity/investor-trend/v2/domestic/005930?exchangeType=KRX&size=3",
 "/api/domestic/market/stock/default?tradeType=KRX&marketType=ALL&orderType=tradingValueDesc&page=1&pageSize=3",
]: show(B + u)
PAT = re.compile(r'["\'`]((?:https://[a-z.]*naver\.com)?/(?:front-)?api/[^"\'`\s<>]{3,140})')
alljs, seen = [], set()
for base in ["https://stock.naver.com/market/stock/kr", "https://stock.naver.com/domestic/index/KOSPI"]:
    html = requests.get(base, headers=H, timeout=20).text
    alljs.append(html)
    for s in re.findall(r'<script[^>]+src="([^"]+)"', html):
        if s.startswith("/"): s = B + s
        if s in seen: continue
        seen.add(s)
        try: alljs.append(requests.get(s, headers=H, timeout=20).text)
        except Exception: pass
print("=== contexts")
for kw in ["indexSise", "/api/domestic/market/", "investor-trend/v2/domestic", "securityService/index/", "listingType:\"", "netBuy", "NetBuy", "foreignBuy", "frgn", "investorType", "personalValue"]:
    n = 0
    for js in alljs:
        for m in re.finditer(re.escape(kw), js):
            print(f"--- [{kw}] ...{js[max(0,m.start()-300):m.end()+300]}...")
            n += 1
            if n >= 3: break
        if n >= 3: break
