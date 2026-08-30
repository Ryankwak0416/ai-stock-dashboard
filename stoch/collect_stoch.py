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

# (라벨, 기간, 슬로잉) — 모든 시간축 공통
TRIO = [("k5", 5, 3), ("k10", 10, 6), ("k20", 20, 12)]

INDICES = [
    ("KS11", "코스피", "INDEX"),
    ("KQ11", "코스닥", "INDEX"),
]

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}


def slow_k(df, n, slowing):
    """슬로 스토캐스틱 %K = SMA(fast %K, slowing)"""
    low = df["Low"].rolling(n).min()
    high = df["High"].rolling(n).max()
    rng = (high - low)
    fast = (df["Close"] - low) / rng.where(rng != 0) * 100.0
    return fast.rolling(slowing).mean()


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


def naver_top(sosok, need):
    """네이버 시가총액 순위에서 (코드, 이름) 수집. sosok 0=코스피 1=코스닥"""
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


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    start = (pd.Timestamp.today() - pd.DateOffset(years=YEARS)).strftime("%Y-%m-%d")
    mrule = month_rule()
    targets = [(c, n, m) for c, n, m in INDICES] + build_universe()

    index, ok, fail = [], 0, []
    for i, (code, name, market) in enumerate(targets, 1):
        try:
            data = process(code, name, market, start, mrule)
            with open(os.path.join(OUT_DIR, f"{code}.json"), "w", encoding="utf-8") as f:
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
                row["n"] = {k: (v[-1] if v else None) for k, v in ix["cnt"].items()}
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

    print(f"\n[완료] 성공 {ok} / 실패 {len(fail)}")
    for m in fail[:15]:
        print("  실패:", m)
    if ok == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
