# -*- coding: utf-8 -*-
"""
KIS 분봉 수집기 — 한국투자증권 Open API로 당일 1분봉을 받아 저장소에 누적한다.

KIS는 '당일 1분봉'만 제공하므로(과거 분봉 미제공) 매 거래일 모아 두는 방식으로
5·10·15·30·60·120·240분봉 히스토리를 스스로 쌓는다.

산출물
  stoch/min/raw_<code>.json : 일자별 1분봉 원본 (재계산용, 최근 KEEP_RAW_DAYS일)
  stoch/min/tf_<code>.json  : 시간축별 {dates, close, k5, k10, k20} (스캐너가 읽음)

환경변수(Actions Secrets)
  KIS_APPKEY, KIS_APPSECRET   필수
  KIS_BASE                    선택, 기본 https://openapi.koreainvestment.com:9443
"""
import os, sys, json, time, datetime
import urllib.request, urllib.parse
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "min")
BASE = os.environ.get("KIS_BASE", "https://openapi.koreainvestment.com:9443")
APPKEY = os.environ.get("KIS_APPKEY", "").strip()
APPSECRET = os.environ.get("KIS_APPSECRET", "").strip()

KEEP_RAW_DAYS = 40          # 1분봉 원본 보관 일수
KEEP_BARS = 400             # 시간축별 보관 봉수
TFS = [5, 10, 15, 30, 60, 120, 240]
TRIO = [("k5", 5, 3), ("k10", 10, 6), ("k20", 20, 12)]
OPEN_MIN = 9 * 60           # 09:00
CLOSE_MIN = 15 * 60 + 30    # 15:30


def kst_today():
    return (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).strftime("%Y%m%d")


def post_json(url, payload, headers):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def get_json(url, params, headers):
    q = urllib.parse.urlencode(params)
    req = urllib.request.Request(url + "?" + q, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def get_token():
    if not APPKEY or not APPSECRET:
        print("[중단] KIS_APPKEY / KIS_APPSECRET 시크릿이 없습니다.")
        sys.exit(1)
    d = post_json(BASE + "/oauth2/tokenP",
                  {"grant_type": "client_credentials", "appkey": APPKEY, "appsecret": APPSECRET},
                  {"content-type": "application/json"})
    tok = d.get("access_token")
    if not tok:
        print("[중단] 토큰 발급 실패:", d)
        sys.exit(1)
    return tok


def fetch_day_minutes(code, token):
    """당일 1분봉 전체를 뒤에서부터 30건씩 페이징해 수집. {분: (o,h,l,c)}"""
    url = BASE + "/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
    head = {"content-type": "application/json; charset=utf-8",
            "authorization": "Bearer " + token,
            "appkey": APPKEY, "appsecret": APPSECRET,
            "tr_id": "FHKST03010200", "custtype": "P"}
    bars, cursor, guard = {}, "153000", 0
    while guard < 20:
        guard += 1
        p = {"FID_ETC_CLS_CODE": "", "FID_COND_MRKT_DIV_CODE": "J",
             "FID_INPUT_ISCD": code, "FID_INPUT_HOUR_1": cursor, "FID_PW_DATA_INCU_YN": "N"}
        try:
            d = get_json(url, p, head)
        except Exception as e:
            print(f"  [경고] {code} {cursor} 호출 실패: {e}")
            break
        rows = d.get("output2") or []
        if not rows:
            break
        got = 0
        for r in rows:
            hh = (r.get("stck_cntg_hour") or "").zfill(6)
            if len(hh) < 4:
                continue
            m = int(hh[:2]) * 60 + int(hh[2:4])
            if m < OPEN_MIN or m > CLOSE_MIN or m in bars:
                continue
            try:
                o = float(r.get("stck_oprc") or 0); h = float(r.get("stck_hgpr") or 0)
                l = float(r.get("stck_lwpr") or 0); c = float(r.get("stck_prpr") or 0)
            except ValueError:
                continue
            if c <= 0:
                continue
            if o <= 0: o = c
            if h <= 0: h = max(o, c)
            if l <= 0: l = min(o, c)
            bars[m] = (o, h, l, c)
            got += 1
        earliest = min(int(r["stck_cntg_hour"][:2]) * 60 + int(r["stck_cntg_hour"][2:4])
                       for r in rows if (r.get("stck_cntg_hour") or "").strip())
        if earliest <= OPEN_MIN or got == 0:
            break
        nxt = earliest - 1
        cursor = f"{nxt // 60:02d}{nxt % 60:02d}00"
        time.sleep(0.12)
    return bars


def load_raw(code):
    f = os.path.join(OUT, f"raw_{code}.json")
    if os.path.exists(f):
        try:
            with open(f, encoding="utf-8") as fp:
                return json.load(fp)
        except Exception:
            pass
    return {"code": code, "days": {}}


def save_json(path, obj):
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(obj, fp, ensure_ascii=False, separators=(",", ":"))


def slow_k(df, n, slowing):
    low = df["l"].rolling(n).min()
    high = df["h"].rolling(n).max()
    rng = (high - low)
    fast = (df["c"] - low) / rng.where(rng != 0) * 100.0
    return fast.rolling(slowing).mean()


def build_frames(raw):
    """일자별 1분봉 → 연속 DataFrame"""
    recs = []
    for day in sorted(raw["days"].keys()):
        d = raw["days"][day]
        for i, m in enumerate(d["t"]):
            recs.append((day, int(m), d["o"][i], d["h"][i], d["l"][i], d["c"][i]))
    if not recs:
        return None
    df = pd.DataFrame(recs, columns=["day", "m", "o", "h", "l", "c"])
    df = df.sort_values(["day", "m"]).reset_index(drop=True)
    return df


def resample_minutes(df, tf):
    """장 시작(09:00) 기준 tf분 묶음. 일자 경계를 넘지 않는다."""
    g = ((df["m"] - OPEN_MIN) // tf).astype(int)
    key = df["day"] + "_" + g.astype(str)
    agg = df.groupby(key, sort=False).agg(day=("day", "first"), m=("m", "first"),
                                          o=("o", "first"), h=("h", "max"),
                                          l=("l", "min"), c=("c", "last"))
    agg = agg.sort_values(["day", "m"]).reset_index(drop=True)
    return agg


def tf_block(df, tf):
    bars = resample_minutes(df, tf)
    if len(bars) < 5:
        return None
    ks = {lab: slow_k(bars, n, s) for lab, n, s in TRIO}
    tail = slice(max(0, len(bars) - KEEP_BARS), len(bars))
    lab_dt = [f"{r.day[:4]}-{r.day[4:6]}-{r.day[6:]} {int(r.m)//60:02d}:{int(r.m)%60:02d}"
              for r in bars.iloc[tail].itertuples()]
    out = {"dates": lab_dt,
           "close": [round(float(v), 2) for v in bars["c"].iloc[tail]]}
    for lab, _, _ in TRIO:
        out[lab] = [None if pd.isna(v) else round(float(v), 1) for v in ks[lab].iloc[tail]]
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    wl_path = os.path.join(HERE, "watchlist.json")
    try:
        with open(wl_path, encoding="utf-8") as f:
            watch = json.load(f)
    except Exception:
        watch = ["005930"]
    if not isinstance(watch, list) or not watch:
        watch = ["005930"]

    token = get_token()
    today = kst_today()
    ok, empty = 0, 0

    for i, code in enumerate(watch, 1):
        code = str(code).zfill(6)
        bars = fetch_day_minutes(code, token)
        raw = load_raw(code)
        if bars:
            ms = sorted(bars.keys())
            raw["days"][today] = {"t": ms,
                                  "o": [bars[m][0] for m in ms],
                                  "h": [bars[m][1] for m in ms],
                                  "l": [bars[m][2] for m in ms],
                                  "c": [bars[m][3] for m in ms]}
        else:
            empty += 1
        for d in sorted(raw["days"].keys())[:-KEEP_RAW_DAYS]:
            raw["days"].pop(d, None)
        save_json(os.path.join(OUT, f"raw_{code}.json"), raw)

        df = build_frames(raw)
        tfout = {}
        if df is not None:
            for tf in TFS:
                b = tf_block(df, tf)
                if b:
                    tfout["m" + str(tf)] = b
        save_json(os.path.join(OUT, f"tf_{code}.json"), tfout)
        ok += 1
        have = ",".join(k for k in tfout)
        print(f"  [{i}/{len(watch)}] {code} 당일 {len(bars)}분봉 · 누적 {len(raw['days'])}일 · 축 [{have}]")
        time.sleep(0.15)

    idx = {"built": (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).strftime("%Y-%m-%d %H:%M KST"),
           "day": today, "codes": [str(c).zfill(6) for c in watch]}
    save_json(os.path.join(OUT, "index.json"), idx)
    print(f"\n[완료] {ok}종목 처리 · 당일 데이터 없음 {empty}종목")


if __name__ == "__main__":
    main()
