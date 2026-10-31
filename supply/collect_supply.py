# -*- coding: utf-8 -*-
"""
시장 수급 체크 앱 — 데이터 수집기 v1 (2026-10-31)
공개 원천(네이버)으로 먼저 채우고, 키움 REST 키가 있으면 같은 항목을 키움 값으로 덮어쓴다(항목별 src 표기).
투자자 3주체 일별 이력·지수 종가는 수급흐름 앱(money/data.json)에 이미 있으므로 화면이 그 파일을 같이 읽는다.

공개 원천 (2026-10-31 supply-probe 로 Actions 에서 확인)
  1) 코스피·코스닥 오늘 투자자·프로그램 : m.stock.naver.com/api/index/{KOSPI|KOSDAQ}/integration
       dealTrendInfo(개인·외국인·기관, 억원) / programTrendInfo(차익·비차익·합계, 억원) — 이력 없음 → programHist 에 매일 누적,
       장중 실행 때마다 intraday 에 시각별로 쌓는다.
  2) 코스피200 선물 투자자 : m.stock.naver.com/api/index/FUT/trend?bizdate=YYYYMMDD (날짜별 이력, 네이버 표기 원값)
  3) 순위 후보 : stock.naver.com/api/domestic/market/stock/default orderType=foreignPureBuy|organizationPureBuy|marketSum
  4) 종목별 투자자 순매매(수량·종가, 날짜별) : stock.naver.com/api/stockSecurity/investor-trend/v2/domestic/{code}/paged
       → 금액(억원) = 순매매 수량 × 종가 / 1e8 (추정 금액), 연속 순매수 일수 계산
  5) 업종 : money/data.json 의 sectorStocks(업종 → 종목명) 로 종목을 업종에 묶는다(상위 종목 기준 합계).

키움 REST (환경변수 KIWOOM_APPKEY / KIWOOM_SECRETKEY, 선택 KIWOOM_HOST)
  - GitHub Actions 에서는 Secrets 로, PC 에서는 같은 이름의 환경변수로 넣는다. 키·토큰 값은 출력하지 않는다.
  - 키움이 호출 IP 를 등록제로 막으면 Actions(유동 IP) 에서는 실패한다 → PC 에서 `--kiwoom-only` 로 돌려
    supply/kiwoom.json 만 push 하면 Actions 수집기가 그 파일을 합친다.
부분 실패해도 가능한 데이터만으로 저장한다.
"""
import json, os, sys, time, datetime, traceback
import requests

KST = datetime.timezone(datetime.timedelta(hours=9))
NOW = datetime.datetime.now(KST)
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data.json")
KW_OUT = os.path.join(HERE, "kiwoom.json")
MONEY = os.path.join(HERE, "..", "money", "data.json")
DAYS = 60
SLEEP = 0.25
ERRORS = []
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
     "Accept": "*/*", "Referer": "https://m.stock.naver.com/"}
NV = "https://m.stock.naver.com/api"
SN = "https://stock.naver.com/api"


def log(m): print(f"[supply] {m}", flush=True)


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


def load(path):
    try:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f) or {}
    except Exception as e:
        ERRORS.append(f"load {os.path.basename(path)}: {e}")
    return {}


def ymd(d): return d.replace("-", "")


def dash(d): return f"{d[:4]}-{d[4:6]}-{d[6:]}" if len(d) == 8 else d


# ───────────────────────── 공개 원천 (네이버) ─────────────────────────

def nv_integration(code):
    """오늘(가장 최근 영업일) 투자자 3주체·프로그램 — (날짜, {ind,frg,inst}, {arb,nonarb,total})."""
    j = get(f"{NV}/index/{code}/integration").json()
    d, p = j.get("dealTrendInfo") or {}, j.get("programTrendInfo") or {}
    deal = {"ind": num(d.get("personalValue")), "frg": num(d.get("foreignValue")),
            "inst": num(d.get("institutionalValue"))}
    prog = {"arb": num(p.get("indexDifferenceReal")), "nonarb": num(p.get("indexBiDifferenceReal")),
            "total": num(p.get("indexTotalReal"))} if p else None
    return dash(d.get("bizdate") or p.get("bizdate") or ""), deal, prog


def nv_futures_day(d):
    """그날 코스피200 선물 개인·외국인·기관 순매수(네이버 표기 원값)."""
    j = get(f"{NV}/index/FUT/trend?bizdate={ymd(d)}").json()
    if j.get("bizdate") != ymd(d): return None
    v = (num(j.get("personalValue")), num(j.get("foreignValue")), num(j.get("institutionalValue")))
    return None if v[1] is None else list(v)


def nv_rank_codes(order, n):
    rows = get(f"{SN}/domestic/market/stock/default?tradeType=KRX&marketType=ALL"
               f"&orderType={order}&startIdx=0&pageSize={n}").json()
    return [(s["itemcode"], s["itemname"], str(s.get("sosok"))) for s in rows if s.get("itemcode")]


def nv_stock_flow(code, size=20):
    """종목 일별 외국인·기관·개인 순매매 → [{date, frg, org, ind}] (억원 추정 = 수량 × 종가), 최신 날짜가 앞."""
    j = get(f"{SN}/stockSecurity/investor-trend/v2/domestic/{code}/paged?exchangeType=krx&size={size}").json()
    out = []
    for it in j.get("items") or []:
        k = it.get("krx") or {}
        px = num(k.get("closingPrice"))
        if not px: continue
        f = lambda key: round(num(k.get(key)) * px / 1e8, 1) if num(k.get(key)) is not None else None
        out.append({"date": it.get("localTradedAt"), "frg": f("foreignNetVolume"),
                    "org": f("organizationNetVolume"), "ind": f("individualNetVolume")})
    return out


def streak(vals):
    """최신부터 같은 방향(+)이 이어진 일수."""
    n = 0
    for v in vals:
        if v is not None and v > 0: n += 1
        else: break
    return n


def public_rank(sec_of):
    """순위·연속매수·업종 집계 (상위 종목 기준)."""
    cand = {}
    for order, n in [("foreignPureBuy", 40), ("organizationPureBuy", 40), ("marketSum", 100)]:
        try:
            for code, name, sosok in nv_rank_codes(order, n):
                cand.setdefault(code, (name, sosok))
        except Exception as e:
            ERRORS.append(f"rank list {order}: {e}")
    flows, fail = {}, 0
    for code, (name, sosok) in cand.items():
        try:
            fl = nv_stock_flow(code)
        except Exception as e:
            fail += 1
            if fail <= 3: ERRORS.append(f"stock flow {name}: {e}")
            continue
        if fl: flows[code] = (name, sosok, fl)
    if not flows:
        ERRORS.append("rank: 종목별 순매매를 받지 못함"); return None, None
    last = max(fl[0]["date"] or "" for _, _, fl in flows.values())
    rows = []
    for code, (name, sosok, fl) in flows.items():
        if fl[0]["date"] != last: continue
        t = fl[0]
        rows.append({"code": code, "name": name, "mk": "kospi" if sosok == "0" else "kosdaq",
                     "sector": sec_of.get(name, ""), "frg": t["frg"], "inst": t["org"],
                     "frg5": round(sum(x["frg"] or 0 for x in fl[:5]), 1),
                     "inst5": round(sum(x["org"] or 0 for x in fl[:5]), 1),
                     "frgDays": streak([x["frg"] for x in fl]), "instDays": streak([x["org"] for x in fl])})
    log(f"종목별 순매매 {len(rows)}종목 ({last}, 후보 {len(cand)}, 실패 {fail})")

    def top(key, rev, cond):
        return [dict(r, amt=r[key]) for r in sorted((r for r in rows if cond(r)), key=lambda r: r[key], reverse=rev)][:20]
    rank = {
        "date": last,
        "frgBuy": top("frg", True, lambda r: (r["frg"] or 0) > 0),
        "frgSell": top("frg", False, lambda r: (r["frg"] or 0) < 0),
        "instBuy": top("inst", True, lambda r: (r["inst"] or 0) > 0),
        "instSell": top("inst", False, lambda r: (r["inst"] or 0) < 0),
        "both": sorted((r for r in rows if (r["frg"] or 0) > 0 and (r["inst"] or 0) > 0),
                       key=lambda r: -(r["frg"] + r["inst"]))[:20],
        "streak": [dict(r, amt=round(r["frg5"] + r["inst5"], 1)) for r in
                   sorted((r for r in rows if max(r["frgDays"], r["instDays"]) >= 3),
                          key=lambda r: (-max(r["frgDays"], r["instDays"]), -(r["frg5"] + r["inst5"])))][:20],
    }
    sec = {"kospi": {}, "kosdaq": {}}
    for r in rows:
        if not r["sector"]: continue
        s = sec[r["mk"]].setdefault(r["sector"], {"name": r["sector"], "frg": 0.0, "inst": 0.0, "n": 0})
        s["frg"] += r["frg"] or 0; s["inst"] += r["inst"] or 0; s["n"] += 1
    sector = {k: [dict(v, frg=round(v["frg"], 1), inst=round(v["inst"], 1)) for v in d.values()] for k, d in sec.items()}
    return rank, sector


# ───────────────────────── 키움 REST ─────────────────────────

class Kiwoom:
    """키움 REST 최소 클라이언트. 조회(시세·수급)만 쓴다 — 주문·계좌 API 는 부르지 않는다."""

    def __init__(self, appkey, secretkey, host=None):
        self.host = (host or "https://api.kiwoom.com").rstrip("/")
        self.appkey, self.secretkey, self.tok = appkey, secretkey, None

    def token(self):
        r = requests.post(f"{self.host}/oauth2/token", timeout=15,
                          headers={"Content-Type": "application/json;charset=UTF-8"},
                          json={"grant_type": "client_credentials", "appkey": self.appkey, "secretkey": self.secretkey})
        j = r.json()
        if not j.get("token"):
            raise RuntimeError(f"토큰 발급 실패: [{j.get('return_code')}] {j.get('return_msg')}")
        self.tok = j["token"]
        return True

    def call(self, api_id, path, body, list_key=None, pages=1):
        """api-id 호출. list_key 가 있으면 연속조회(cont-yn/next-key)로 pages 쪽까지 이어 붙인다."""
        out, cont, nkey = [], "N", ""
        for _ in range(max(1, pages)):
            hd = {"Content-Type": "application/json;charset=UTF-8", "authorization": f"Bearer {self.tok}",
                  "api-id": api_id, "cont-yn": cont, "next-key": nkey}
            r = requests.post(f"{self.host}{path}", headers=hd, json=body, timeout=15)
            j = r.json()
            if j.get("return_code") not in (0, "0", None):
                raise RuntimeError(f"{api_id} [{j.get('return_code')}] {j.get('return_msg')}")
            time.sleep(0.3)
            if not list_key: return j
            out += j.get(list_key) or []
            cont, nkey = r.headers.get("cont-yn", "N"), r.headers.get("next-key", "")
            if cont != "Y": break
        return out


def kiwoom_collect():
    """키움에서 받을 수 있는 항목을 모아 dict 로 돌려준다. 키가 없으면 None.
    TR 명세(api-id·body·응답 키)는 KIWOOM_TR 에 모아 두고, 명세 확인 전 항목은 비워 둔다."""
    ak, sk = os.environ.get("KIWOOM_APPKEY", ""), os.environ.get("KIWOOM_SECRETKEY", "")
    if not (ak and sk):
        log("키움 키 없음 — 공개 원천만 사용")
        return None
    kw = Kiwoom(ak, sk, os.environ.get("KIWOOM_HOST"))
    res = {"updated": NOW.strftime("%Y-%m-%d %H:%M KST"), "ok": False, "errors": []}
    try:
        kw.token()
        res["ok"] = True
        log("키움 토큰 발급 성공")
    except Exception as e:
        res["errors"].append(str(e))
        log(f"키움 토큰 실패: {e}")
        return res
    for name, fn in KIWOOM_TR.items():
        try:
            v = fn(kw)
            if v: res[name] = v; log(f"키움 {name} 수신")
        except Exception as e:
            res["errors"].append(f"{name}: {e}")
            log(f"키움 {name} 실패: {e}")
    return res


# 항목 이름 → 함수(kw) — 키움 명세 확인 후 채운다. 반환 형식은 data.json 의 같은 항목과 맞춘다.
KIWOOM_TR = {}


# ───────────────────────── 조립 ─────────────────────────

def main():
    kiwoom_only = "--kiwoom-only" in sys.argv
    if kiwoom_only:
        res = kiwoom_collect()
        if res is None: raise SystemExit("KIWOOM_APPKEY / KIWOOM_SECRETKEY 환경변수가 없다")
        with open(KW_OUT, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, separators=(",", ":"))
        log(f"kiwoom.json 저장 (ok={res['ok']}, 오류 {len(res['errors'])})")
        return

    prev = load(OUT)
    money = load(MONEY)
    out = {"updated": NOW.strftime("%Y-%m-%d %H:%M KST"), "version": 1, "errors": ERRORS, "src": {}}
    dates = (money.get("dates") or [])[-DAYS:]

    # 1) 오늘 투자자·프로그램 + 장중 누적
    phist = prev.get("programHist") or {}
    intra = prev.get("intraday") or {}
    today, snap = None, {}
    for key, code in [("kospi", "KOSPI"), ("kosdaq", "KOSDAQ")]:
        try:
            d, deal, prog = nv_integration(code)
            today = today or d
            snap[key] = (deal, prog)
            if prog and d:
                phist.setdefault(d, {})[key] = [prog["arb"], prog["nonarb"], prog["total"]]
        except Exception as e:
            ERRORS.append(f"integration {code}: {e}")
    hd = sorted(phist)[-DAYS:]
    phist = {d: phist[d] for d in hd}
    out["programHist"] = phist
    out["program"] = {"dates": hd, **{k: {
        "arb": [(phist[d].get(k) or [None] * 3)[0] for d in hd],
        "nonarb": [(phist[d].get(k) or [None] * 3)[1] for d in hd],
        "total": [(phist[d].get(k) or [None] * 3)[2] for d in hd]} for k in ("kospi", "kosdaq")}}
    out["src"]["program"] = "naver"
    log(f"프로그램 이력 {len(hd)}일 누적")

    hhmm = NOW.strftime("%H:%M")
    if today and "09:00" <= hhmm <= "15:45" and today == NOW.strftime("%Y-%m-%d"):
        if intra.get("date") != today:
            intra = {"date": today, "times": [], "kospi": {}, "kosdaq": {}}
        intra["times"].append(hhmm)
        for key, (deal, prog) in snap.items():
            m = intra.setdefault(key, {})
            for k in ("ind", "frg", "inst"):
                m.setdefault(k, []).append(deal.get(k))
            m.setdefault("prog", []).append(prog["total"] if prog else None)
        n = len(intra["times"])
        for key in ("kospi", "kosdaq"):
            for k, arr in intra.get(key, {}).items():
                intra[key][k] = ([None] * (n - len(arr)) + arr)[-n:]
        out["src"]["intraday"] = "naver"
    out["intraday"] = intra

    # 2) 선물 투자자 — 날짜별, 이미 받은 날은 다시 쓰고 최근 2일만 새로
    pf = prev.get("futures") or {}
    cache = {d: [a, b, c] for d, a, b, c in zip(pf.get("dates") or [], pf.get("ind") or [],
                                                 pf.get("frg") or [], pf.get("inst") or []) if b is not None}
    fut, fail = {}, 0
    for d in dates:
        if d in cache and d not in dates[-2:]:
            fut[d] = cache[d]; continue
        try:
            v = nv_futures_day(d)
        except Exception as e:
            v = None; fail += 1
            if fail <= 3: ERRORS.append(f"futures {d}: {e}")
        if v is None: v = cache.get(d)
        if v is not None: fut[d] = v
    fd = [d for d in dates if d in fut]
    out["futures"] = {"dates": fd, "ind": [fut[d][0] for d in fd], "frg": [fut[d][1] for d in fd],
                      "inst": [fut[d][2] for d in fd], "unit": ""}
    out["src"]["futures"] = "naver"
    log(f"선물 투자자 {len(fd)}/{len(dates)}일 (실패 {fail})")

    # 3) 종목 순위·연속매수·업종
    sec_of = {}
    for sname, stocks in (money.get("sectorStocks") or {}).items():
        for s in stocks:
            sec_of.setdefault(s[0], sname)
    try:
        rank, sector = public_rank(sec_of)
        if rank:
            out["rank"] = rank; out["src"]["rank"] = "naver"
            out["sectorInv"] = sector; out["src"]["sectorInv"] = "naver"
    except Exception as e:
        ERRORS.append(f"rank: {e}"); traceback.print_exc()

    # 4) 키움 — Actions 에서 직접 받거나, PC 가 올린 kiwoom.json 을 합친다
    kw = None
    try:
        kw = kiwoom_collect()
    except Exception as e:
        ERRORS.append(f"kiwoom: {e}")
    if not (kw and kw.get("ok")):
        pc = load(KW_OUT)
        if pc.get("ok") and str(pc.get("updated", ""))[:10] == NOW.strftime("%Y-%m-%d"):
            kw = pc; log("PC 가 올린 kiwoom.json 사용")
    out["kiwoom"] = {"ok": bool(kw and kw.get("ok")), "updated": (kw or {}).get("updated"),
                     "errors": (kw or {}).get("errors", [])[:5]}
    if kw and kw.get("ok"):
        for name in ("investor", "program", "intraday", "sectorInv", "rank", "aux"):
            if kw.get(name):
                out[name] = kw[name]; out["src"][name] = "kiwoom"
        if kw.get("investor"):
            out["dates"] = kw.get("dates") or dates

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    log(f"저장 완료 (원천 {out['src']}, 오류 {len(ERRORS)})")
    for e in ERRORS: log("ERR " + str(e))


if __name__ == "__main__":
    main()
