# -*- coding: utf-8 -*-
"""
매수 후보 확률 대장 — 2026-09-26 대표 「확률적으로 기록해 두면 좋을 것 같다 … 계획서를 작성해서 적용하라」.
계획 = 시암업부체계화 마스터플랜\\_주식실시간\\_계획_260926_확률대장.md

  후보 자리  = 60분 큰형 %K 가 4.0 이하에서 골(앞뒤 6봉 최저)을 만들고 다음 봉에서 오른 것이 확인된 60분 봉,
               앞 40봉 안에 큰형 6.0 이상이 있었던 눌림. 매수가 = 그 봉 종가.
  꼬리표     = T1~T8 (원칙이 늘면 칸을 «더한다», 정의를 고치지 않는다 — 축적대장 운영 규칙 ⑥)
  결과       = 70봉(약 10거래일) 안 종가 +10% 도달(적중) · 35봉 뒤 수익 · 70봉 안 최대 하락
  산출물     = stoch/prob/prob_table.json · stoch/prob/signals.jsonl(전진 기록) · stoch/prob/_변경로그.md

계산식(스토캐스틱·상위봉 묶기)은 verify_setting.py 한 벌을 쓴다. 페이지 timing/index.html 의 probTags 가 같은 정의다.
"""
import os, sys, json, gzip, glob, bisect, datetime, itertools

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import verify_setting as V

RAW = os.path.join(HERE, "min", "raw")
OUTD = os.path.join(HERE, "prob")
KST = datetime.timezone(datetime.timedelta(hours=9))
H_HIT, H_RET, HIT_PCT, MIN_N = 70, 35, 10.0, 30
# 조합을 좁힐 때 쓰는 꼬리표 순서 — 원칙 꼬리표 먼저 (P1 · P12 · P6 …), 관찰 꼬리표는 뒤
PRIO = ["T2", "T7", "T5", "T6", "T3", "T1", "T8", "T4"]
TAG_NAME = {
    "T1": "60분 골 깊이", "T2": "바닥 구간 60분 3형제 동시 2.0↓ (P1)", "T3": "240분 큰형 기울기 (P6)",
    "T4": "240분 큰형 7.0 초과", "T5": "5분 3형제 동시 2.0↓ 돌아서기 전 하루 (P12)",
    "T6": "5분 3형제 바닥 반복 (P12)", "T7": "계단 점수 5분막내→60분큰형 (P12)", "T8": "가격 눌림 폭 (관찰)",
}
LAD = [("5m", "k5"), ("5m", "k10"), ("5m", "k20"), ("30m", "k5"), ("30m", "k10"), ("60m", "k10"), ("60m", "k20")]


def last_trough(r, key, t0, t1, cap):
    t, k = r["t"], r[key]
    j0 = bisect.bisect_left(t, t0); j1 = bisect.bisect_right(t, t1) - 1
    best = None
    for x in range(max(1, j0), min(j1, len(k) - 2) + 1):
        if k[x] is None or k[x - 1] is None or k[x + 1] is None:
            continue
        if k[x] <= k[x - 1] and k[x] < k[x + 1] and k[x] <= cap:
            best = t[x]
    return best


def low5(x, r5):
    return all(r5[k][x] is not None and r5[k][x] <= 20 for k in ("k5", "k10", "k20"))


def events(R):
    """R = {'60m','240m','30m'?,'5m'?} series. 후보 자리마다 꼬리표·결과."""
    r = R["60m"]; g, C, T = r["k20"], r["c"], r["t"]; N = len(C)
    r240, r5, r30 = R["240m"], R.get("5m"), R.get("30m")
    out = []
    for i in range(12, N - 1):
        if g[i] is None or g[i + 1] is None:
            continue
        w = [x for x in g[max(0, i - 6):i + 7] if x is not None]
        if g[i] != min(w) or g[i + 1] <= g[i] or g[i] > 40:
            continue
        pk = [x for x in range(max(0, i - 40), i) if g[x] is not None and g[x] >= 60]
        if not pk:
            continue
        e = i + 1
        tag = {}
        tag["T1"] = "2.0↓" if g[i] <= 20 else ("2.0~3.0" if g[i] <= 30 else "3.0~4.0")
        tag["T2"] = "있음" if any(V.state_at(r, x) == 2 for x in range(pk[-1], e + 1)) else "없음"
        j = bisect.bisect_right(r240["t"], T[e]) - 1
        if j >= 1 and r240["k20"][j] is not None and r240["k20"][j - 1] is not None:
            tag["T3"] = "상승" if r240["k20"][j] > r240["k20"][j - 1] else "하락"
            tag["T4"] = "예" if r240["k20"][j] > 70 else "아니오"
        else:
            tag["T3"] = tag["T4"] = "자료 없음"
        # 5분·30분 칸 — 눌림 시작부터 자료가 있어야 값이 있다
        t0, t1 = T[pk[-1]], T[e] + 3599
        if r5 and r5["t"] and r5["t"][0] <= t0 and r5["t"][-1] >= T[e]:
            j1 = bisect.bisect_right(r5["t"], t1) - 1
            j0d = max(1, j1 - 78)
            tag["T5"] = "있음" if any(low5(x, r5) for x in range(j0d, j1 + 1)) else "없음"
            j0 = bisect.bisect_left(r5["t"], t0)
            n3, on = 0, False
            for x in range(j0, j1 + 1):
                c = low5(x, r5)
                if c and not on:
                    n3 += 1
                on = c
            tag["T6"] = "2번 이상" if n3 >= 2 else "0~1번"
            if r30 and r30["t"] and r30["t"][0] <= t0:
                RR = {"5m": r5, "30m": r30, "60m": r}
                tr = [last_trough(RR[tf], key, t0, t1, 40 if tf == "60m" else 30) if not (tf == "60m" and key == "k20") else T[i]
                      for tf, key in LAD]
                pairs = [(tr[a], tr[a + 1]) for a in range(len(tr) - 1) if tr[a] and tr[a + 1]]
                sc = sum(1 for p, q in pairs if q >= p) / len(pairs) if pairs else 0
                tag["T7"] = "0.66 이상" if (all(tr) and sc >= 0.66) else "미만"
            else:
                tag["T7"] = "자료 없음"
        else:
            tag["T5"] = tag["T6"] = tag["T7"] = "자료 없음"
        pkx = max(range(max(0, i - 40), i + 1), key=lambda x: C[x])
        drop = (C[i] / C[pkx] - 1) * 100
        tag["T8"] = "−3% 이내" if drop > -3 else ("−3~−7%" if drop > -7 else "−7% 넘게")
        res = None
        if e + H_HIT < N:
            res = dict(hit=max(C[e + 1:e + H_HIT + 1]) / C[e] - 1 >= HIT_PCT / 100,
                       r35=(C[e + H_RET] / C[e] - 1) * 100,
                       dd=(min(C[e + 1:e + H_HIT + 1]) / C[e] - 1) * 100)
        out.append(dict(t=T[e], px=C[e], g=g[i], tag=tag, res=res))
    return out


def load(code):
    raw = json.load(gzip.open(os.path.join(RAW, code + ".json.gz"), "rt", encoding="utf-8"))
    if "60m" not in raw or len(raw["60m"]["c"]) < 300:
        return None
    R = {"60m": V.series(raw["60m"]), "240m": V.series(V.chunk_day(raw["60m"], 4))}
    for tf in ("5m", "30m"):
        if tf in raw and len(raw[tf]["c"]) > 80:
            R[tf] = V.series(raw[tf])
    return R


def key_of(tag, cols):
    return "|".join(f"{c}={tag[c]}" for c in sorted(cols))


def lookup(table, tag):
    """원칙 꼬리표 순서대로 값이 있는 칸 3개 → 2개 → 1개로 좁혀, 건수 MIN_N 이상인 가장 좁은 조합."""
    cols = [c for c in PRIO if tag.get(c) not in (None, "자료 없음")]
    for n in (3, 2, 1):
        if len(cols) < n:
            continue
        k = key_of(tag, cols[:n])
        s = table.get(k)
        if s and s["n"] >= MIN_N:
            return k, s
    return None, None


def main():
    os.makedirs(OUTD, exist_ok=True)
    codes = sorted(os.path.basename(f)[:-8] for f in glob.glob(os.path.join(RAW, "*.json.gz")))
    allev = {}
    for c in codes:
        R = load(c)
        if R:
            allev[c] = events(R)
    # 확률 대장 — 꼬리표 1~3칸 조합마다 (결과가 확정된 자리만)
    table = {}
    base = [0, 0, 0.0, 0.0]
    for c, L in allev.items():
        for ev in L:
            if not ev["res"]:
                continue
            rs = ev["res"]
            base[0] += 1; base[1] += rs["hit"]; base[2] += rs["r35"]; base[3] += rs["dd"]
            cols = [k for k in ev["tag"] if ev["tag"][k] != "자료 없음"]
            for n in (1, 2, 3):
                for comb in itertools.combinations(sorted(cols), n):
                    k = key_of(ev["tag"], comb)
                    s = table.setdefault(k, {"n": 0, "hit": 0, "r35": 0.0, "dd": 0.0})
                    s["n"] += 1; s["hit"] += rs["hit"]; s["r35"] += rs["r35"]; s["dd"] += rs["dd"]
    for s in table.values():
        s["p"] = round(s["hit"] / s["n"] * 100, 1); s["r35"] = round(s["r35"] / s["n"], 2); s["dd"] = round(s["dd"] / s["n"], 2)
    built = datetime.datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    doc = {
        "built": built, "codes": len(allev), "min_n": MIN_N, "prio": PRIO, "tags": TAG_NAME,
        "result": f"{H_HIT}봉 안 +{HIT_PCT:.0f}% 도달 · {H_RET}봉 뒤 수익 · {H_HIT}봉 안 최대 하락",
        "base": {"n": base[0], "p": round(base[1] / max(base[0], 1) * 100, 1),
                 "r35": round(base[2] / max(base[0], 1), 2), "dd": round(base[3] / max(base[0], 1), 2)},
        "table": table,
    }
    with open(os.path.join(OUTD, "prob_table.json"), "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))

    # 전진 기록 — 이미 적힌 줄은 결과만 채우고, 새 후보는 덧붙인다. 지우지 않는다.
    sp = os.path.join(OUTD, "signals.jsonl")
    old = []
    if os.path.exists(sp):
        with open(sp, encoding="utf-8") as f:
            old = [json.loads(x) for x in f if x.strip()]
    have = {(o["code"], o["t"]) for o in old}
    evmap = {(c, ev["t"]): ev for c, L in allev.items() for ev in L}
    filled = added = 0
    for o in old:
        if o.get("res") is None:
            ev = evmap.get((o["code"], o["t"]))
            if ev and ev["res"]:
                o["res"] = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in ev["res"].items()}; filled += 1
    # 새 줄 = 결과가 아직 없는(최근) 후보 — 처음 실행 때 과거 전체를 «전진 기록»으로 올리지 않는다
    for c, L in allev.items():
        for ev in L:
            if ev["res"] is None and (c, ev["t"]) not in have:
                k, s = lookup(table, ev["tag"])
                old.append({"code": c, "t": ev["t"], "at": datetime.datetime.fromtimestamp(ev["t"], KST).strftime("%Y-%m-%d %H:%M"),
                            "px": ev["px"], "tag": ev["tag"], "combo": k, "p": s["p"] if s else None, "n": s["n"] if s else None,
                            "logged": built, "res": None})
                added += 1
    old.sort(key=lambda o: (o["t"], o["code"]))
    with open(sp, "w", encoding="utf-8") as f:
        for o in old:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")

    lp = os.path.join(OUTD, "_변경로그.md")
    head = "" if os.path.exists(lp) else "# 확률 대장 변경 로그 (prob_build.py 가 실행마다 덧붙인다 · 지우지 말 것)\n\n"
    with open(lp, "a", encoding="utf-8") as f:
        f.write(head + f"## {built} — 종목 {len(allev)} · 결과 확정 후보 {base[0]} · 기준선 적중 {doc['base']['p']}% · 조합 {len(table)}칸 · 전진 기록 새 줄 {added} · 결과 채움 {filled}\n\n")
    print(f"종목 {len(allev)} · 후보 {base[0]} · 기준선 {doc['base']['p']}% · 조합 {len(table)} · 전진 +{added} 채움 {filled}")


if __name__ == "__main__":
    main()
