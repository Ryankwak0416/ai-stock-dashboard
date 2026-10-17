# 진단용 8차 — 지난 날짜 지수 거래대금 원천 (수정 후 삭제)
import re, requests
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"
def show(u, ref, n=900):
    try:
        r = requests.get(u, headers={"User-Agent": UA, "Accept": "application/json, */*", "Referer": ref}, timeout=25)
        print(f"=== {u}\nstatus={r.status_code} len={len(r.content)}\n{re.sub(chr(10)+'|  +', ' ', r.text[:n])}\n")
    except Exception as e:
        print(f"=== {u} ERROR {e!r}\n")
N = "https://stock.naver.com/"
for u in ["https://stock.naver.com/api/stockSecurity/items/v2/domestic/KOSPI/daily-prices/paged?size=3&index=0",
          "https://stock.naver.com/api/stockSecurity/items/v2/domestic/KOSPI/daily-prices/paged?exchangeType=krx&size=3&index=0",
          "https://stock.naver.com/api/stockSecurity/items/v2/domestic/005930/daily-prices/paged?size=2&index=0",
          "https://stock.naver.com/api/stockSecurity/items/v2/domestic/005930/daily-prices/paged?exchangeType=krx&size=2&index=0"]:
    show(u, N)
D = "https://finance.daum.net/domestic/kospi"
for u in ["https://finance.daum.net/api/market_index/days?page=1&perPage=5&market=KOSPI&pagination=true",
          "https://finance.daum.net/api/market_index/days?page=3&perPage=10&market=KOSDAQ&pagination=true"]:
    show(u, D, 1500)
