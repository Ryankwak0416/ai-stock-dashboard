# -*- coding: utf-8 -*-
"""
수급흐름 대시보드 — 데이터 수집기 (GitHub Actions에서 평일 18:40 KST 자동 실행)
KRX(pykrx)에서 수집해 money/data.json 생성:
  1) KOSPI/KOSDAQ 지수·거래대금 (시장 수급 집중도)
  2) 시장별 투자자(외국인/기관/개인) 일별 순매수
  3) 업종지수별 종가·거래대금 (관심도/로테이션)
  4) 투자자별 업종 순매수 (최근 5거래일, 종목→업종 집계)
부분 실패해도 가능한 데이터만으로 JSON을 생성한다.
"""
import json, os, time, datetime, traceback
import pandas as pd
from pykrx import stock

KST = datetime.timezone(datetime.timedelta(hours=9))
NOW = datetime.datetime.now(KST)
END = NOW.strftime("%Y%m%d")
START = (NOW - datetime.timedelta(days=110)).strftime("%Y%m%d")  # 약 70거래일
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")
SLEEP = 0.35
ERRORS = []

# 업종지수가 아닌 지수(규모/전략/테마) 제외 패턴
EXCLUDE = ["코스피", "코스닥", "대형주", "중형주", "소형주", "200", "150", "100", "50",
           "KRX", "krx", "배당", "우선주", "글로벌", "ESG", "레버리지", "인버스",
           "TR", "총수익", "프리미어", "혁신", "스타", "벤처", "신성장", "기술성장",
           "우량기업", "외국주포함", "전체지수"]

def log(msg):
    print(f"[collect] {msg}", flush=True)

def guard(fn, label, default=None):
    try:
        r = fn()
        time.sleep(SLEEP)
        return r
    except Exception as e:
        ERRORS.append(f"{label}: {type(e).__name__} {e}")
        log(f"FAIL {label}: {e}")
        traceback.print_exc()
        return default

def col_like(df, key):
    for c in df.columns:
        if key in str(c):
            return c
    return None

def is_sector(name):
    return not any(p in name for p in EXCLUDE)

def to_jo(series):
    """거래대금 시리즈를 조원 단위로 변환 (원/백만원 단위 자동 감지)"""
    s = pd.Series(series).astype(float)
    med = s[s > 0].median() if (s > 0).any() else 0
    if med > 5e10:
        return s / 1e12          # 원 → 조원
    elif med > 5e4:
        return s / 1e6           # 백만원 → 조원
    return s                     # 이미 조 단위로 보기 어려우면 그대로

def to_eok(v):
    """순매수 거래대금(원)을 억원으로"""
    return round(float(v) / 1e8, 1)

def main():
    out = {"updated": NOW.strftime("%Y-%m-%d %H:%M KST"), "errors": ERRORS}

    # ── 1) 시장 지수 + 거래대금 ─────────────────────────────
    kospi = guard(lambda: stock.get_index_ohlcv_by_date(START, END, "1001"), "KOSPI ohlcv")
    kosdaq = guard(lambda: stock.get_index_ohlcv_by_date(START, END, "2001"), "KOSDAQ ohlcv")
    if kospi is None or kospi.empty:
        raise SystemExit("KOSPI 지수 수집 실패 — 중단")

    dates_idx = kospi.index
    dates = [d.strftime("%Y-%m-%d") for d in dates_idx]
    val_col = col_like(kospi, "거래대금")
    cls_col = col_like(kospi, "종가")

    def align(df):
        return df.reindex(dates_idx).ffill() if df is not None else None

    kosdaq = align(kosdaq)
    kospi_val = to_jo(kospi[val_col]).round(3).tolist()
    kosdaq_val = to_jo(kosdaq[val_col]).round(3).tolist() if kosdaq is not None else [0] * len(dates)
    out["dates"] = dates
    out["market"] = {
        "kospi": {"close": kospi[cls_col].round(2).tolist(), "value": kospi_val},
        "kosdaq": {"close": (kosdaq[cls_col].round(2).tolist() if kosdaq is not None else []),
                   "value": kosdaq_val},
    }

    # ── 2) 시장별 투자자 순매수 (일별) ───────────────────────
    inv_out = {}
    for mkt_key, mkt in [("kospi", "KOSPI"), ("kosdaq", "KOSDAQ")]:
        df = guard(lambda m=mkt: stock.get_market_trading_value_by_date(START, END, m),
                   f"투자자 순매수 {mkt}")
        if df is None or df.empty:
            continue
        df = df.reindex(dates_idx).fillna(0)
        c_for = col_like(df, "외국인")
        c_ins = col_like(df, "기관")
        c_ind = col_like(df, "개인")
        inv_out[mkt_key] = {
            "foreign": [to_eok(v) for v in df[c_for]] if c_for else [],
            "institution": [to_eok(v) for v in df[c_ins]] if c_ins else [],
            "individual": [to_eok(v) for v in df[c_ind]] if c_ind else [],
        }
    out["investor"] = inv_out

    # ── 3) 업종지수 수집 ─────────────────────────────────────
    sector_meta = []  # (ticker, name, market)
    for mkt in ["KOSPI", "KOSDAQ"]:
        tickers = guard(lambda m=mkt: stock.get_index_ticker_list(market=m),
                        f"지수목록 {mkt}", default=[])
        for t in (tickers or []):
            name = guard(lambda tt=t: stock.get_index_ticker_name(tt), f"지수명 {t}", "")
            if name and is_sector(name):
                sector_meta.append((t, name.strip(), mkt))
    log(f"업종지수 {len(sector_meta)}개: {[n for _, n, _ in sector_meta]}")

    sectors = []
    raw_close = {}
    for t, name, mkt in sector_meta:
        df = guard(lambda tt=t: stock.get_index_ohlcv_by_date(START, END, tt), f"업종 {name}")
        if df is None or df.empty:
            continue
        df = df.reindex(dates_idx).ffill()
        c = col_like(df, "종가")
        v = col_like(df, "거래대금")
        close = df[c].astype(float)
        value = to_jo(df[v])
        if close.isna().all() or float(close.iloc[-1] or 0) == 0:
            continue
        raw_close[name] = close
        sectors.append({"ticker": t, "name": name, "market": mkt,
                        "close": close.round(2).tolist(),
                        "value": value.round(4).tolist()})

    # 파생지표 계산
    n = len(dates)
    mkt_close = {"KOSPI": pd.Series(kospi[cls_col].astype(float).values, index=range(n)),
                 "KOSDAQ": pd.Series(kosdaq[cls_col].astype(float).values, index=range(n))
                 if kosdaq is not None else None}
    # 시장별 업종 거래대금 합 (비중 분모)
    sum5 = {"KOSPI": 0.0, "KOSDAQ": 0.0}
    sum5_prev = {"KOSPI": 0.0, "KOSDAQ": 0.0}
    for s in sectors:
        v = pd.Series(s["value"])
        sum5[s["market"]] += float(v.iloc[-5:].mean())
        sum5_prev[s["market"]] += float(v.iloc[-10:-5].mean()) if n >= 10 else 0.0

    for s in sectors:
        cl = pd.Series(s["close"], dtype=float)
        v = pd.Series(s["value"], dtype=float)

        def pct(k):
            if n > k and cl.iloc[-1 - k] > 0:
                return round(100 * (cl.iloc[-1] / cl.iloc[-1 - k] - 1), 2)
            return None

        s["chg1"], s["chg5"], s["chg20"] = pct(1), pct(5), pct(20)
        v5, v5p = float(v.iloc[-5:].mean()), float(v.iloc[-10:-5].mean()) if n >= 10 else 0.0
        denom, denom_p = sum5[s["market"]], sum5_prev[s["market"]]
        s["valShare"] = round(100 * v5 / denom, 2) if denom > 0 else None
        s["valSharePrev"] = round(100 * v5p / denom_p, 2) if denom_p > 0 else None
        s["val5d"] = round(v5, 3)

        # RRG: x=20일 상대강도(%), y=5일 상대모멘텀(%) — 시장지수 대비
        mc = mkt_close.get(s["market"])
        if mc is not None and len(mc) == n:
            ratio = cl.reset_index(drop=True) / mc.reset_index(drop=True)
            base = ratio.rolling(20, min_periods=10).mean()
            trail = []
            for k in range(5, -1, -1):  # 5일 전 → 오늘
                i = n - 1 - k
                if i >= 5 and pd.notna(base.iloc[i]) and base.iloc[i] > 0 and ratio.iloc[i - 5] > 0:
                    x = round(100 * (ratio.iloc[i] / base.iloc[i] - 1), 2)
                    y = round(100 * (ratio.iloc[i] / ratio.iloc[i - 5] - 1), 2)
                    trail.append([x, y])
            if trail:
                s["rrg"] = trail  # 마지막 원소가 오늘
        # 차트 경량화: 최근 30일만 유지
        s["close"] = s["close"][-30:]
        s["value"] = s["value"][-30:]
    out["sectors"] = sectors

    # ── 4) 종목 → 업종 매핑 (지수 구성종목) ──────────────────
    code2sec = {}
    for t, name, mkt in sector_meta:
        codes = guard(lambda tt=t: stock.get_index_portfolio_deposit_file(tt),
                      f"구성종목 {name}", default=[])
        for c in (codes or []):
            code2sec[c] = name
    log(f"업종 매핑 종목수 {len(code2sec)}")

    # ── 5) 투자자별 업종 순매수 (최근 5거래일) ────────────────
    d5 = dates_idx[-5].strftime("%Y%m%d") if n >= 5 else START
    inv_sector, top_stocks = {}, {}
    for inv in ["외국인", "기관합계", "개인"]:
        agg, tops = {}, []
        for mkt in ["KOSPI", "KOSDAQ"]:
            df = guard(lambda m=mkt, i=inv: stock.get_market_net_purchases_of_equities(d5, END, m, i),
                       f"순매수 {mkt} {inv}")
            if df is None or df.empty:
                continue
            ncol = col_like(df, "순매수거래대금")
            mcol = col_like(df, "종목명")
            if not ncol:
                continue
            for code, row in df.iterrows():
                net = float(row[ncol])
                sec = code2sec.get(str(code))
                if sec:
                    agg[sec] = agg.get(sec, 0.0) + net
                nm = str(row[mcol]) if mcol else str(code)
                tops.append({"name": nm, "net": to_eok(net),
                             "sector": code2sec.get(str(code), ""), "market": mkt})
        inv_sector[inv] = sorted(
            [{"sector": k, "net": to_eok(v)} for k, v in agg.items()],
            key=lambda x: -x["net"])
        tops.sort(key=lambda x: -abs(x["net"]))
        top_stocks[inv] = sorted(tops, key=lambda x: -x["net"])[:10] + \
                          sorted(tops, key=lambda x: x["net"])[:10]
    out["investorSector"] = inv_sector
    out["topStocks"] = top_stocks

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    log(f"저장 완료 {OUT} (업종 {len(sectors)}개, 오류 {len(ERRORS)}건)")

if __name__ == "__main__":
    main()
