# 진단용 6차 — 지수 일별시세·투자자 일자 조회 (수정 후 삭제)
import re, requests
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
     "Accept": "application/json, */*", "Referer": "https://stock.naver.com/"}
def show(u, n=1200):
    try:
        r = requests.get(u, headers=H, timeout=20)
        print(f"=== {u}\nstatus={r.status_code} len={len(r.content)}\n{re.sub(chr(10)+'|  +', ' ', r.text[:n])}\n")
    except Exception as e:
        print(f"=== {u} ERROR {e!r}\n")
B = "https://stock.naver.com"
for u in [
 B + "/api/domestic/indexSise/time?koreaIndexType=KOSPI&thistime=20261016&startIdx=0&pageSize=3",
 B + "/api/domestic/indexSise/time?koreaIndexType=KOSPI&thistime=20261016153000&startIdx=0&pageSize=3",
 B + "/api/domestic/indexSise/time?koreaIndexType=KOSPI&thistime=202610161530&startIdx=0&pageSize=3",
 B + "/api/domestic/indexSise/time?koreaIndexType=KOSPI&thistime=2026-10-16&startIdx=0&pageSize=3",
 B + "/api/domestic/indexSise/time?koreaIndexType=KOSPI&thistime=20261017235959&startIdx=0&pageSize=3",
 "https://m.stock.naver.com/api/index/KOSPI/trend?bizdate=20261016",
 "https://m.stock.naver.com/api/index/KOSPI/trend?bizdate=20261015",
 "https://m.stock.naver.com/api/index/KOSPI/trend?bizdate=20260917",
 "https://m.stock.naver.com/api/index/KOSDAQ/trend?bizdate=20260917",
 "https://m.stock.naver.com/api/index/KOSPI/basic",
 B + "/api/domestic/market/stock/default?tradeType=KRX&marketType=ALL&orderType=marketSum&startIdx=0&pageSize=100",
 B + "/api/domestic/market/stock/default?tradeType=KRX&marketType=ALL&orderType=foreignPureBuy&startIdx=0&pageSize=40",
]: show(u, 900)
