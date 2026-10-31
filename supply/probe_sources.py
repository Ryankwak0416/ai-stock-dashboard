# -*- coding: utf-8 -*-
"""
수급 앱 원천 시험 (GitHub Actions 에서 실행 — Claude 컨테이너는 naver·daum·kiwoom 이 막혀 있다)
  1) 러너 공인 IP — 키움 REST 의 IP 등록 판단용
  2) 키움 REST 토큰 엔드포인트 접속 — 키가 없으면 가짜 키로 접속 여부만, KIWOOM_APPKEY/SECRETKEY 가 있으면 실제 발급 시도
     (키·토큰 값은 절대 출력하지 않는다)
  3) 네이버·다음 공개 API 의 수급 관련 응답 필드
  4) 네이버·다음 프론트 JS 번들에서 투자자·프로그램·선물 관련 /api 경로 찾기
"""
import os, re, json, time
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
      "Accept": "*/*"}
KW = re.compile(r"invest|program|trend|futures|deal|foreign|institu|credit|short|loan|deposit|programTrade|frgn", re.I)


def sec(t):
    print(f"\n######## {t}", flush=True)


def show(name, url, method="GET", headers=None, body=None, n=1500):
    try:
        h = dict(UA, **(headers or {}))
        r = requests.request(method, url, headers=h, json=body, timeout=15)
        t = r.text
        print(f"=== {name} [{r.status_code}] len={len(t)} {url}")
        print(t[:n].replace("\n", " "))
        return r
    except Exception as e:
        print(f"=== {name} ERROR {type(e).__name__}: {e} {url}")


def kiwoom():
    sec("1) runner IP")
    show("ipify", "https://api.ipify.org?format=json", n=200)
    show("ipinfo", "https://ipinfo.io/json", n=400)

    sec("2) kiwoom REST token")
    ak, sk = os.environ.get("KIWOOM_APPKEY", ""), os.environ.get("KIWOOM_SECRETKEY", "")
    print("secrets present:", bool(ak), bool(sk))
    for host in ["https://api.kiwoom.com", "https://mockapi.kiwoom.com"]:
        body = {"grant_type": "client_credentials", "appkey": ak or "dummy", "secretkey": sk or "dummy"}
        try:
            r = requests.post(f"{host}/oauth2/token", json=body, timeout=15,
                              headers={"Content-Type": "application/json;charset=UTF-8"})
            j = {}
            try:
                j = r.json()
            except Exception:
                pass
            safe = {k: (f"<{len(str(v))}자>" if k in ("token", "access_token") else v) for k, v in j.items()}
            print(f"=== {host} [{r.status_code}] {json.dumps(safe, ensure_ascii=False)[:600] if j else r.text[:300]}")
        except Exception as e:
            print(f"=== {host} ERROR {type(e).__name__}: {e}")


def public():
    sec("3) naver / daum public")
    d = "20261030"
    nv = {"Referer": "https://m.stock.naver.com/"}
    dm = {"Referer": "https://finance.daum.net/domestic/investor"}
    for name, url, h in [
        ("nv-trend-kospi", f"https://m.stock.naver.com/api/index/KOSPI/trend?bizdate={d}", nv),
        ("nv-trend-nodate", "https://m.stock.naver.com/api/index/KOSPI/trend", nv),
        ("nv-integration", "https://m.stock.naver.com/api/index/KOSPI/integration", nv),
        ("nv-basic", "https://m.stock.naver.com/api/index/KOSPI/basic", nv),
        ("nv-program", "https://m.stock.naver.com/api/index/KOSPI/program", nv),
        ("nv-investor", "https://m.stock.naver.com/api/index/KOSPI/investor", nv),
        ("nv-fut-trend", "https://m.stock.naver.com/api/index/FUT/trend", nv),
        ("nv-fut-basic", "https://m.stock.naver.com/api/index/FUT/basic", nv),
        ("dm-investor-days", "https://finance.daum.net/api/investor/days?market=KOSPI&page=1&perPage=3", dm),
        ("dm-investor-detail", "https://finance.daum.net/api/investor/days?market=KOSPI&page=1&perPage=3&detail=true", dm),
        ("dm-investor-times", "https://finance.daum.net/api/investor/times?market=KOSPI", dm),
        ("dm-program-days", "https://finance.daum.net/api/program/days?market=KOSPI&page=1&perPage=3", dm),
        ("dm-program-times", "https://finance.daum.net/api/program/times?market=KOSPI", dm),
        ("dm-futures-investor", "https://finance.daum.net/api/investor/days?market=FUTURES&page=1&perPage=3", dm),
    ]:
        show(name, url, headers=h, n=1200)


def bundles():
    sec("4) JS bundle api paths")
    for site, ref in [("https://stock.naver.com/", "https://stock.naver.com/"),
                      ("https://m.stock.naver.com/", "https://m.stock.naver.com/"),
                      ("https://stock.naver.com/market/stock/kr/investor", "https://stock.naver.com/"),
                      ("https://finance.daum.net/domestic/investor", "https://finance.daum.net/"),
                      ("https://finance.daum.net/domestic/program", "https://finance.daum.net/")]:
        try:
            html = requests.get(site, headers=dict(UA, Referer=ref), timeout=15).text
        except Exception as e:
            print(f"=== {site} ERROR {e}")
            continue
        srcs = sorted(set(re.findall(r'src="([^"]+\.js[^"]*)"', html)))
        base = re.match(r"https://[^/]+", site).group(0)
        found = set(p for p in re.findall(r'["\'`](/api/[A-Za-z0-9_/\-{}$.:?=&]+)', html) if KW.search(p))
        for s in srcs[:80]:
            u = s if s.startswith("http") else base + (s if s.startswith("/") else "/" + s)
            try:
                js = requests.get(u, headers=dict(UA, Referer=site), timeout=15).text
            except Exception:
                continue
            for p in re.findall(r'["\'`](/?api/[A-Za-z0-9_/\-{}$.:?=&]+|https://[a-z.]*(?:naver|daum)[a-z.]*/api/[A-Za-z0-9_/\-{}$.:?=&]+)', js):
                if KW.search(p):
                    found.add(p)
            time.sleep(0.1)
        print(f"=== {site} scripts={len(srcs)} paths={len(found)}")
        for p in sorted(found)[:150]:
            print("   ", p)


if __name__ == "__main__":
    kiwoom()
    public()
    bundles()
