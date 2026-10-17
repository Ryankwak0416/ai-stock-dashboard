# 진단용 — money-flow 수집 원천이 GitHub 러너에서 어떻게 응답하는지 기록 (수정 후 삭제)
import re, json, datetime, requests
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
     "Accept": "*/*", "Referer": "https://finance.naver.com/"}
today = datetime.date.today().strftime("%Y%m%d")
start = (datetime.date.today() - datetime.timedelta(days=120)).strftime("%Y%m%d")
U = [
 ("index_day", "https://finance.naver.com/sise/sise_index_day.naver?code=KOSPI&page=1"),
 ("investor_day", f"https://finance.naver.com/sise/investorDealTrendDay.naver?bizdate={today}&sosok=01&page=1"),
 ("industry_api", "https://m.stock.naver.com/api/stocks/industry?page=1&pageSize=20"),
 ("fx", "https://finance.naver.com/marketindex/exchangeDailyQuote.naver?marketindexCd=FX_USDKRW&page=1"),
 ("deal_rank", "https://finance.naver.com/sise/sise_deal_rank.naver"),
 ("api_idx_chart", f"https://api.stock.naver.com/chart/domestic/index/KOSPI/day?startDateTime={start}0000&endDateTime={today}2359"),
 ("m_idx_price", "https://m.stock.naver.com/api/index/KOSPI/price?pageSize=5&page=1"),
 ("m_idx_basic", "https://m.stock.naver.com/api/index/KOSPI/basic"),
 ("m_idx_trend", "https://m.stock.naver.com/api/index/KOSPI/trend"),
 ("m_idx_investor", "https://m.stock.naver.com/api/index/KOSPI/investor?pageSize=5&page=1"),
 ("m_fx", "https://m.stock.naver.com/front-api/marketIndex/prices?category=exchange&reutersCode=FX_USDKRW&page=1&pageSize=5"),
 ("m_deal_rank", "https://m.stock.naver.com/api/stocks/foreignBuy/KOSPI?page=1&pageSize=5"),
]
for name, u in U:
    print(f"=== {name}  {u}")
    try:
        r = requests.get(u, headers=H, timeout=20, allow_redirects=False)
        print(f"status={r.status_code} len={len(r.content)} ctype={r.headers.get('content-type')} enc={r.encoding} loc={r.headers.get('location')}")
        t = r.text
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", t, re.S)
        dates = re.findall(r"\d{2,4}\.\d{2}\.\d{2}", t)
        print(f"tr={len(rows)} date_like={len(dates)} first_dates={dates[:4]}")
        body = re.sub(r"\s+", " ", t)
        print("head:", body[:900])
    except Exception as e:
        print("ERROR", repr(e))
    print()
