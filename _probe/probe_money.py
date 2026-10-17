# 진단용 7차 — 지난 날짜 지수 거래대금 원천 (수정 후 삭제)
import re, requests, json
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
     "Accept": "application/json, */*", "Referer": "https://stock.naver.com/"}
B = "https://stock.naver.com"
def show(u, n=700):
    try:
        r = requests.get(u, headers=H, timeout=25)
        t = r.text
        extra = ""
        try:
            j = r.json()
            if isinstance(j, dict) and isinstance(j.get("priceInfos"), list):
                pi = j["priceInfos"]
                extra = f" priceInfos={len(pi)} keys={list(pi[0].keys()) if pi else None}\n first={pi[0] if pi else None}\n last={pi[-1] if pi else None}"
        except Exception:
            pass
        print(f"=== {u}\nstatus={r.status_code} len={len(r.content)}{extra}\n{re.sub(chr(10)+'|  +', ' ', t[:n])}\n")
    except Exception as e:
        print(f"=== {u} ERROR {e!r}\n")
for d in ["20260918", "20260925", "20261001", "20261008", "20261013"]:
    show(B + f"/api/domestic/indexSise/time?koreaIndexType=KOSPI&thistime={d}&startIdx=0&pageSize=1", 300)
show(B + "/api/domestic/indexSise/time?koreaIndexType=KOSPI&thistime=20260918153000&startIdx=0&pageSize=1", 300)
for pt in ["week", "month", "year", "threeMonth", "dayCandle", "candle"]:
    show(B + f"/api/securityService/chart/domestic/index/KOSPI?periodType={pt}", 300)
for rg in ["3M", "month3", "threeMonths", "1Y"]:
    show(B + f"/api/securityService/chart/domestic/index/KOSPI?periodType=day&range={rg}", 300)
show(B + "/api/securityService/chart/domestic/index/KOSPI/candle?periodType=day", 300)
# JS 에서 periodType·range 값 찾기
seen, js_all = set(), []
for base in ["https://stock.naver.com/domestic/index/KOSPI", "https://stock.naver.com/domestic/index/KOSPI/price"]:
    try:
        html = requests.get(base, headers=H, timeout=20).text
    except Exception:
        continue
    js_all.append(html)
    for s in re.findall(r'<script[^>]+src="([^"]+)"', html):
        if s.startswith("/"): s = B + s
        if s in seen: continue
        seen.add(s)
        try: js_all.append(requests.get(s, headers=H, timeout=20).text)
        except Exception: pass
print("=== contexts")
for kw in ["periodType", "range:", "indexSise", "accumulatedTradingValue", "dailyPrice", "day-prices", "/prices"]:
    n = 0
    for js in js_all:
        for m in re.finditer(re.escape(kw), js):
            print(f"--- [{kw}] ...{js[max(0,m.start()-250):m.end()+250]}...")
            n += 1
            if n >= 4: break
        if n >= 4: break
