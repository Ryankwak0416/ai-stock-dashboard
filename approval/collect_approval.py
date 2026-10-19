# -*- coding: utf-8 -*-
"""
지지율·코스피 대시보드 — 데이터 수집기
  1) 코스피 일별 종가 : m.stock.naver.com/api/index/KOSPI/price (money/collect_money.py 와 같은 원천)
                        실패하면 FinanceDataReader('KS11')
  2) 한국갤럽 대통령 직무 긍정률 : 갤럽은 공개 데이터 피드가 없어 구글 뉴스 RSS 의 기사 제목에서 읽는다.
                        제목에 '갤럽'이 들어간 기사 2건 이상이 같은 수치를 말할 때만 새 조사로 추가한다.
                        조사 마지막 날 = 발표일(보통 금요일) 직전 목요일.
기존 data.json 의 이력은 지우지 않고 덧붙인다. 부분 실패해도 가능한 것만으로 저장한다.
"""
import json, os, re, time, datetime, urllib.parse, email.utils
import xml.etree.ElementTree as ET
import requests

KST = datetime.timezone(datetime.timedelta(hours=9))
NOW = datetime.datetime.now(KST)
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data.json")
START = "2025-10-01"
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
     "Accept": "*/*", "Referer": "https://m.stock.naver.com/"}
ERRORS = []

def log(m): print(f"[approval] {m}", flush=True)

def get(url, headers=None, retries=2):
    last = None
    for _ in range(retries + 1):
        try:
            r = requests.get(url, headers=headers or H, timeout=20)
            if r.status_code == 200:
                time.sleep(0.25)
                return r
            last = f"HTTP {r.status_code}"
        except Exception as e:
            last = repr(e)
        time.sleep(1.0)
    raise RuntimeError(f"{last} {url}")

def num(s):
    try: return float(str(s).replace(",", "").strip())
    except Exception: return None

def kospi_naver():
    out = {}
    for p in range(1, 8):
        rows = get(f"https://m.stock.naver.com/api/index/KOSPI/price?pageSize=60&page={p}").json()
        if not rows: break
        for r in rows:
            v = num(r.get("closePrice")); d = str(r.get("localTradedAt", ""))[:10]
            if v and d: out[d] = round(v, 2)
        if min(out) <= START: break
    return out

def kospi_fdr():
    import FinanceDataReader as fdr
    df = fdr.DataReader("KS11", START)
    return {d.strftime("%Y-%m-%d"): round(float(c), 2) for d, c in df["Close"].items()}

def gallup_news():
    """구글 뉴스 RSS 제목에서 이번 주 갤럽 긍정률을 읽는다. 반환: (조사 마지막 날, 값, 기사주소, 일치 건수) 또는 None."""
    q = urllib.parse.quote("한국갤럽 대통령 지지율")
    xml = get(f"https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko").text
    root = ET.fromstring(xml)
    votes = {}
    for it in root.iter("item"):
        title = (it.findtext("title") or "")
        if "갤럽" not in title: continue
        try: pub = email.utils.parsedate_to_datetime(it.findtext("pubDate")).astimezone(KST)
        except Exception: continue
        if (NOW - pub).days > 7: continue
        m = re.search(r"(?:지지율|긍정(?:률|\s*평가)?)\D{0,8}?(\d{2})\s*%", title)
        if not m: continue
        v = int(m.group(1))
        if not 10 <= v <= 90: continue
        d = pub.date()
        end = d - datetime.timedelta(days=(d.weekday() - 3) % 7)   # 발표일 직전(또는 당일) 목요일
        key = (end.isoformat(), v)
        votes.setdefault(key, []).append(it.findtext("link") or "")
    if not votes: return None
    (end, v), links = max(votes.items(), key=lambda kv: (kv[0][0], len(kv[1])))
    if len(links) < 2: return None
    return end, v, links[0], len(links)

def main():
    data = {}
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as f: data = json.load(f)
    kospi = {d: v for d, v in data.get("kospi", [])}
    src = data.get("kospiSource", "")
    try:
        new = kospi_naver(); src = "네이버 증권 지수 일별 시세"
    except Exception as e:
        ERRORS.append(f"코스피(네이버) 실패: {e}"); log(ERRORS[-1])
        try:
            new = kospi_fdr(); src = "FinanceDataReader(KS11)"
        except Exception as e2:
            new = {}; ERRORS.append(f"코스피(FDR) 실패: {e2}"); log(ERRORS[-1])
    kospi.update({d: v for d, v in new.items() if d >= START})
    log(f"코스피 {len(kospi)}일, 최신 {max(kospi) if kospi else '-'}")

    gallup = data.get("gallup", [])
    try:
        got = gallup_news()
        if got:
            end, v, link, n = got
            if all(r["date"] != end for r in gallup):
                gallup.append({"date": end, "approve": v, "source": link,
                               "note": f"자동 수집: 뉴스 제목 {n}건 일치"})
                log(f"갤럽 추가 {end} {v}%")
            else:
                log(f"갤럽 {end} 이미 있음")
        else:
            log("갤럽 이번 주 값 없음(2건 이상 일치하는 제목 없음)")
    except Exception as e:
        ERRORS.append(f"갤럽 뉴스 수집 실패: {e}"); log(ERRORS[-1])
    gallup.sort(key=lambda r: r["date"])

    data.update({
        "updated": NOW.strftime("%Y-%m-%d %H:%M KST"),
        "kospiSource": src,
        "kospi": [[d, kospi[d]] for d in sorted(kospi)],
        "gallup": gallup,
        "errors": ERRORS,
    })
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

if __name__ == "__main__":
    main()
