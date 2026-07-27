# -*- coding: utf-8 -*-
"""
멀티 타임프레임 스토캐스틱(슬로) 수집기
- 일봉 OHLC 하나로 일/주/월 3계층 x 단/중/장 3종 = 9종 %K 계산
- 종목별 JSON을 data/<code>.json 으로 저장 (정적 페이지가 필요할 때만 로드)

파라미터(일봉 기준 환산):
  일  단5,3  중10,6  장20,12
  주  단25,15 중50,30 장100,60      (주=일봉 x5)
  월  단100,60 중200,120 장400,240  (월=일봉 x20)
  ※ %K만 사용(%D 미표시)이므로 (기간, 슬로잉)만 필요
"""
import os, re, json, time, sys
import urllib.request
import pandas as pd
import FinanceDataReader as fdr

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
YEARS = 7                      # 400,240 계산 워밍업 위해 넉넉히
KEEP_DAYS = 500                # 화면에 쓸 최근 거래일 수
TOP_N = int(os.environ.get("TOP_N", "500"))   # 시총 상위 N (코스피+코스닥 합산)

# (라벨, 기간, 슬로잉, 시간축, 등급)
SETTINGS = [
    ("D5",   5,   3,   "day",   "short"),
    ("D10",  10,  6,   "day",   "mid"),
    ("D20",  20,  12,  "day",   "long"),
    ("W5",   25,  15,  "week",  "short"),
    ("W10",  50,  30,  "week",  "mid"),
    ("W20",  100, 60,  "week",  "long"),
    ("M5",   100, 60,  "month", "short"),
    ("M10",  200, 120, "month", "mid"),
    ("M20",  400, 240, "month", "long"),
]

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


def process(code, name, market, start):
    df = fdr.DataReader(code, start)
    if df is None or len(df) < 60:
        raise ValueError(f"데이터 부족 ({0 if df is None else len(df)}행)")
    df = df.dropna(subset=["Close"])
    for c in ("High", "Low"):
        if c not in df.columns or df[c].isna().all():
            df[c] = df["Close"]
    df["High"] = df["High"].fillna(df["Close"])
    df["Low"] = df["Low"].fillna(df["Close"])

    series = {}
    for label, n, s, _tf, _tier in SETTINGS:
        series[label] = slow_k(df, n, s)

    tail = df.tail(KEEP_DAYS)
    out = {
        "code": code,
        "name": name,
        "market": market,
        "dates": [d.strftime("%Y-%m-%d") for d in tail.index],
        "close": [None if pd.isna(v) else round(float(v), 2) for v in tail["Close"]],
        "stoch": {},
        "rows": int(len(df)),
    }
    for label in series:
        vals = series[label].tail(KEEP_DAYS)
        out["stoch"][label] = [None if pd.isna(v) else round(float(v), 1) for v in vals]
    return out


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    start = (pd.Timestamp.today() - pd.DateOffset(years=YEARS)).strftime("%Y-%m-%d")
    targets = [(c, n, m) for c, n, m in INDICES] + build_universe()

    index, ok, fail = [], 0, []
    for i, (code, name, market) in enumerate(targets, 1):
        try:
            data = process(code, name, market, start)
            with open(os.path.join(OUT_DIR, f"{code}.json"), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
            index.append({"code": code, "name": name, "market": market})
            ok += 1
            if i % 25 == 0 or i <= 3:
                print(f"  [{i}/{len(targets)}] {code} {name} ok ({data['rows']}행)")
        except Exception as e:
            fail.append(f"{code} {name}: {e}")
        time.sleep(0.12)

    meta = {
        "built": pd.Timestamp.now(tz="Asia/Seoul").strftime("%Y-%m-%d %H:%M KST"),
        "count": ok,
        "settings": [
            {"label": l, "n": n, "slowing": s, "tf": tf, "tier": t}
            for l, n, s, tf, t in SETTINGS
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
