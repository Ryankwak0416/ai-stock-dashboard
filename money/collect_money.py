# -*- coding: utf-8 -*-
"""
수급흐름 대시보드 — 데이터 수집기 v2 (네이버 증권 기반)
GitHub Actions(해외 IP)에서 KRX가 차단되어 네이버 공개 데이터를 사용한다.
  1) 지수 일별 시세+거래대금  : finance.naver.com/sise/sise_index_day.naver   (이력 제공)
  2) 투자자별 일별 순매수     : finance.naver.com/sise/investorDealTrendDay.naver (이력 제공)
  3) 업종 목록/구성종목       : m.stock.naver.com/api/stocks/industry          (당일 스냅샷)
  4) 외국인 매매 상위         : finance.naver.com/sise/sise_deal_rank.naver    (당일)
업종 이력은 제공되지 않으므로 data.json 안의 sectorHist 에 매일 누적한다.
부분 실패해도 가능한 데이터만으로 JSON을 생성한다.
"""
import json, os, re, time, datetime, traceback
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

def get(url, retries=2):
    last = None
    for i in range(retries + 1):
        try:
            r = requests.get(url, headers=H, timeout=15)
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

def table_rows(html):
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = [re.sub(r"<[^>]+>", "", c).replace("&nbsp;", " ").strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
        cells = [c for c in cells if c != ""]
        if cells: rows.append(cells)
    return rows

def fetch_index_history(code, max_pages=12):
    out = {}
    for p in range(1, max_pages + 1):
        html = get(f"https://finance.naver.com/sise/sise_index_day.naver?code={code}&page={p}").text
        got = 0
        for r in table_rows(html):
            if len(r) >= 6 and re.match(r"\d{4}\.\d{2}\.\d{2}", r[0]):
                d = r[0].replace(".", "-")
                close, val = num(r[1]), num(r[5])
                if close and val is not None:
                    out[d] = (close, round(val / 1e6, 3)); got += 1
        if got == 0: break
    return out

def fetch_investor_history(sosok, bizdate, max_pages=8):
    out = {}
    for p in range(1, max_pages + 1):
        u = (f"https://finance.naver.com/sise/investorDealTrendDay.naver"
             f"?bizdate={bizdate}&sosok={sosok}&page={p}")
        html = get(u).text
        got = 0
        for r in table_rows(html):
            if len(r) >= 4 and re.match(r"\d{2}\.\d{2}\.\d{2}", r[0]):
                d = "20" + r[0].replace(".", "-")
                ind, frn, ins = num(r[1]), num(r[2]), num(r[3])
                if ind is not None:
                    out[d] = (ind, frn, ins); got += 1
        if got == 0: break
    return out

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

def fetch_foreign_rank():
    """외국인 순매수/순매도 상위. 본문+iframe 안의 테이블에서 '종목명/금액' 헤더를 찾아 파싱."""
    html = get("https://finance.naver.com/sise/sise_deal_rank.naver").text
    htmls = [html]
    for src in re.findall(r'<iframe[^>]*src=["\']([^"\']+)["\']', html)[:5]:
        if src.startswith("/"):
            src = "https://finance.naver.com" + src
        if "naver.com" not in src:
            continue
        try:
            htmls.append(get(src).text)
        except Exception as e:
            ERRORS.append(f"rank iframe: {e}")
    res, side_idx = [], 0
    all_tables = []
    for h in htmls:
        all_tables += re.findall(r"<table[^>]*>(.*?)</table>", h, re.S)
    for tb in all_tables:
        rows = []
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", tb, re.S):
            cells = [re.sub(r"<[^>]+>", "", c).replace("&nbsp;", " ").strip()
                     for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
            rows.append(cells)
        hdr = next((r for r in rows if any("종목명" in c for c in r)), None)
        if not hdr: continue
        name_i = next(i for i, c in enumerate(hdr) if "종목명" in c)
        amt_i = next((i for i, c in enumerate(hdr) if "금액" in c), None)
        side = "buy" if side_idx == 0 else "sell"
        side_idx += 1
        for r in rows:
            if r == hdr or len(r) <= max(name_i, amt_i or 0): continue
            nm = r[name_i]
            if not nm or re.match(r"^[\d,.\-+%\s]*$", nm): continue
            amt = num(r[amt_i]) if amt_i is not None else None
            res.append({"name": nm, "amt": amt, "side": side})
        if side_idx >= 2: break
    seen, dedup = set(), []
    for r in res:
        k = (r["name"], r["side"])
        if k not in seen:
            seen.add(k); dedup.append(r)
    return dedup[:40]

def main():
    out = {"updated": NOW.strftime("%Y-%m-%d %H:%M KST"), "errors": ERRORS, "version": 2}

    try:
        kospi = fetch_index_history("KOSPI")
    except Exception as e:
        traceback.print_exc(); raise SystemExit(f"KOSPI 지수 수집 실패: {e}")
    try:
        kosdaq = fetch_index_history("KOSDAQ")
    except Exception as e:
        ERRORS.append(f"KOSDAQ index: {e}"); kosdaq = {}

    dates = sorted(kospi.keys())[-DAYS:]
    out["dates"] = dates
    def series(src, i):
        return [src.get(d, (None, None))[i] if src.get(d) else None for d in dates]
    out["market"] = {
        "kospi": {"close": series(kospi, 0), "value": series(kospi, 1)},
        "kosdaq": {"close": series(kosdaq, 0), "value": series(kosdaq, 1)},
    }
    log(f"지수 {len(dates)}일 (마지막 {dates[-1]})")

    biz = dates[-1].replace("-", "")
    inv_out = {}
    for key, sosok in [("kospi", "01"), ("kosdaq", "02")]:
        try:
            h = fetch_investor_history(sosok, biz)
            inv_out[key] = {
                "individual": [h.get(d, (None,) * 3)[0] for d in dates],
                "foreign":    [h.get(d, (None,) * 3)[1] for d in dates],
                "institution":[h.get(d, (None,) * 3)[2] for d in dates],
            }
            log(f"투자자 {key}: {sum(1 for d in dates if d in h)}일")
        except Exception as e:
            ERRORS.append(f"investor {key}: {e}")
    out["investor"] = inv_out

    prev_hist = {}
    try:
        if os.path.exists(OUT):
            with open(OUT, encoding="utf-8") as f:
                prev_hist = json.load(f).get("sectorHist", {}) or {}
    except Exception as e:
        ERRORS.append(f"prev hist: {e}")

    snap, code2sec = {}, {}
    try:
        groups = fetch_industries()
        log(f"업종 {len(groups)}개")
        for g in groups:
            try:
                ss = fetch_industry_stocks(g["no"])
            except Exception as e:
                ERRORS.append(f"industry {g.get('name')}: {e}"); continue
            tot = ksp = kdq = 0.0
            for s in ss:
                v = num(s.get("accumulatedTradingValue")) or 0.0
                tot += v
                if str(s.get("sosok")) == "0": ksp += v
                else: kdq += v
                code2sec[s.get("itemCode")] = g["name"]
                code2sec[s.get("stockName")] = g["name"]
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
