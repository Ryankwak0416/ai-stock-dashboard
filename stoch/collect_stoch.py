# -*- coding: utf-8 -*-
"""
멀티 타임프레임 스토캐스틱(슬로) 수집기
- 일봉 OHLC를 실제 주봉/월봉으로 리샘플한 뒤, 각 시간축에서 3형제(5·3 / 10·6 / 20·12) %K를 계산
- 종목별 JSON을 data/<code>.json 으로 저장

시간축별 파라미터 (각 축의 봉 기준)
  일봉  막내 5,3  둘째 10,6  큰형 20,12
  주봉  막내 5,3  둘째 10,6  큰형 20,12
  월봉  막내 5,3  둘째 10,6  큰형 20,12
  ※ %K만 사용(%D 미표시)이므로 (기간, 슬로잉)만 필요

출력 구조
  dates/close/stoch : 일봉축 (기존 페이지 호환).
                      stoch.W*/M* 는 실제 주·월봉 값을 일봉축에 전방채움(미래참조 없음)
  tf.W / tf.M       : 주봉·월봉 자체 축(dates/close/k5/k10/k20)
"""
import os, re, json, time, sys
import urllib.request
import pandas as pd
import FinanceDataReader as fdr

try:
    import indicators106
except ImportError:                      # 스크립트를 다른 위치에서 실행한 경우
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import indicators106

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
YEARS = 12                     # 월봉 20개(+슬로잉12) 워밍업 위해 넉넉히
KEEP_DAYS = 500                # 일봉 보관 봉수
KEEP_WEEK = 300                # 주봉 보관 봉수(약 6년)
KEEP_MONTH = 180               # 월봉 보관 봉수(15년)
TOP_N = int(os.environ.get("TOP_N", "500"))   # 시총 상위 N (코스피+코스닥 합산)
ETF_N = int(os.environ.get("ETF_N", "100"))   # 거래대금 상위 ETF N개

ETF_API = "https://finance.naver.com/api/sise/etfItemList.nhn"
# 금리·채권형 ETF는 값이 거의 움직이지 않는다. 스토캐스틱도 백분위도 뜻이 없고
# 오히려 전 종목 순위의 분모만 흐려서 뺀다.
ETF_SKIP = ("CD금리", "금리액티브", "머니마켓", "MMF", "통안", "국고채", "단기채",
            "종합채권", "회사채", "KOFR", "머니마켓액티브", "금리투자")

# (라벨, 기간, 슬로잉) — 모든 시간축 공통
TRIO = [("k5", 5, 3), ("k10", 10, 6), ("k20", 20, 12)]

INDICES = [
    ("KS11", "코스피", "INDEX"),
    ("KQ11", "코스닥", "INDEX"),
]

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}


def slow_k(df, n, slowing):
    """슬로 스토캐스틱 %K — HTS 정식.

    Σ(종가 − n기간최저) / Σ(n기간최고 − n기간최저) × 100  (슬로잉 기간 합산).
    사장님 HTS 내보내기 파일로 역산해 오차 0으로 맞춘 식이다(2026-09-17).
    """
    low = df["Low"].rolling(n).min()
    high = df["High"].rolling(n).max()
    num = (df["Close"] - low).rolling(slowing).sum()
    den = (high - low).rolling(slowing).sum()
    return (num / den.where(den != 0)) * 100.0


def resample_ohlc(df, rule):
    agg = {"High": "max", "Low": "min", "Close": "last"}
    if "Open" in df.columns:
        agg["Open"] = "first"
    r = df.resample(rule).agg(agg)
    return r.dropna(subset=["Close"])


def month_rule():
    """pandas 버전에 따라 월말 규칙 이름이 다름"""
    try:
        pd.Series(dtype=float, index=pd.DatetimeIndex([])).resample("ME")
        return "ME"
    except Exception:
        return "M"


NAVER_MV = "https://m.stock.naver.com/api/stocks/marketValue/{}?page={}&pageSize=100"


def naver_top(sosok, need):
    """네이버 시가총액 순위에서 (코드, 이름) 수집. sosok 0=코스피 1=코스닥.
    2026-09-26 — finance.naver.com/sise/sise_market_sum 이 새 구조(Next.js)로 바뀌어 아래 옛 정규식이 0건이 됐고,
    9/25 수집에서 코스피·코스닥 497종목이 목록에서 빠졌다(점검 A1). 모바일 시가총액 JSON 을 먼저 쓰고 옛 방식은 뒤에 둔다.
    ETF 는 따로 모으므로(naver_etf) 여기서는 stockEndType == 'stock' 만 — 옛 목록도 ETF 0개였다."""
    out, page = [], 1
    mk = "KOSPI" if sosok == 0 else "KOSDAQ"
    while len(out) < need and page <= 30:
        try:
            req = urllib.request.Request(NAVER_MV.format(mk, page), headers=UA)
            d = json.loads(urllib.request.urlopen(req, timeout=15).read())
        except Exception as e:
            print(f"  [경고] 시총 JSON {mk}/{page} 실패: {e}")
            break
        st = d.get("stocks") or []
        if not st:
            break
        for x in st:
            if x.get("stockEndType") != "stock":
                continue
            code = str(x.get("itemCode", ""))
            if re.fullmatch(r"\d{6}", code) and not any(c == code for c, _ in out):
                out.append((code, str(x.get("stockName", "")).strip()))
        page += 1
        time.sleep(0.2)
    if len(out) >= min(need, 20):
        return out[:need]
    print(f"  [경고] 시총 JSON {mk} {len(out)}건 — 옛 페이지 방식으로 재시도")
    out, page = [], 1
    while len(out) < need and page <= 40:
        url = f"https://finance.naver.com/sise/sise_market_sum.naver?sosok={sosok}&page={page}"
        try:
            req = urllib.request.Request(url, headers=UA)
            html = urllib.request.urlopen(req, timeout=15).read().decode("euc-kr", "ignore")
        except Exception as e:
            print(f"  [경고] 목록 {sosok}/{page} 실패: {e}")
            break
        found = re.findall(r'/item/main\.naver\?code=(\d{6})">([^<]+)</a>', html)
        if not found:
            break
        for code, name in found:
            if not any(c == code for c, _ in out):
                out.append((code, name.strip()))
        page += 1
        time.sleep(0.2)
    return out[:need]


def naver_etf(need):
    """네이버 ETF 목록에서 거래대금 상위 need개. 국내 ETF는 전부 코스피 상장이다."""
    try:
        req = urllib.request.Request(ETF_API, headers=dict(UA, Referer="https://finance.naver.com/sise/etf.naver"))
        raw = urllib.request.urlopen(req, timeout=20).read().decode("euc-kr", "ignore")
        lst = json.loads(raw)["result"]["etfItemList"]
    except Exception as e:
        print(f"[목록] ETF 실패: {str(e)[:60]}")
        return []
    lst.sort(key=lambda x: x.get("amonut") or 0, reverse=True)
    out = []
    for x in lst:
        nm = str(x.get("itemname", "")).strip()
        if not nm or any(k in nm for k in ETF_SKIP):
            continue
        out.append((str(x["itemcode"]).zfill(6), nm, "ETF"))
        if len(out) >= need:
            break
    print(f"[목록] ETF 거래대금 상위 {len(out)}종목")
    return out


def build_universe():
    """시총 상위 종목 목록. 네이버 우선, 실패 시 FDR 상장목록."""
    half = max(1, TOP_N // 2)
    ks = naver_top(0, half)
    kq = naver_top(1, TOP_N - len(ks))
    uni = [(c, n, "KOSPI") for c, n in ks] + [(c, n, "KOSDAQ") for c, n in kq]
    if len(uni) >= 20:
        print(f"[목록] 네이버 시총순위 {len(uni)}종목")
        return uni

    print("[목록] 네이버 실패 → FDR 상장목록으로 대체")
    uni = []
    for mk in ("KOSPI", "KOSDAQ"):
        try:
            df = fdr.StockListing(mk)
        except Exception as e:
            print(f"  [경고] FDR {mk} 실패: {e}")
            continue
        cols = {c.lower(): c for c in df.columns}
        ccol = cols.get("code") or cols.get("symbol")
        ncol = cols.get("name")
        mcol = cols.get("marcap") or cols.get("markcap")
        if mcol:
            df = df.sort_values(mcol, ascending=False)
        for _, r in df.head(TOP_N // 2).iterrows():
            uni.append((str(r[ccol]).zfill(6), str(r[ncol]), mk))
    print(f"[목록] FDR {len(uni)}종목")
    return uni


def r1(v):
    return None if pd.isna(v) else round(float(v), 1)


def tf_block(bars, keep):
    """리샘플된 봉으로 3형제 %K 계산 후 자체 축으로 반환"""
    if bars is None or len(bars) < 25:
        return None, {}
    ks = {lab: slow_k(bars, n, s) for lab, n, s in TRIO}
    idx = bars.index[-keep:]
    block = {
        "dates": [d.strftime("%Y-%m-%d") for d in idx],
        "close": [None if pd.isna(v) else round(float(v), 2) for v in bars["Close"].iloc[-keep:]],
    }
    for lab, _, _ in TRIO:
        block[lab] = [r1(v) for v in ks[lab].iloc[-keep:]]
    return block, ks


def process(code, name, market, start, mrule):
    df = None
    if market == "INDEX":
        try:
            df = naver_index_daily(code, start)
        except Exception as e:
            LOG.append(f"- ⚠ {code} 네이버 지수 실패 → FDR: {str(e)[:60]}")
    if df is None:
        df = fdr.DataReader(code, start)
    if df is None or len(df) < 60:
        raise ValueError(f"데이터 부족 ({0 if df is None else len(df)}행)")
    df = df.dropna(subset=["Close"])
    for c in ("High", "Low", "Open"):
        if c not in df.columns or df[c].isna().all():
            df[c] = df["Close"]
    for c in ("High", "Low", "Open"):
        df[c] = df[c].fillna(df["Close"])
    if "Volume" not in df.columns:
        df["Volume"] = float("nan")

    tail = df.tail(KEEP_DAYS)

    def num(series, nd=2):
        return [None if pd.isna(v) else round(float(v), nd) for v in series]

    out = {
        "code": code,
        "name": name,
        "market": market,
        "dates": [d.strftime("%Y-%m-%d") for d in tail.index],
        "close": num(tail["Close"]),
        # 106지표 계산에 필요한 원천 OHLCV (기존 close 는 호환 위해 유지)
        "open": num(tail["Open"]),
        "high": num(tail["High"]),
        "low": num(tail["Low"]),
        "vol": [None if pd.isna(v) else int(v) for v in tail["Volume"].fillna(0)],
        "stoch": {},
        "tf": {},
        "rows": int(len(df)),
    }

    # ── 106 보조지표 종합점수 ──
    try:
        # keep_detail 을 KEEP_DAYS 와 같게 둔다.
        # 250봉만 저장하면 카테고리 백테스트 관측창이 46회로 줄어 결론을 확정할 수 없다.
        # 500봉이면 84회 → 선별점수(이평+추세+거래량) 우위를 두 배 표본으로 재검증 가능.
        # 대가는 종목 JSON 76KB → 약 84KB.
        out["ind"] = indicators106.compute(df, keep=KEEP_DAYS, keep_detail=KEEP_DAYS)
    except Exception as e:
        out["ind"] = None
        print(f"  [경고] {code} 106지표 실패: {e}")

    # 일봉 3형제 (기존 라벨 유지)
    for lab, n, s in TRIO:
        key = {"k5": "D5", "k10": "D10", "k20": "D20"}[lab]
        out["stoch"][key] = [r1(v) for v in slow_k(df, n, s).tail(KEEP_DAYS)]

    # 주봉 / 월봉
    for tf, rule, keep, pre in (("W", "W-FRI", KEEP_WEEK, "W"), ("M", mrule, KEEP_MONTH, "M")):
        bars = resample_ohlc(df, rule)
        block, ks = tf_block(bars, keep)
        if block:
            out["tf"][tf] = block
        # 일봉축 전방채움 (해당 시점까지 확정된 봉만 사용 → 미래참조 없음)
        for lab, _, _ in TRIO:
            key = pre + {"k5": "5", "k10": "10", "k20": "20"}[lab]
            if ks:
                daily = ks[lab].reindex(tail.index, method="ffill")
                out["stoch"][key] = [r1(v) for v in daily]
            else:
                out["stoch"][key] = [None] * len(tail)
    return out


# ── 변경 기록·보호 (2026-09-26 대표 「변경 시 항상 로그를 기록, 스토리·히스토리·데이터 저장을 명심」) ──
LOG = []
CHANGE_LOG_NAME = "_변경로그.md"


def load_prev_index():
    try:
        with open(os.path.join(OUT_DIR, "index.json"), encoding="utf-8") as f:
            return json.load(f).get("tickers") or []
    except Exception:
        return []


def shrink_reason(path, new):
    """옛 파일보다 일봉 수가 줄거나 마지막 날짜가 뒤로 가면 그 까닭을 돌려준다(덮어쓰기 거부)."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            old = json.load(f)
    except Exception:
        return None
    od, nd = old.get("dates") or [], new.get("dates") or []
    if od and nd and nd[-1] < od[-1]:
        return f"마지막 날짜 {od[-1]} → {nd[-1]}"
    if len(nd) < len(od) * 0.97:
        return f"일봉 {len(od)} → {len(nd)}"
    return None


def write_change_log(prev, index, fail, built):
    """실행마다 한 묶음 — 시장별 종목 수, 목록에 새로 든·빠진 종목, 실패, 보호 조치. 저장소에 함께 커밋된다."""
    pc = {t["code"]: t for t in prev}
    nc = {t["code"]: t for t in index}

    def cnt(L):
        ms = sorted({str(t.get("market")) for t in L})
        return ", ".join(f"{m} {sum(1 for t in L if str(t.get('market')) == m)}" for m in ms)
    added = [c for c in nc if c not in pc]
    removed = [c for c in pc if c not in nc]
    lines = [f"## {built} — 종목 {len(index)} ({cnt(index)}) · 이전 {len(prev)} ({cnt(prev)})"]
    if added:
        lines.append(f"- 목록에 새로 듦 {len(added)}: " + ", ".join(f"{c} {nc[c]['name']}" for c in added[:40]) + (" …" if len(added) > 40 else ""))
    if removed:
        lines.append(f"- 목록에서 빠짐 {len(removed)} (자료 파일은 남음): " + ", ".join(f"{c} {pc[c]['name']}" for c in removed[:40]) + (" …" if len(removed) > 40 else ""))
    if fail:
        lines.append(f"- 실패 {len(fail)}: " + " / ".join(fail[:15]))
    lines += LOG
    if len(lines) == 1:
        lines.append("- 변화 없음")
    path = os.path.join(OUT_DIR, CHANGE_LOG_NAME)
    head = "" if os.path.exists(path) else "# 일봉 수집 변경 로그 (collect_stoch.py 가 실행마다 덧붙인다 · 지우지 말 것)\n\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(head + "\n".join(lines) + "\n\n")


NAVER_IDX = "https://api.stock.naver.com/chart/domestic/index/{}/day?startDateTime={}&endDateTime={}"


def naver_index_daily(code, start):
    """지수 일봉 — 네이버. 2026-09-26: FDR 의 KS11·KQ11 이 9/17 에서 멈춰(점검 A2) 네이버를 먼저 쓴다."""
    sym = {"KS11": "KOSPI", "KQ11": "KOSDAQ"}.get(code)
    if not sym:
        return None
    s_ = start.replace("-", "") + "0000"
    e_ = pd.Timestamp.today().strftime("%Y%m%d") + "2359"
    req = urllib.request.Request(NAVER_IDX.format(sym, s_, e_), headers=UA)
    rows = json.loads(urllib.request.urlopen(req, timeout=30).read())
    if not rows:
        return None
    df = pd.DataFrame({
        "Open": [r.get("openPrice") for r in rows], "High": [r.get("highPrice") for r in rows],
        "Low": [r.get("lowPrice") for r in rows], "Close": [r.get("closePrice") for r in rows],
        "Volume": [r.get("accumulatedTradingVolume") for r in rows]},
        index=pd.to_datetime([r["localDate"] for r in rows], format="%Y%m%d"))
    return df.astype(float).sort_index()


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    start = (pd.Timestamp.today() - pd.DateOffset(years=YEARS)).strftime("%Y-%m-%d")
    mrule = month_rule()
    prev = load_prev_index()
    uni = build_universe()
    prev_st = [(t["code"], t["name"], t["market"]) for t in prev if t.get("market") in ("KOSPI", "KOSDAQ")]
    if prev_st and len(uni) < len(prev_st) * 0.8:
        # 목록 원천이 무너져도 종목을 빼지 않는다 — 이전 목록을 그대로 쓴다 (2026-09-26, 점검 A1 재발 방지)
        LOG.append(f"- ⚠ 종목 목록 원천 {len(uni)}종목 < 이전 {len(prev_st)}종목의 80% → 이전 목록 유지")
        uni = prev_st
    etf = naver_etf(ETF_N)
    prev_etf = [(t["code"], t["name"], "ETF") for t in prev if t.get("market") == "ETF"]
    if prev_etf and len(etf) < len(prev_etf) * 0.8:
        LOG.append(f"- ⚠ ETF 목록 원천 {len(etf)}종목 < 이전 {len(prev_etf)}종목의 80% → 이전 목록 유지")
        etf = prev_etf
    targets = [(c, n, m) for c, n, m in INDICES] + uni + etf
    seen, uniq = set(), []
    for c, n, m in targets:
        if c in seen:
            continue
        seen.add(c); uniq.append((c, n, m))
    targets = uniq

    index, ok, fail = [], 0, []
    for i, (code, name, market) in enumerate(targets, 1):
        try:
            data = process(code, name, market, start, mrule)
            fpath = os.path.join(OUT_DIR, f"{code}.json")
            why = shrink_reason(fpath, data)
            if why:
                # 자료가 줄거나 날짜가 뒤로 가는 덮어쓰기는 하지 않는다 — 옛 파일을 그대로 둔다 (2026-09-26)
                LOG.append(f"- ⛔ {code} {name} 덮어쓰기 거부 — {why}")
                with open(fpath, encoding="utf-8") as f:
                    data = json.load(f)
            else:
                with open(fpath, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
            row = {"code": code, "name": name, "market": market}
            # 스크리너용 최신 106지표 요약 (index.json 하나만 읽어도 전 종목 순위가 나오게)
            ix = data.get("ind")
            if ix and ix.get("score"):
                sc = next((v for v in reversed(ix["score"]) if v is not None), None)
                prv = [v for v in ix["score"] if v is not None]
                row["s"] = sc
                row["d"] = None if len(prv) < 2 else round(prv[-1] - prv[-2], 1)
                row["c"] = {k: (v[-1] if v else None) for k, v in ix["cat"].items()}
                # 관행 판정 집계 — 스크리너의 본체
                st = ix.get("std") or {}
                row["n"] = {k: (st[k][-1] if st.get(k) else None) for k in ("buy", "hold", "sell")}
                row["n"]["dir"] = st.get("dir")
                ag = ix.get("agree") or []
                row["a"] = next((x for x in reversed(ag) if x is not None), None)   # 합의도
                prv = [x for x in ag if x is not None]
                row["ad"] = None if len(prv) < 2 else prv[-1] - prv[-2]             # 합의도 전일대비
                row["ca"] = {k: (v[-1] if v else None) for k, v in (ix.get("cagree") or {}).items()}
                row["p"] = data["close"][-1] if data["close"] else None
            index.append(row)
            ok += 1
            if i % 25 == 0 or i <= 3:
                w = len(data["tf"].get("W", {}).get("dates", []))
                m = len(data["tf"].get("M", {}).get("dates", []))
                print(f"  [{i}/{len(targets)}] {code} {name} ok (일{data['rows']} 주{w} 월{m})")
        except Exception as e:
            fail.append(f"{code} {name}: {e}")
        time.sleep(0.12)

    meta = {
        "built": pd.Timestamp.now(tz="Asia/Seoul").strftime("%Y-%m-%d %H:%M KST"),
        "count": ok,
        "ind106": {
            "n": 106,
            "category_w": indicators106.CATEGORY_W,
            "rank_win": indicators106.RANK_WIN,
            "buy_th": indicators106.BUY_TH,
            "sell_th": indicators106.SELL_TH,
        },
        "settings": [
            {"tf": tf, "label": lab, "n": n, "slowing": s}
            for tf in ("D", "W", "M") for lab, n, s in TRIO
        ],
        "tickers": index,
    }
    with open(os.path.join(OUT_DIR, "index.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, separators=(",", ":"))
    write_change_log(prev, index, fail, meta["built"])

    print(f"\n[완료] 성공 {ok} / 실패 {len(fail)}")
    for m in fail[:15]:
        print("  실패:", m)
    if ok == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
