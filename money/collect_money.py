# -*- coding: utf-8 -*-
"""
수급흐름 대시보드 — 데이터 수집기 v3 (네이버 증권 새 API)
GitHub Actions(해외 IP)에서 KRX가 차단되어 네이버 공개 데이터를 사용한다.
2026-10-17: 네이버가 finance.naver.com 옛 시세 페이지(지수·투자자·환율 일별)를 폐지(HTTP 410)해
            9/17 이후 수집이 멈춰 있던 것을 아래 새 주소로 옮김.
  1) 지수 일별 종가           : m.stock.naver.com/api/index/{KOSPI|KOSDAQ}/price             (이력 제공)
  2) 지수 일별 거래대금       : finance.daum.net/api/market_index/days                      (이력 제공 — 네이버엔 없음)
                                + stock.naver.com/api/domestic/indexSise/time?thistime=날짜   (최근 약 7거래일만 — 보조)
  3) 투자자별 일별 순매수     : m.stock.naver.com/api/index/{KOSPI|KOSDAQ}/trend?bizdate=날짜 (날짜별)
  4) 업종 목록/구성종목       : m.stock.naver.com/api/stocks/industry                       (당일 스냅샷)
  5) 원/달러 환율             : api.stock.naver.com/marketindex/exchange/FX_USDKRW/prices   (이력 제공)
  6) 외국인 매매 상위         : stock.naver.com/api/domestic/market/stock/default 순위 목록
                                + stock.naver.com/api/stockSecurity/investor-trend 종목별 외국인 순매매 수량
2)의 보조 원천과 3)은 날짜마다 따로 불러야 하므로 data.json 에 이미 있는 날짜는 그 값을 다시 쓰고,
없는 날짜와 최근 2일(장중 값 갱신)만 새로 받는다.
업종 이력은 제공되지 않으므로 data.json 안의 sectorHist 에 매일 누적한다.
부분 실패해도 가능한 데이터만으로 JSON을 생성한다.
"""
import json, os, time, datetime, traceback
import requests

KST = datetime.timezone(datetime.timedelta(hours=9))
NOW = datetime.datetime.now(KST)
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data.json")
DAYS = 60
SLEEP = 0.25
ERRORS = []
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
     "Accept": "*/*", "Referer": "https://finance.naver.com/"}

def log(m): print(f"[collect] {m}", flush=True)

def get(url, retries=2, headers=None):
    last = None
    for i in range(retries + 1):
        try:
            r = requests.get(url, headers=headers or H, timeout=15)
            if r.status_code == 200:
                time.sleep(SLEEP)
                return r
            last = f"HTTP {r.status_code}"
        except Exception as e:
            last = repr(e)
        time.sleep(1.0)
    raise RuntimeError(f"{last} {url}")

def num(s):
    s = str(s).replace(",", "").replace("+", "").replace("%", "").strip()
    try: return float(s)
    except: return None

def by_date(dates, arr):
    """날짜 순서 배열 → {날짜: 값} (값이 None 인 날은 뺀다)."""
    return {d: v for d, v in zip(dates or [], arr or []) if v is not None}

def per_day(dates, cache, fetch, label, refresh=()):
    """날짜마다 부르는 원천 — 캐시에 없는 날짜, 최근 2일, refresh(직전 실행의 최근 2일 — 장중 값이었을 수 있음)만
    새로 받는다. {날짜: 값}."""
    recent = set(dates[-2:]) | set(refresh)
    out, fresh, fail = {}, 0, 0
    for d in dates:
        if d in cache and d not in recent:
            out[d] = cache[d]; continue
        try:
            v = fetch(d)
        except Exception as e:
            v = None; fail += 1
            if fail <= 3: ERRORS.append(f"{label} {d}: {e}")
        fresh += 1
        if v is None: v = cache.get(d)
        if v is not None: out[d] = v
    log(f"{label}: {len(out)}/{len(dates)}일 (새로 받은 날 {fresh}, 실패 {fail})")
    return out

def fetch_index_closes(code):
    """지수 일별 종가 {날짜: 종가} — 최근 DAYS 거래일."""
    rows = get(f"https://m.stock.naver.com/api/index/{code}/price?pageSize={DAYS}&page=1").json()
    return {r["localTradedAt"]: num(r.get("closePrice")) for r in rows if num(r.get("closePrice"))}

def fetch_index_values_daum(code, need=DAYS):
    """지수 일별 거래대금 이력 {날짜: 조원} — 다음 금융 (accTradePrice 단위 백만원)."""
    hd = dict(H, Referer=f"https://finance.daum.net/domestic/{code.lower()}")
    out = {}
    for p in range(1, 6):
        rows = get(f"https://finance.daum.net/api/market_index/days?page={p}&perPage=20&market={code}&pagination=true",
                   headers=hd).json().get("data") or []
        for r in rows:
            v = num(r.get("accTradePrice"))
            if v: out[r["date"][:10]] = round(v / 1e6, 3)
        if len(rows) < 20 or len(out) >= need: break
    return out

def fetch_index_value(code, d):
    """그날 지수 거래대금(조원) — 분 시세 목록에서 가장 늦은 시각의 누적 거래대금."""
    rows = get(f"https://stock.naver.com/api/domestic/indexSise/time"
               f"?koreaIndexType={code}&thistime={d.replace('-', '')}&startIdx=0&pageSize=3").json()
    if not rows: return None
    v = num(max(rows, key=lambda r: r.get("thistime", "")).get("amount"))
    return round(v / 1e12, 3) if v else None

def fetch_investor_day(code, d):
    """그날 개인·외국인·기관 순매수(억원)."""
    j = get(f"https://m.stock.naver.com/api/index/{code}/trend?bizdate={d.replace('-', '')}").json()
    if j.get("bizdate") != d.replace("-", ""): return None
    v = (num(j.get("personalValue")), num(j.get("foreignValue")), num(j.get("institutionalValue")))
    return None if v[0] is None else v

def fetch_industries():
    groups, seen = [], set()
    for p in range(1, 12):
        try:
            j = get(f"https://m.stock.naver.com/api/stocks/industry?page={p}&pageSize=20").json()
        except Exception as e:
            ERRORS.append(f"industry list p{p}: {e}"); break
        gs = j.get("groups", [])
        new = [g for g in gs if g.get("no") not in seen]
        for g in new: seen.add(g["no"])
        groups += new
        if len(gs) < 20: break
    return groups

def fetch_industry_stocks(no):
    stocks = []
    for p in range(1, 4):
        j = get(f"https://m.stock.naver.com/api/stocks/industry/{no}?page={p}&pageSize=60").json()
        ss = j.get("stocks", [])
        stocks += ss
        if len(ss) < 60: break
    return stocks

def fetch_fx(pages=2):
    """원/달러 매매기준율 일별 이력 {날짜: 환율}."""
    out = {}
    for p in range(1, pages + 1):
        try:
            rows = get(f"https://api.stock.naver.com/marketindex/exchange/FX_USDKRW/prices?page={p}&pageSize=60").json()
        except Exception as e:
            ERRORS.append(f"fx p{p}: {e}"); break
        for r in rows:
            rate = num(r.get("closePrice"))
            if rate: out[r["localTradedAt"]] = rate
        if len(rows) < 60: break
    return out

def fetch_foreign_rank(n_buy=30, n_cap=100):
    """외국인 순매수/순매도 상위 (금액 = 외국인 순매매 수량 × 종가, 백만원).
    순매수 순위는 foreignPureBuy 목록에서, 순매도 순위 목록은 따로 없어 시가총액 상위 종목 중에서 고른다.
    종목별 투자자 동향의 가장 최근 날짜(KRX)만 쓰고, 날짜가 다른 종목은 뺀다."""
    base = "https://stock.naver.com/api/domestic/market/stock/default?tradeType=KRX&marketType=ALL"
    cand = {}
    for order, n in [("foreignPureBuy", n_buy), ("marketSum", n_cap)]:
        try:
            for s in get(f"{base}&orderType={order}&startIdx=0&pageSize={n}").json():
                cand.setdefault(s["itemcode"], s["itemname"])
        except Exception as e:
            ERRORS.append(f"rank list {order}: {e}")
    res, fail = [], 0
    for code, name in cand.items():
        try:
            j = get(f"https://stock.naver.com/api/stockSecurity/investor-trend/v2/domestic/{code}/paged"
                    f"?exchangeType=krx&size=1").json()
            it = (j.get("items") or [{}])[0]
            k = it.get("krx") or {}
            vol, px = num(k.get("foreignNetVolume")), num(k.get("closingPrice"))
        except Exception as e:
            fail += 1
            if fail <= 3: ERRORS.append(f"rank {name}: {e}")
            continue
        if vol is not None and px:
            res.append({"name": name, "amt": round(vol * px / 1e6), "date": it.get("localTradedAt")})
    if not res:
        ERRORS.append("foreign rank: 종목별 외국인 순매매를 받지 못함")
        return []
    last = max(r["date"] or "" for r in res)
    res = [r for r in res if r["date"] == last]
    buys = sorted((r for r in res if r["amt"] > 0), key=lambda r: -r["amt"])[:20]
    sells = sorted((r for r in res if r["amt"] < 0), key=lambda r: r["amt"])[:20]
    for r in buys: r["side"] = "buy"
    for r in sells: r["side"] = "sell"
    log(f"외국인 순매매 {len(res)}종목 ({last})")
    return buys + sells

def main():
    out = {"updated": NOW.strftime("%Y-%m-%d %H:%M KST"), "errors": ERRORS, "version": 3}

    prev = {}
    try:
        if os.path.exists(OUT):
            with open(OUT, encoding="utf-8") as f:
                prev = json.load(f) or {}
    except Exception as e:
        ERRORS.append(f"prev data: {e}")
    pdates = prev.get("dates") or []

    try:
        kospi = fetch_index_closes("KOSPI")
    except Exception as e:
        traceback.print_exc(); raise SystemExit(f"KOSPI 지수 수집 실패: {e}")
    if not kospi:
        raise SystemExit("KOSPI 지수 수집 실패: 빈 응답")
    try:
        kosdaq = fetch_index_closes("KOSDAQ")
    except Exception as e:
        ERRORS.append(f"KOSDAQ index: {e}"); kosdaq = {}

    dates = sorted(kospi.keys())[-DAYS:]
    out["dates"] = dates
    out["market"] = {}
    for key, code, closes in [("kospi", "KOSPI", kospi), ("kosdaq", "KOSDAQ", kosdaq)]:
        pm = (prev.get("market") or {}).get(key) or {}
        cache = by_date(pdates, pm.get("value"))
        try:
            daum = fetch_index_values_daum(code)
        except Exception as e:
            ERRORS.append(f"거래대금 {key} (다음): {e}"); daum = {}
        cache.update(daum)
        val = per_day(dates, cache, lambda d, c=code: fetch_index_value(c, d), f"거래대금 {key}",
                      [d for d in pdates[-2:] if d not in daum])
        out["market"][key] = {"close": [closes.get(d) for d in dates], "value": [val.get(d) for d in dates]}
    log(f"지수 {len(dates)}일 (마지막 {dates[-1]})")

    inv_out = {}
    for key, code in [("kospi", "KOSPI"), ("kosdaq", "KOSDAQ")]:
        pi = (prev.get("investor") or {}).get(key) or {}
        rows = list(zip(pi.get("individual") or [], pi.get("foreign") or [], pi.get("institution") or []))
        cache = {d: r for d, r in by_date(pdates, rows).items() if r[0] is not None}
        h = per_day(dates, cache, lambda d, c=code: fetch_investor_day(c, d), f"투자자 {key}", pdates[-2:])
        if not h:
            ERRORS.append(f"investor {key}: 받은 날 없음"); continue
        inv_out[key] = {
            "individual": [h.get(d, (None,) * 3)[0] for d in dates],
            "foreign":    [h.get(d, (None,) * 3)[1] for d in dates],
            "institution":[h.get(d, (None,) * 3)[2] for d in dates],
        }
    out["investor"] = inv_out

    prev_hist = prev.get("sectorHist") or {}

    snap, code2sec, sec_stocks = {}, {}, {}
    try:
        groups = fetch_industries()
        log(f"업종 {len(groups)}개")
        for g in groups:
            try:
                ss = fetch_industry_stocks(g["no"])
            except Exception as e:
                ERRORS.append(f"industry {g.get('name')}: {e}"); continue
            tot = ksp = kdq = 0.0
            stk = []
            for s in ss:
                v = num(s.get("accumulatedTradingValue")) or 0.0
                tot += v
                if str(s.get("sosok")) == "0": ksp += v
                else: kdq += v
                code2sec[s.get("itemCode")] = g["name"]
                code2sec[s.get("stockName")] = g["name"]
                cap = num(s.get("marketValue"))
                chg = num(s.get("fluctuationsRatio"))
                if chg is None: chg = num(s.get("changeRate"))
                stk.append([s.get("stockName"),
                            round(cap / 1e4, 3) if cap else None,
                            chg, round(v / 1e6, 4)])
            stk = [x for x in stk if x[1]]
            stk.sort(key=lambda x: x[1], reverse=True)
            sec_stocks[g["name"]] = stk[:20]
            snap[g["name"]] = {"chg": num(g.get("changeRate")), "val": round(tot / 1e6, 4),
                               "ksp": round(ksp / 1e6, 4), "kdq": round(kdq / 1e6, 4),
                               "rise": g.get("riseCount"), "fall": g.get("fallCount")}
    except Exception as e:
        ERRORS.append(f"industries: {e}"); traceback.print_exc()

    today = dates[-1]
    if snap:
        prev_hist[today] = {k: [v["chg"], v["val"]] for k, v in snap.items()}
    hist_dates = sorted(prev_hist.keys())[-DAYS:]
    prev_hist = {d: prev_hist[d] for d in hist_dates}
    out["sectorHist"] = prev_hist
    nh = len(hist_dates)
    out["histDays"] = nh
    log(f"업종 이력 {nh}일 누적")

    tot_by_day = {d: sum((x[1] or 0) for x in prev_hist[d].values()) for d in hist_dates}
    kmap = dict(zip(dates, out["market"]["kospi"]["close"]))
    sectors = []
    for name, v in snap.items():
        mkt = "KOSPI" if v["ksp"] >= v["kdq"] else "KOSDAQ"
        s = {"name": name, "market": mkt, "chg1": v["chg"], "val5d": v["val"],
             "rise": v["rise"], "fall": v["fall"]}
        my = [(d, prev_hist[d].get(name)) for d in hist_dates if prev_hist[d].get(name)]
        if my:
            def share(days):
                vals = [(x[1] or 0) / tot_by_day[d] * 100 for d, x in days if tot_by_day[d] > 0]
                return round(sum(vals) / len(vals), 2) if vals else None
            s["valShare"] = share(my[-5:])
            if len(my) >= 10:
                s["valSharePrev"] = share(my[-10:-5])
            idx, idxs = 100.0, []
            for d, x in my:
                idx *= (1 + (x[0] or 0) / 100); idxs.append((d, idx))
            if len(idxs) >= 6:
                s["chg5"] = round(100 * (idxs[-1][1] / idxs[-6][1] - 1), 2)
            if len(idxs) >= 25:
                ratio = [i / kmap[d] for d, i in idxs if kmap.get(d)]
                if len(ratio) >= 25:
                    trail = []
                    for k in range(5, -1, -1):
                        i = len(ratio) - 1 - k
                        if i >= 20:
                            base = sum(ratio[i - 19:i + 1]) / 20
                            x = round(100 * (ratio[i] / base - 1), 2)
                            y = round(100 * (ratio[i] / ratio[i - 5] - 1), 2) if i >= 5 else 0
                            trail.append([x, y])
                    if trail: s["rrg"] = trail
        sectors.append(s)
    out["sectors"] = sectors
    out["sectorStocks"] = sec_stocks

    try:
        fxh = fetch_fx()
        out["fx"] = [fxh.get(d) for d in dates]
        log(f"환율 {sum(1 for d in dates if fxh.get(d))}일")
    except Exception as e:
        ERRORS.append(f"fx: {e}")

    try:
        rank = fetch_foreign_rank()
        for r in rank: r["sector"] = code2sec.get(r["name"], "")
        out["foreignRank"] = rank
        log(f"외국인 매매상위 {len(rank)}종목")
    except Exception as e:
        ERRORS.append(f"foreign rank: {e}")

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    log(f"저장 완료 (업종 {len(sectors)}, 이력 {nh}일, 오류 {len(ERRORS)})")
    for e in ERRORS: log("ERR " + str(e))

if __name__ == "__main__":
    main()
