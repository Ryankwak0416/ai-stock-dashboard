#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
60분봉 매매세팅 검증 — 재현용 하네스 (2026-09-18 작성)

왜 있는가
  2026-09-17 세션에서 이 검증을 임시 스크립트로 돌리고 숫자만 문서에 옮겼다.
  스크립트가 남지 않아 다음 세션에서 재현이 불가능했다. 그래서 저장소에 넣는다.
  규칙을 바꾸거나 인버스를 빼기로 정하면 이 파일만 고쳐 다시 돌린다.

입력   stoch/min/raw/<code>.json.gz  ({1m,5m,30m,60m} OHLC 누적 원본)
출력   표준출력에 표 4개 (전체 사이클 / 청산규칙 / 240분 수준 / 종목별)

규칙 (claude/스토캐스틱_주관매수매도_기준.md §0-1 기준)
  사이클 시작 = 60분 큰형(20,12,12) %K가 20 아래로 내려오는 봉
  진입        = 큰형이 20 위로 복귀하는 봉 (반등 확인)
  사이클 한계 = 다음 «20 아래로 내려오는 봉»
  청산 후보   = 데드크로스(80 위에서 %K가 %D 하향돌파) / 80 이탈 / 3봉 꺾임 / 80 도달
  무산 처리   = held(사이클 넘겨서라도 데드크로스까지 대기) / cut(다음 20↓에서 손절)

사용
  python3 stoch/verify_setting.py                 # 전체
  python3 stoch/verify_setting.py --exclude-inverse
  python3 stoch/verify_setting.py --only 000660
"""
import os, sys, json, gzip, glob, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "min", "raw")

# 인버스·레버리지 — §2② 판단 대기 항목
INVERSE = {"252670", "251340"}
LEVERAGE = {"122630", "233740"}


# ─────────────────────────── 지표 ───────────────────────────
def slow_stoch(h, l, c, n, sl, dp):
    """HTS 정식. %K = Σ(종가−최저)/Σ(최고−최저)×100, %D = EMA(%K).
    사장님 HTS 내보내기 900봉과 오차 0.0000으로 맞춘 식이다."""
    N = len(c)
    hi = [None] * N
    lo = [None] * N
    for i in range(n - 1, N):
        w_h = h[i - n + 1:i + 1]
        w_l = l[i - n + 1:i + 1]
        hi[i] = max(w_h)
        lo[i] = min(w_l)
    k = [None] * N
    for i in range(n + sl - 2, N):
        num = den = 0.0
        ok = True
        for j in range(i - sl + 1, i + 1):
            if hi[j] is None:
                ok = False
                break
            num += c[j] - lo[j]
            den += hi[j] - lo[j]
        if ok and den > 0:
            k[i] = num / den * 100.0
    d = [None] * N
    a = 2.0 / (dp + 1)
    p = None
    for i in range(N):
        if k[i] is None:
            continue
        p = k[i] if p is None else p + a * (k[i] - p)
        d[i] = p
    return k, d


def chunk_day(bars, n):
    """하루 안에서 앞에서부터 n개씩 묶는다. collect_min.chunk_by_day와 동일해야 한다 —
    ① 마지막 자투리 묶음도 버리지 않는다(한국장 60분봉은 하루 7개라 4+3이 된다)
    ② 봉 시각은 묶음의 «첫» 봉 시각이다
    이 둘을 어기면 240분봉 개수가 절반이 되고 240분 집계가 앱과 달라진다."""
    t, h, l, c = bars["t"], bars["h"], bars["l"], bars["c"]
    out = {"t": [], "h": [], "l": [], "c": []}
    day = None
    buf = []
    def flush():
        for i in range(0, len(buf), n):
            g = buf[i:i + n]
            out["t"].append(g[0][0])
            out["h"].append(max(x[1] for x in g))
            out["l"].append(min(x[2] for x in g))
            out["c"].append(g[-1][3])
    for i in range(len(t)):
        dkey = t[i] // 86400
        if day is None:
            day = dkey
        elif dkey != day:
            flush()
            buf = []
            day = dkey
        buf.append((t[i], h[i], l[i], c[i]))
    if buf:
        flush()
    return out


def series(bars):
    h, l, c = bars["h"], bars["l"], bars["c"]
    k5, d5 = slow_stoch(h, l, c, 5, 3, 3)
    k10, d10 = slow_stoch(h, l, c, 10, 6, 6)
    k20, d20 = slow_stoch(h, l, c, 20, 12, 12)
    return {"t": bars["t"], "c": c,
            "k5": k5, "k10": k10, "k20": k20, "d20": d20}


def clock_chunk(bars, mins):
    """1분봉을 09:00(KST) 기점 mins분 단위로 묶는다 — collect_min.clock_chunk·페이지 chunkClock과 같은 규칙."""
    t, h, l, c = bars["t"], bars["h"], bars["l"], bars["c"]
    out = {"t": [], "h": [], "l": [], "c": []}
    key = None
    step = mins * 60
    for i in range(len(t)):
        since9 = ((t[i] + 32400) % 86400) - 32400
        if since9 < 0:
            continue
        k = t[i] - since9 + (since9 // step) * step
        if k != key:
            key = k
            out["t"].append(k); out["h"].append(h[i]); out["l"].append(l[i]); out["c"].append(c[i])
        else:
            if h[i] > out["h"][-1]: out["h"][-1] = h[i]
            if l[i] < out["l"][-1]: out["l"][-1] = l[i]
            out["c"][-1] = c[i]
    return out


# ─────────────── 3형제 매수 규칙 (2026-09-18 대표 지시 · 페이지 buySig/sellSig/pairUp 과 동일) ───────────────
BUYP = dict(FLOOR=20, RISE=20, WIN1=12, WIN2=12)   # 2026-09-19 정정: 큰형이 FLOOR 아래로 내려와 있다가 올라가는 첫 봉
TFS_ALL = ["1m", "3m", "5m", "10m", "30m", "60m", "120m", "240m"]


def state_at(r, i):
    v = (r["k5"][i], r["k10"][i], r["k20"][i])
    if None in v:
        return None
    if all(x <= 20 for x in v):
        return 2
    if all(x >= 80 for x in v):
        return -2
    return 0


# 규칙 목록 — 페이지 BUY_RULES·SELL_RULES 와 같다. 규칙은 여기에 «더한다» (2026-09-19 대표).
def buy_rule1(r, P=BUYP):
    """① 3형제 동시 FLOOR 이하가 새로 성립한 봉 (종전 적극매수)."""
    return [i for i in range(1, len(r["c"])) if state_at(r, i) == 2 and state_at(r, i - 1) != 2]


def buy_rule2(r, P=BUYP):
    """② 막내 바닥 → 둘째 바닥 → 둘 다 RISE 이상 회복 → 큰형이 FLOOR 아래에서 올라가는 첫 봉."""
    a, b, g = r["k5"], r["k10"], r["k20"]
    N = len(a)
    def tr(x, i):
        return (x[i] is not None and x[i - 1] is not None and x[i + 1] is not None
                and x[i] <= x[i - 1] and x[i + 1] > x[i] and x[i] <= P["FLOOR"])
    out, t1, t2, used = [], None, None, False
    for i in range(1, N - 1):
        if tr(a, i):
            t1, t2, used = i, None, False
        if t1 is not None and t2 is None and i >= t1 and i - t1 <= P["WIN1"] and tr(b, i):
            t2, used = i, False
        if (t2 is not None and not used and i > t2 and i - t2 <= P["WIN2"]
                and None not in (a[i], b[i], g[i], g[i - 1])
                and a[i] - a[t1] >= P["RISE"] and b[i] - b[t2] >= P["RISE"]
                and g[i - 1] <= P["FLOOR"] and g[i] > g[i - 1]):
            out.append(i)
            used = True
    return out


def sell_rule1(r, P=BUYP):
    return [i for i in range(1, len(r["c"])) if state_at(r, i) == -2 and state_at(r, i - 1) != -2]


def sell_rule2(r, P=BUYP):
    a, b, g = r["k5"], r["k10"], r["k20"]
    N = len(a)
    TOP = 100 - P["FLOOR"]
    def pk(x, i):
        return (x[i] is not None and x[i - 1] is not None and x[i + 1] is not None
                and x[i] >= x[i - 1] and x[i + 1] < x[i] and x[i] >= TOP)
    out, t1, t2, used = [], None, None, False
    for i in range(1, N - 1):
        if pk(a, i):
            t1, t2, used = i, None, False
        if t1 is not None and t2 is None and i >= t1 and i - t1 <= P["WIN1"] and pk(b, i):
            t2, used = i, False
        if (t2 is not None and not used and i > t2 and i - t2 <= P["WIN2"]
                and None not in (a[i], b[i], g[i], g[i - 1])
                and a[t1] - a[i] >= P["RISE"] and b[t2] - b[i] >= P["RISE"]
                and g[i - 1] >= TOP and g[i] < g[i - 1]):
            out.append(i)
            used = True
    return out


def buy_rule3(r, P=BUYP):
    """③ 막내·둘째가 WIN1봉 안에 FLOOR 이하였고, 큰형이 FLOOR 이하에서 내려가다 처음 위로 꺾이는 봉."""
    a, b, g = r["k5"], r["k10"], r["k20"]
    def rec(x, i):
        return any(x[j] is not None and x[j] <= P["FLOOR"] for j in range(max(1, i - P["WIN1"]), i + 1))
    return [i for i in range(2, len(a)) if None not in (g[i], g[i - 1], g[i - 2])
            and g[i - 1] <= P["FLOOR"] and g[i - 1] <= g[i - 2] and g[i] > g[i - 1] and rec(a, i) and rec(b, i)]


def sell_rule3(r, P=BUYP):
    a, b, g = r["k5"], r["k10"], r["k20"]
    TOP = 100 - P["FLOOR"]
    def rec(x, i):
        return any(x[j] is not None and x[j] >= TOP for j in range(max(1, i - P["WIN1"]), i + 1))
    return [i for i in range(2, len(a)) if None not in (g[i], g[i - 1], g[i - 2])
            and g[i - 1] >= TOP and g[i - 1] >= g[i - 2] and g[i] < g[i - 1] and rec(a, i) and rec(b, i)]


BUY_RULES = [("①", buy_rule1), ("②", buy_rule2), ("③", buy_rule3)]
SELL_RULES = [("①", sell_rule1), ("②", sell_rule2), ("③", sell_rule3)]


def sig_union(rules, r):
    return sorted({i for _, fn in rules for i in fn(r)})


def buy_sig(r):
    return sig_union(BUY_RULES, r)


def sell_sig(r, mode="dead"):
    if mode in ("rule", "aggr"):
        return sig_union(SELL_RULES, r)
    g, gd = r["k20"], r["d20"]
    return [i for i in range(1, len(g)) if None not in (g[i], gd[i], g[i - 1], gd[i - 1])
            and g[i] < gd[i] and g[i - 1] >= gd[i - 1] and g[i - 1] >= 80]


def pair_up(r, buys, sells):
    c = r["c"]
    out, si, hold, dup, opn = [], 0, -1, 0, None
    for i in buys:
        if i <= hold:
            dup += 1
            continue
        while si < len(sells) and sells[si] <= i:
            si += 1
        if si >= len(sells):
            opn = i
            break
        j = sells[si]
        out.append(((c[j] - c[i]) / c[i] * 100.0, j - i))
        hold = j
    return out, dup, opn


def pair_row(name, pairs, opn):
    if not pairs:
        return f"  {name:<6} {'-':>6}"
    n = len(pairs)
    rets = [x[0] for x in pairs]
    win = sum(1 for x in rets if x > 0) / n * 100
    bars = sum(x[1] for x in pairs) / n
    return (f"  {name:<6} {n:>5}건  승률 {win:>4.0f}%  평균 {sum(rets)/n:>+7.2f}%  "
            f"최악 {min(rets):>+7.1f}%  최고 {max(rets):>+7.1f}%  보유 {bars:>5.0f}봉  진행중 {opn}")



# ─────────────────────── 사이클 추출 ───────────────────────
def g240_at(r240, ts):
    """진입 시각 이하의 마지막 240분봉 큰형 %K."""
    t = r240["t"]
    lo, hi = 0, len(t) - 1
    best = None
    while lo <= hi:
        m = (lo + hi) // 2
        if t[m] <= ts:
            best = m
            lo = m + 1
        else:
            hi = m - 1
    if best is None:
        return None
    return r240["k20"][best]


def split_avg(r5, t0, t1, P=BUYP):
    """5분 분할매수 평균가 — 페이지 splitAvg 와 같다. [t0,t1) 동안 5분 막내·둘째·큰형이 각각 FLOOR 이하 바닥을 찍을 때마다
    다음 봉 종가를 한 몫으로 평균."""
    if r5 is None:
        return 0, None
    ts, c = r5["t"], r5["c"]
    K = (r5["k5"], r5["k10"], r5["k20"])
    import bisect
    i0 = bisect.bisect_left(ts, t0)
    px = []
    i = max(1, i0)
    while i < len(ts) - 1 and ts[i] < t1:
        for x in K:
            if (x[i] is not None and x[i - 1] is not None and x[i + 1] is not None
                    and x[i] <= x[i - 1] and x[i + 1] > x[i] and x[i] <= P["FLOOR"]):
                px.append(c[i + 1])
        i += 1
    return len(px), (sum(px) / len(px) if px else None)


def cycles(r60, r240, r5=None):
    K, D, C = r60["k20"], r60["d20"], r60["c"]
    N = len(K)
    out = []
    i = 1
    while i < N:
        # 사이클 시작 = 20 아래로 내려오는 봉
        if not (K[i] is not None and K[i] <= 20 and K[i - 1] is not None and K[i - 1] > 20):
            i += 1
            continue
        s = i
        j = i + 1
        while j < N and not (K[j] is not None and K[j] > 20 and
                             K[j - 1] is not None and K[j - 1] <= 20):
            j += 1
        if j >= N:
            break
        e = j                                   # 진입 = 20 위로 복귀
        lim = e + 1
        while lim < N and not (K[lim] is not None and K[lim] <= 20 and
                               K[lim - 1] is not None and K[lim - 1] > 20):
            lim += 1
        lim = min(lim, N - 1)

        def find(cond, frm=None):
            for x in range(e if frm is None else frm, lim + 1):
                if cond(x):
                    return x
            return None

        def dead_at(x):
            return (K[x] is not None and D[x] is not None and
                    K[x - 1] is not None and D[x - 1] is not None and
                    K[x] < D[x] and K[x - 1] >= D[x - 1] and K[x - 1] >= 80)

        i80 = find(lambda x: K[x] is not None and K[x] >= 80)
        dead = find(dead_at, i80) if i80 is not None else None
        iout = find(lambda x: K[x] is not None and K[x] < 80, i80) if i80 is not None else None
        ibend = find(lambda x: x >= 3 and K[x] is not None and K[x - 3] is not None
                     and K[x] < K[x - 3] and K[x - 3] >= 80, i80) if i80 is not None else None

        # 사이클을 넘겨서라도 데드크로스까지 기다리는 경우
        held = None
        for x in range((e if i80 is None else i80), N):
            if dead_at(x):
                held = x
                break

        low = min(C[s:e + 1]) if e >= s else C[e]
        # 「사이클 최고가」는 데드크로스까지의 최고다 — 데드크로스 규칙의 상한선을 재는 것이므로
        # 사이클 끝까지의 최고(+21.5%)를 쓰면 도달 불가능한 값과 비교하게 된다.
        peak = max(C[e:(dead if dead is not None else lim) + 1])
        sp_n, sp_avg = split_avg(r5, r60["t"][s], r60["t"][e])
        out.append(dict(s=s, e=e, i80=i80, dead=dead, iout=iout, ibend=ibend,
                        lim=lim, held=held, ep=C[e], low=low, peak=peak,
                        g=g240_at(r240, r60["t"][e]), sp_n=sp_n, sp_avg=sp_avg))
        i = max(e + 1, lim)
    return out


# ─────────────────────────── 집계 ───────────────────────────
def pct(a, b):
    return (b / a - 1.0) * 100.0


class Acc:
    def __init__(self):
        self.v = []

    def add(self, x):
        self.v.append(x)

    def row(self, name):
        if not self.v:
            return f"{name:<28} {'-':>7}"
        n = len(self.v)
        win = sum(1 for x in self.v if x > 0) / n * 100
        avg = sum(self.v) / n
        return (f"{name:<28} {n:>6}건  승률 {win:>5.0f}%  "
                f"평균 {avg:>+7.2f}%  최악 {min(self.v):>+8.2f}%")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exclude-inverse", action="store_true")
    ap.add_argument("--exclude-leverage", action="store_true")
    ap.add_argument("--only", default=None)
    ap.add_argument("--sell", default="dead", choices=["dead", "rule"], help="매수→매도 표의 매도 신호")
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(RAW, "*.json.gz")))
    skip = set()
    if args.exclude_inverse:
        skip |= INVERSE
    if args.exclude_leverage:
        skip |= LEVERAGE

    R = {k: Acc() for k in ("held", "cut", "dead", "out80", "bend", "hit80", "peak")}
    G = {"lo": Acc(), "mid": Acc(), "hi": Acc(), "na": Acc()}
    per = {}
    n_cyc = n_miss = 0
    dd = Acc()
    SP = {k: Acc() for k in ("hit80", "combo", "hold", "missCut")}   # 5분 분할매수 평균가 기준
    sp_n = 0; sp_cnt = []
    used = []
    PT = {tf: [[], 0] for tf in TFS_ALL}     # 3형제 매수 규칙 — [짝 목록, 진행중 수]
    PR = [{tf: [[], 0] for tf in TFS_ALL} for _ in BUY_RULES]   # 규칙 하나씩

    for f in files:
        code = os.path.basename(f)[:-8]
        if code in skip:
            continue
        if args.only and code != args.only:
            continue
        raw = json.load(gzip.open(f, "rt", encoding="utf-8"))
        if "60m" not in raw or len(raw["60m"]["c"]) < 200:
            continue
        r60 = series(raw["60m"])
        r240 = series(chunk_day(raw["60m"], 4))
        r5 = series(raw["5m"]) if "5m" in raw and len(raw["5m"]["c"]) > 80 else None
        cy = cycles(r60, r240, r5)
        if not cy:
            continue
        used.append(code)
        # 매수 신호 → 매도 신호 (페이지 검증 탭 맨 위 표와 같은 계산)
        allt = {tf: raw[tf] for tf in ("1m", "5m", "30m", "60m") if tf in raw and len(raw[tf]["c"]) > 80}
        if "1m" in allt:
            allt["3m"] = clock_chunk(allt["1m"], 3)
        if "5m" in allt:
            allt["10m"] = chunk_day(allt["5m"], 2)
        if "60m" in allt:
            allt["120m"] = chunk_day(allt["60m"], 2)
            allt["240m"] = chunk_day(allt["60m"], 4)
        for tf in TFS_ALL:
            if tf not in allt or len(allt[tf]["c"]) <= 80:
                continue
            rr = series(allt[tf])
            sells = sell_sig(rr, args.sell)
            pr, _d, op = pair_up(rr, buy_sig(rr), sells)
            PT[tf][0].extend(pr); PT[tf][1] += (1 if op is not None else 0)
            for k, (_no, fn) in enumerate(BUY_RULES):
                pr, _d, op = pair_up(rr, fn(rr), sells)
                PR[k][tf][0].extend(pr); PR[k][tf][1] += (1 if op is not None else 0)
        C = r60["c"]
        pa = Acc()
        for c in cy:
            n_cyc += 1
            if c["i80"] is None:
                n_miss += 1
            dd.add(pct(c["ep"], c["low"]))

            # 무산 포함 두 관행
            if c["held"] is not None:
                x = pct(c["ep"], C[c["held"]])
                R["held"].add(x)
                pa.add(x)
            cut = c["dead"] if c["dead"] is not None else c["lim"]
            xc = pct(c["ep"], C[cut])
            R["cut"].add(xc)

            # 5분 분할매수 평균가 기준 (몫이 있는 사이클만)
            if c["sp_n"] and c["sp_avg"]:
                ap = c["sp_avg"]; sp_n += 1; sp_cnt.append(c["sp_n"])
                if c["i80"] is not None: SP["hit80"].add(pct(ap, C[c["i80"]]))
                SP["combo"].add(pct(ap, C[c["i80"] if c["i80"] is not None else c["lim"]]))
                if c["held"] is not None: SP["hold"].add(pct(ap, C[c["held"]]))
                if c["i80"] is None: SP["missCut"].add(pct(ap, C[c["lim"]]))
            # 240분 수준별 (손절 방식)
            g = c["g"]
            key = "na" if g is None else ("lo" if g < 30 else ("hi" if g > 70 else "mid"))
            G[key].add(xc)

            # 청산 규칙 비교 — 80에 닿은 사이클만
            if c["i80"] is not None:
                R["hit80"].add(pct(c["ep"], C[c["i80"]]))
                if c["iout"] is not None:
                    R["out80"].add(pct(c["ep"], C[c["iout"]]))
                if c["ibend"] is not None:
                    R["bend"].add(pct(c["ep"], C[c["ibend"]]))
                if c["dead"] is not None:
                    R["dead"].add(pct(c["ep"], C[c["dead"]]))
                    R["peak"].add(pct(c["ep"], c["peak"]))
        per[code] = pa

    sell_nm = "매도 규칙 ①+②+③" if args.sell == "rule" else "큰형 80 위 데드크로스"
    print(f"■ 매수 신호 → 매도 신호 · 매수 규칙 전부(①+②+③) (FLOOR {BUYP['FLOOR']} RISE {BUYP['RISE']} WIN {BUYP['WIN1']}/{BUYP['WIN2']}) · 매도 = {sell_nm}")
    tot, topn = [], 0
    for tf in TFS_ALL:
        print(pair_row(tf, PT[tf][0], PT[tf][1])); tot += PT[tf][0]; topn += PT[tf][1]
    print(pair_row("합계", tot, topn))
    for k, (no, _fn) in enumerate(BUY_RULES):
        print(f"■ 규칙 {no}만")
        tot, topn = [], 0
        for tf in TFS_ALL:
            print(pair_row(tf, PR[k][tf][0], PR[k][tf][1])); tot += PR[k][tf][0]; topn += PR[k][tf][1]
        print(pair_row("합계", tot, topn))
    print()
    print(f"종목 {len(used)}개 · 사이클 {n_cyc}개 · 그중 80 미도달(무산) "
          f"{n_miss}개 ({n_miss/max(n_cyc,1)*100:.0f}%)")
    if skip:
        print(f"제외: {sorted(skip)}")
    print()
    print("■ 전체 사이클 (무산 포함)")
    print(" ", R["held"].row("끝까지 보유(데드크로스)"))
    print(" ", R["cut"].row("다음 20↓ 손절"))
    print()
    print("■ 청산 규칙 비교 (80 도달 사이클만 — 승률은 의미 없음, 평균만 본다)")
    for k, nm in (("peak", "사이클 최고가(상한)"), ("dead", "데드크로스"),
                  ("out80", "80 이탈"), ("bend", "3봉 꺾임"), ("hit80", "80 도달 즉시")):
        print(" ", R[k].row(nm))
    print()
    print("■ 240분 큰형 수준별 (손절 방식)")
    for k, nm in (("lo", "30 미만"), ("mid", "30~70"), ("hi", "70 초과"), ("na", "값 없음")):
        print(" ", G[k].row(nm))
    print()
    print(f"■ 5분 분할매수 평균가 기준 (5분 자료 있는 사이클 {sp_n}개 · 사이클당 평균 {sum(sp_cnt)/len(sp_cnt) if sp_cnt else 0:.1f}몫)")
    for k, nm in (("hit80", "80 도달 즉시"), ("missCut", "무산→손절"), ("combo", "합쳐서(도달 즉시+손절)"), ("hold", "끝까지 보유")):
        print(" ", SP[k].row(nm))
    print()
    print("■ 진입 전 최저 (20↓ 시작 → 진입까지)")
    print(" ", dd.row("구간최저"))
    print()
    print("■ 종목별 (끝까지 보유 기준)")
    for code, a in sorted(per.items(), key=lambda x: -(sum(x[1].v) / len(x[1].v) if x[1].v else 0)):
        print(" ", a.row(code))


if __name__ == "__main__":
    main()
