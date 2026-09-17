# -*- coding: utf-8 -*-
"""
분봉 수집기 — 스토캐스틱 주관 매수매도 타이밍용.

야후 파이낸스에서 1·5·30·60분봉을 받아 저장소에 누적하고,
10·120·240분봉은 하루 안에서 봉을 묶어 만든다.
각 시간축마다 3형제 Slow 스토캐스틱(%K·%D)을 계산해 저장한다.

  막내 = Slow %K 5,3  / %D 3
  둘째 = Slow %K 10,6 / %D 6
  큰형 = Slow %K 20,12 / %D 12

야후 보유 한도(2026-09 실측)
  1분봉  8일   /  5분봉 60일  /  30분봉 60일  /  60분봉 730일
한도를 넘는 구간은 매일 받아서 누적해야 늘어난다. 그래서 이 수집기는
기존 파일을 읽어 새로 받은 봉과 합치고 중복을 제거한다.

★ 야후 한국 분봉은 09:00~14:55까지만 준다(장 마감 35분 누락).
  그래서 네이버 1분봉(09:00~15:30 전 구간, 종가만 제공)을 받아
  15:00 이후 봉을 만들어 메운다. 고가·저가는 그 구간 1분 종가의
  최대·최소로 채운다 — 1분 단위라 실제 고저와 거의 차이가 없다.

산출물
  stoch/min/<code>.json
    raw  : {1m,5m,30m,60m} 원본 OHLC (재계산·누적용)
    sig  : {1m,5m,10m,30m,60m,120m,240m} 시각·종가·3형제 %K/%D
"""
import os, sys, json, gzip, time, datetime, warnings, re
import urllib.request
import pandas as pd
import numpy as np

warnings.filterwarnings("ignore")

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "min")
RAW = os.path.join(OUT, "raw")
SIG_BARS = 300          # 화면용으로 남길 봉 수 (백테스트는 raw에서 재계산)
# 누적 대상. 60m도 저장한다 — 야후가 3년을 주긴 하지만, 검증(백테스트)이
# 매번 야후를 다시 부르지 않고 저장소만 읽고 끝내도록 하기 위해서다.
ACC = ("1m", "5m", "30m", "60m")

# 야후에서 직접 받는 시간축: (라벨, interval, period)
FETCH = [("1m", "1m", "8d"), ("5m", "5m", "60d"), ("30m", "30m", "60d"), ("60m", "60m", "730d")]
# 묶어서 만드는 시간축: (라벨, 원본라벨, 묶을 봉수)
DERIVE = [("10m", "5m", 2), ("120m", "60m", 2), ("240m", "60m", 4)]
# 시간축별 보관 봉수
KEEP = {"1m": 7800, "5m": 4700, "10m": 2400, "30m": 1600, "60m": 4400, "120m": 2200, "240m": 1200}
TRIO = [("k5", 5, 3, 3), ("k10", 10, 6, 6), ("k20", 20, 12, 12)]   # 이름, 기간n, 슬로잉, %D기간


def slow_stoch(high, low, close, n, slowing, dper):
    """Slow %K / Slow %D — HTS 정식.

    2026-09-17에 사장님 HTS가 내보낸 60분봉 엑셀(KODEX 반도체레버리지, 900봉)로
    역산해 오차 0.0000으로 맞춘 식이다. 이전에 쓰던 SMA(Fast %K) 방식은 평균 1.5~1.8,
    최대 22포인트까지 벌어져 840봉 중 18봉에서 20/80 판정 자체가 달랐다.

      Slow %K = Σ(종가 − n기간최저) / Σ(n기간최고 − n기간최저) × 100   (슬로잉 기간 합산)
      Slow %D = Slow %K의 지수이동평균(EMA, α = 2/(dper+1))
    """
    hh = high.rolling(n, min_periods=n).max()
    ll = low.rolling(n, min_periods=n).min()
    num = (close - ll).rolling(slowing, min_periods=slowing).sum()
    den = (hh - ll).rolling(slowing, min_periods=slowing).sum()
    slow_k = (num / den.replace(0, np.nan)) * 100.0
    slow_d = slow_k.ewm(span=dper, adjust=False).mean()
    slow_d = slow_d.where(slow_k.notna())
    return slow_k, slow_d


def chunk_by_day(df, k):
    """하루 안에서 앞에서부터 k개씩 묶는다. 캘린더 리샘플과 달리 09:00 기준이 안 어긋난다."""
    if df.empty:
        return df
    out = []
    for _, g in df.groupby(df.index.normalize(), sort=True):
        g = g.sort_index()
        for i in range(0, len(g), k):
            b = g.iloc[i:i + k]
            out.append((b.index[0], b["h"].max(), b["l"].min(), b["c"].iloc[-1]))
    r = pd.DataFrame(out, columns=["t", "h", "l", "c"]).set_index("t")
    return r.sort_index()


def fetch(yf, ticker, interval, period):
    for attempt in range(3):
        try:
            df = yf.download(ticker, interval=interval, period=period,
                             progress=False, auto_adjust=False, threads=False)
            if df is None or df.empty:
                return pd.DataFrame()
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
            df = df.rename(columns={"Open": "o", "High": "h", "Low": "l", "Close": "c"})
            df = df[["h", "l", "c"]].dropna()
            df.index = pd.to_datetime(df.index)
            return df
        except Exception as e:
            if attempt == 2:
                print(f"    ! {interval} 실패: {str(e)[:60]}")
                return pd.DataFrame()
            time.sleep(2)
    return pd.DataFrame()


NAVER = "https://fchart.stock.naver.com/sise.nhn?symbol={}&timeframe=minute&count=3000&requestType=0"


def fetch_naver_1m(code):
    """네이버 1분봉(종가만). 09:00~15:30 전 구간을 준다."""
    try:
        req = urllib.request.Request(NAVER.format(code), headers={"User-Agent": "Mozilla/5.0"})
        raw = urllib.request.urlopen(req, timeout=20).read().decode("euc-kr", "ignore")
    except Exception as e:
        print(f"    ! 네이버 실패: {str(e)[:50]}")
        return pd.DataFrame()
    ts, cs = [], []
    for d in re.findall(r'data="([^"]+)"', raw):
        f = d.split("|")
        if len(f) < 5 or f[4] in ("null", ""):
            continue
        try:
            ts.append(pd.Timestamp(f[0][:4] + "-" + f[0][4:6] + "-" + f[0][6:8] + " "
                                   + f[0][8:10] + ":" + f[0][10:12], tz="Asia/Seoul"))
            cs.append(float(f[4]))
        except Exception:
            continue
    if not ts:
        return pd.DataFrame()
    return pd.DataFrame({"c": cs}, index=pd.DatetimeIndex(ts)).sort_index()


def late_bars(nv, minutes):
    """네이버 1분 종가로 15:00 이후 봉을 만든다. h/l는 1분 종가의 최대·최소."""
    if nv.empty:
        return pd.DataFrame()
    late = nv[(nv.index.hour == 15) & (nv.index.minute <= 30)]   # 정규장 마감 15:30까지만
    if late.empty:
        return pd.DataFrame()
    key = late.index.normalize() + pd.to_timedelta(
        15 * 60 + ((late.index.hour - 15) * 60 + late.index.minute) // minutes * minutes, unit="m")
    g = late.groupby(key)["c"]
    out = pd.DataFrame({"h": g.max(), "l": g.min(), "c": g.last()})
    out.index.name = None
    return out


def load_raw(code):
    """누적 원본(gz)을 DataFrame으로 되살린다. 시각은 epoch 초."""
    path = os.path.join(RAW, f"{code}.json.gz")
    if not os.path.exists(path):
        return {}
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return {}
    out = {}
    for tf, v in (d or {}).items():
        if not v.get("t"):
            continue
        df = pd.DataFrame({"h": v["h"], "l": v["l"], "c": v["c"]},
                          index=pd.to_datetime(v["t"], unit="s", utc=True))
        out[tf] = df.tz_convert("Asia/Seoul")
    return out


def save_raw(code, raw):
    os.makedirs(RAW, exist_ok=True)
    doc = {tf: {"t": [int(t.timestamp()) for t in d.index],
                "h": [round(float(x), 2) for x in d["h"]],
                "l": [round(float(x), 2) for x in d["l"]],
                "c": [round(float(x), 2) for x in d["c"]]}
           for tf, d in raw.items() if tf in ACC and not d.empty}
    with gzip.open(os.path.join(RAW, f"{code}.json.gz"), "wt", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))


def merge(old, new):
    if old is None or old.empty:
        return new
    if new is None or new.empty:
        return old
    if old.index.tz is None:
        old.index = old.index.tz_localize("Asia/Seoul")
    if new.index.tz is None:
        new.index = new.index.tz_localize("Asia/Seoul")
    both = pd.concat([old, new])
    both = both[~both.index.duplicated(keep="last")].sort_index()
    return both


def sig_block(df, keep):
    """3형제 %K·%D를 계산해 저장용 dict로."""
    if df.empty or len(df) < 40:
        return None
    o = {"t": [], "c": []}
    k = {}
    for name, n, sl, dp in TRIO:
        sk, sd = slow_stoch(df["h"], df["l"], df["c"], n, sl, dp)
        k[name + "k"] = sk
        k[name + "d"] = sd
    tail = df.tail(keep)
    idx = tail.index
    o["t"] = [int(t.timestamp()) for t in idx]
    o["c"] = [round(float(x), 2) for x in tail["c"]]
    for key, ser in k.items():
        o[key] = [None if pd.isna(x) else int(round(float(x))) for x in ser.reindex(idx)]
    return o


def main():
    try:
        import yfinance as yf
    except ImportError:
        print("yfinance 없음 — pip install yfinance");  sys.exit(1)

    os.makedirs(OUT, exist_ok=True)
    wl = json.load(open(os.path.join(HERE, "watchlist.json"), encoding="utf-8"))
    names = {}
    npath = os.path.join(HERE, "data", "index.json")
    if os.path.exists(npath):
        try:
            for t in json.load(open(npath, encoding="utf-8")).get("tickers", []):
                names[t["code"]] = (t.get("name"), t.get("market"))
        except Exception:
            pass

    ok = 0
    for i, code in enumerate(wl, 1):
        nm, mk = names.get(code, (code, None))
        suffix = ".KQ" if mk == "KOSDAQ" else ".KS"
        ticker = code + suffix
        path = os.path.join(OUT, f"{code}.json")
        raw = load_raw(code)

        nv = fetch_naver_1m(code)
        got = []
        for label, interval, period in FETCH:
            new = fetch(yf, ticker, interval, period)
            if new.empty and label not in raw:
                continue
            raw[label] = merge(raw.get(label), new).tail(KEEP[label])
            got.append(f"{label}:{len(raw[label])}")
            time.sleep(0.4)

        # 야후가 빠뜨린 15:00~15:30 구간을 네이버로 메운다
        if not nv.empty:
            one = pd.DataFrame({"h": nv["c"], "l": nv["c"], "c": nv["c"]})
            lateMask = (one.index.hour == 15) & (one.index.minute <= 30)
            raw["1m"] = merge(raw.get("1m"), one[lateMask]).tail(KEEP["1m"])
            for label, mins in (("5m", 5), ("30m", 30), ("60m", 60)):
                lb = late_bars(nv, mins)
                if not lb.empty:
                    raw[label] = merge(raw.get(label), lb).tail(KEEP[label])
            got.append("naver:+" + str(int(((nv.index.hour == 15) & (nv.index.minute <= 30)).sum())))

        if not raw:
            print(f"[{i}/{len(wl)}] {code} {nm} — 데이터 없음")
            continue

        # 파생 시간축
        allt = dict(raw)
        for label, src, k in DERIVE:
            if src in raw and not raw[src].empty:
                allt[label] = chunk_by_day(raw[src], k).tail(KEEP[label])

        sig = {}
        for label in ["1m", "5m", "10m", "30m", "60m", "120m", "240m"]:
            if label in allt:
                b = sig_block(allt[label], SIG_BARS)
                if b:
                    sig[label] = b

        save_raw(code, raw)
        doc = {
            "code": code, "name": nm, "market": mk,
            "updated": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "bars": {tf: len(d) for tf, d in allt.items()},
            "sig": sig,
        }
        json.dump(doc, open(path, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
        ok += 1
        print(f"[{i}/{len(wl)}] {code} {nm} — {' '.join(got)} ({os.path.getsize(path)//1024}KB)")

    print(f"완료: {ok}/{len(wl)}종목")


if __name__ == "__main__":
    main()
