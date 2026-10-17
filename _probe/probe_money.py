# 진단용 2차 — 대체 원천 탐색 (수정 후 삭제)
import re, json, datetime, requests
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
     "Accept": "*/*", "Referer": "https://m.stock.naver.com/"}
today = datetime.date.today().strftime("%Y%m%d")
start = (datetime.date.today() - datetime.timedelta(days=120)).strftime("%Y%m%d")
def show(name, u, n=700):
    print(f"=== {name}  {u}")
    try:
        r = requests.get(u, headers=H, timeout=20, allow_redirects=False)
        t = re.sub(r"\s+", " ", r.text)
        print(f"status={r.status_code} len={len(r.content)} loc={r.headers.get('location')}")
        print("head:", t[:n])
        return r
    except Exception as e:
        print("ERROR", repr(e))
    print()
# 1) 지수 레코드 전체 키
for name, u in [("m_idx_price", "https://m.stock.naver.com/api/index/KOSPI/price?pageSize=60&page=1"),
                ("api_idx_chart", f"https://api.stock.naver.com/chart/domestic/index/KOSPI/day?startDateTime={start}0000&endDateTime={today}2359")]:
    try:
        j = requests.get(u, headers=H, timeout=20).json()
        print(f"=== {name} n={len(j)} keys={list(j[0].keys())}\n first={j[0]}\n last={j[-1]}\n")
    except Exception as e:
        print(name, "ERROR", repr(e))
# 2) 투자자 이력 후보
for name, u in [
 ("trend_bizdate", "https://m.stock.naver.com/api/index/KOSPI/trend?bizdate=20261010"),
 ("trend_page", "https://m.stock.naver.com/api/index/KOSPI/trend?pageSize=10&page=1"),
 ("trend_day", "https://m.stock.naver.com/api/index/KOSPI/trend/day?pageSize=10&page=1"),
 ("trend_list", "https://m.stock.naver.com/api/index/KOSPI/trendList?pageSize=10&page=1"),
 ("investorTrend", "https://m.stock.naver.com/api/index/KOSPI/investorTrend?pageSize=10&page=1"),
 ("api_trend", "https://api.stock.naver.com/index/KOSPI/trend?pageSize=10"),
 ("kosdaq_trend", "https://m.stock.naver.com/api/index/KOSDAQ/trend"),
]: show(name, u, 500); print()
# 3) 환율 이력
for name, u in [
 ("m_fx60", "https://m.stock.naver.com/front-api/marketIndex/prices?category=exchange&reutersCode=FX_USDKRW&page=1&pageSize=60"),
 ("api_fx", "https://api.stock.naver.com/marketindex/exchange/FX_USDKRW/prices?page=1&pageSize=60"),
]: show(name, u, 600); print()
# 4) 새 사이트·모바일 JS 에서 API 경로 수집
KW = re.compile(r"invest|foreign|trend|deal|rank|exchange|marketIndex|frgn|buy", re.I)
for base in ["https://stock.naver.com/market/stock/kr", "https://m.stock.naver.com/domestic/index/KOSPI/total", "https://m.stock.naver.com/"]:
    print(f"=== discover {base}")
    try:
        html = requests.get(base, headers=H, timeout=20).text
        srcs = re.findall(r'<script[^>]+src="([^"]+)"', html)
        found = set(re.findall(r'["\'`]((?:https://[a-z.]*naver\.com)?/(?:front-)?api/[^"\'`\s<>]{3,140})', html))
        for s in srcs[:60]:
            if s.startswith("//"): s = "https:" + s
            elif s.startswith("/"): s = base.split("/", 3)[0] + "//" + base.split("/")[2] + s
            try:
                js = requests.get(s, headers=H, timeout=20).text
            except Exception:
                continue
            found |= set(re.findall(r'["\'`]((?:https://[a-z.]*naver\.com)?/(?:front-)?api/[^"\'`\s<>]{3,140})', js))
        print(f"scripts={len(srcs)} api_paths={len(found)}")
        for p in sorted(found):
            if KW.search(p): print("  ", p)
    except Exception as e:
        print("ERROR", repr(e))
    print()
