# 진단용 5차 — 새 API 형식 맞추기 (수정 후 삭제)
import re, requests, json
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
     "Accept": "application/json, */*", "Referer": "https://stock.naver.com/"}
B = "https://stock.naver.com"
def show(u, n=1500):
    try:
        r = requests.get(B + u, headers=H, timeout=20)
        t = r.text
        try:
            j = r.json()
            items = j if isinstance(j, list) else next((v for v in (j.values() if isinstance(j, dict) else []) if isinstance(v, list)), None)
            extra = f" listlen={len(items)} keys0={list(items[0].keys()) if items and isinstance(items[0], dict) else None}" if items is not None else f" topkeys={list(j.keys()) if isinstance(j, dict) else type(j)}"
        except Exception:
            extra = ""
        print(f"=== {u}\nstatus={r.status_code} len={len(r.content)}{extra}\n{re.sub(chr(10)+'|  +', ' ', t[:n])}\n")
    except Exception as e:
        print(f"=== {u} ERROR {e!r}\n")
for u in [
 "/api/domestic/indexSise/time?koreaIndexType=KOSPI&thistime=20261017&startIdx=0&pageSize=3",
 "/api/domestic/indexSise/time?koreaIndexType=KOSPI&thistime=202610171600&startIdx=0&pageSize=3",
 "/api/domestic/indexSise/time?koreaIndexType=KOSPI&thistime=20261017160000&startIdx=0&pageSize=3",
 "/api/domestic/indexSise/time?koreaIndexType=KOSDAQ&thistime=20261017&startIdx=0&pageSize=80",
 "/api/stockSecurity/investor-trend/v2/domestic/KOSPI?exchangeType=krx&size=3",
 "/api/stockSecurity/investor-trend/v2/domestic/KOSPI/paged?exchangeType=krx&size=3",
 "/api/stockSecurity/investor-trend/v2/domestic/KOSDAQ/paged?exchangeType=krx&size=3",
 "/api/stockSecurity/investor-trend/v2/domestic/005930/paged?exchangeType=krx&size=2",
 "/api/domestic/market/stock/default?tradeType=KRX&marketType=ALL&orderType=foreignPureBuy&startIdx=0&pageSize=3",
 "/api/domestic/market/stock/default?tradeType=KRX&marketType=KOSPI&orderType=foreignPureBuy&startIdx=0&pageSize=3",
]: show(u)
