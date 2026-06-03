# -*- coding: utf-8 -*-
"""
AI 관련주 대시보드 — 정적 페이지 빌더 (GitHub Actions에서 평일 자동 실행)
시세(FinanceDataReader/KRX) + 종목별 뉴스(Google News RSS)를 수집해 index.html 생성.
OFFLINE=1 이면 내장 스냅샷으로 생성(네트워크 불필요).
"""
import os, json, datetime, urllib.parse, urllib.request
import xml.etree.ElementTree as ET

OFFLINE = os.environ.get("OFFLINE") == "1"

META = [
 {"category":"AI 반도체-HBM/메모리","name":"삼성전자","code":"005930","market":"코스피","grade":"D","score":11,"comment":"1Q 매출 133.9조, 영업이익 57.2조 (분기 사상최대)","note":"DS 영업이익 53.7조"},
 {"category":"AI 반도체-HBM/메모리","name":"SK하이닉스","code":"000660","market":"코스피","grade":"D","score":20,"comment":"1Q 영업이익 37.6조, 영업이익률 72%","note":"PER 5.3배 역사최저"},
 {"category":"AI 서버 PCB/기판","name":"이수페타시스","code":"007660","market":"코스피","grade":"D","score":11,"comment":"엔비디아향 MLB, AI 슈퍼사이클 직접 수혜","note":"김상범 회장 부자 50위"},
 {"category":"AI 서버 PCB/기판","name":"대덕전자","code":"353200","market":"코스피","grade":"-","score":None,"comment":"FC-BGA, AI 가속기용 고다층","note":"캐시 미수록"},
 {"category":"AI 서버 PCB/기판","name":"심텍","code":"222800","market":"코스닥","grade":"D","score":0,"comment":"메모리 모듈 PCB","note":"캐시상 적자 -163억 (재확인 필요)"},
 {"category":"AI 후공정/장비","name":"한미반도체","code":"042700","market":"코스피","grade":"D","score":8,"comment":"TC본더 (HBM 핵심)","note":"2026 추정 PER 67배"},
 {"category":"AI 후공정/장비","name":"이오테크닉스","code":"039030","market":"코스닥","grade":"D","score":23,"comment":"레이저 장비, AI 슈퍼사이클 수혜주","note":"PER 35배 역사최저"},
 {"category":"AI 후공정/장비","name":"ISC","code":"095340","market":"코스닥","grade":"D","score":23,"comment":"테스트 소켓","note":"PER 24배 역사최저"},
 {"category":"AI 후공정/장비","name":"HPSP","code":"403870","market":"코스닥","grade":"D","score":11,"comment":"고압 어닐링, HBM 핵심 공정","note":"캐시 D11 (캐시원본 반영)"},
 {"category":"AI 팹리스","name":"텔레칩스","code":"054450","market":"코스닥","grade":"-","score":None,"comment":"차량용 AI SoC, 가온칩스로 디자인 파트너 변경","note":"캐시 미수록"},
 {"category":"AI 팹리스","name":"가온칩스","code":"399720","market":"코스닥","grade":"-","score":None,"comment":"삼성 파운드리 디자인하우스, 상장후 첫 적자지만 텔레칩스 수주↑","note":"단기 실적 변동 큼"},
 {"category":"AI 팹리스","name":"오픈엣지","code":"394280","market":"코스닥","grade":"-","score":None,"comment":"NPU IP","note":"캐시 미수록"},
 {"category":"AI 팹리스","name":"칩스앤미디어","code":"094360","market":"코스닥","grade":"-","score":None,"comment":"비디오 IP","note":"캐시 미수록"},
 {"category":"AI 팹리스","name":"에이직랜드","code":"445090","market":"코스닥","grade":"-","score":None,"comment":"TSMC 디자인 파트너","note":"캐시 미수록"},
 {"category":"AI 소프트웨어-대형","name":"NAVER","code":"035420","market":"코스피","grade":"D","score":23,"comment":"1Q 매출 3.24조, 분기 최대 실적","note":"실행형 AI 전략"},
 {"category":"AI 소프트웨어-대형","name":"카카오","code":"035720","market":"코스피","grade":"D","score":11,"comment":"1Q 매출 1.94조, 영업이익 2114억(+66%)","note":"챗GPT 포 카카오 가입자 1100만"},
 {"category":"AI 소프트웨어-소형","name":"코난테크놀로지","code":"402030","market":"코스닥","grade":"-","score":None,"comment":"매출 +29.1%, 손실 폭 축소 (개선중)","note":"캐시 미수록"},
 {"category":"AI 소프트웨어-소형","name":"솔트룩스","code":"304100","market":"코스닥","grade":"-","score":None,"comment":"매출 감소, 손실 확대, 5년째 적자","note":"⚠ 리스크 큼"},
 {"category":"AI 소프트웨어-소형","name":"셀바스AI","code":"108860","market":"코스닥","grade":"D","score":3,"comment":"2025 3Q 매출 258억, 영업이익 10억 (흑자)","note":"캐시상 D등급"},
 {"category":"AI 의료영상","name":"뷰노","code":"338220","market":"코스닥","grade":"B","score":60,"comment":"3기 연속 영업이익 증가, 영업이익률 빠른 개선","note":"★ 캐시 B등급(유일한 AI 우량주)"},
 {"category":"AI 의료영상","name":"루닛","code":"328130","market":"코스닥","grade":"C","score":48,"comment":"2025 매출 831억/영업손실 831억, 2000억 유증 진행","note":"⚠ 자생력 우려"},
 {"category":"AI 의료영상","name":"제이엘케이","code":"322510","market":"코스닥","grade":"-","score":None,"comment":"뇌질환 AI","note":"캐시 미수록"},
 {"category":"AI 의료영상","name":"딥노이드","code":"315640","market":"코스닥","grade":"-","score":None,"comment":"의료영상 플랫폼","note":"캐시 미수록"},
 {"category":"AI 로봇","name":"레인보우로보틱스","code":"277810","market":"코스닥","grade":"-","score":None,"comment":"삼성전자 지분 투자, 휴머노이드","note":"캐시 미수록"},
 {"category":"AI 로봇","name":"두산로보틱스","code":"454910","market":"코스피","grade":"D","score":28,"comment":"협동로봇 점유율 1위","note":"캐시 D28 (캐시원본 반영)"},
 {"category":"AI 로봇","name":"로보스타","code":"090360","market":"코스닥","grade":"-","score":None,"comment":"공장 자동화, 반도체 이송","note":"캐시 미수록"},
 {"category":"AI 로봇","name":"유진로봇","code":"056080","market":"코스닥","grade":"-","score":None,"comment":"자율주행 로봇","note":"캐시 미수록"},
 {"category":"AI 인프라/클라우드","name":"더존비즈온","code":"012510","market":"코스피","grade":"-","score":None,"comment":"SaaS·AI 회계","note":"캐시 미수록"},
 {"category":"AI 인프라/클라우드","name":"케이아이엔엑스","code":"093320","market":"코스닥","grade":"-","score":None,"comment":"IDC","note":"캐시 미수록"},
 {"category":"AI 인프라/클라우드","name":"가비아","code":"079940","market":"코스닥","grade":"-","score":None,"comment":"클라우드","note":"캐시 미수록"},
 {"category":"AI 보안","name":"안랩","code":"053800","market":"코스닥","grade":"D","score":5,"comment":"AI 보안","note":"PER 22.3배 고평가"},
 {"category":"AI 보안","name":"윈스","code":"136540","market":"코스닥","grade":"-","score":None,"comment":"네트워크 보안","note":"캐시 미수록"},
 {"category":"AI 콘텐츠/VFX","name":"자이언트스텝","code":"289220","market":"코스닥","grade":"-","score":None,"comment":"VFX·버추얼휴먼","note":"캐시 미수록"},
 {"category":"AI 콘텐츠/VFX","name":"위지윅스튜디오","code":"299900","market":"코스닥","grade":"-","score":None,"comment":"CG·메타휴먼","note":"캐시 미수록"},
]

SEED = {
 "005930":{"price":307000,"changePct":2.68,"t":"May 27","cap":"1952.71T","h52":323000,"l52":53800,"eps":12479},
 "000660":{"price":1610000,"changePct":0.56,"t":"May 7","cap":"1148.52T","h52":1648000,"l52":185900,"eps":60378},
 "007660":{"price":136300,"changePct":-2.22,"t":"Jun 2","cap":"10.01T","h52":164400,"l52":38000,"eps":2362},
 "353200":{"price":190900,"changePct":15.84,"t":"May 29","cap":"9.52T","h52":193500,"l52":14800,"eps":1918},
 "222800":{"price":131800,"changePct":5.02,"t":"May 22","cap":"4.94T","h52":135000,"l52":17660,"eps":-3222},
 "042700":{"price":393000,"changePct":-0.38,"t":"May 7","cap":"37.46T","h52":413000,"l52":76800,"eps":2256},
 "039030":{"price":473000,"changePct":7.01,"t":"May 18","cap":"5.73T","h52":527000,"l52":127500,"eps":4689},
 "095340":{"price":211500,"changePct":0.95,"t":"Jun 2","cap":"4.48T","h52":292500,"l52":49750,"eps":3309},
 "403870":{"price":60100,"changePct":9.87,"t":"May 26","cap":"4.95T","h52":67800,"l52":21200,"eps":1012},
 "054450":{"price":14710,"changePct":-4.48,"t":"May 29","cap":"222.77B","h52":19530,"l52":10970,"eps":-3875},
 "399720":{"price":58500,"changePct":6.56,"t":"May 29","cap":"692.57B","h52":83200,"l52":38900,"eps":-886},
 "394280":{"price":16180,"changePct":-1.16,"t":"May 29","cap":"426.29B","h52":22700,"l52":10310,"eps":-1311},
 "094360":{"price":15500,"changePct":-2.52,"t":"May 29","cap":"330.68B","h52":21150,"l52":13720,"eps":372},
 "445090":{"price":31350,"changePct":5.20,"t":"Jun 2","cap":"342.52B","h52":35900,"l52":23500,"eps":-1927},
 "035420":{"price":208000,"changePct":-0.48,"t":"May 6","cap":"32.63T","h52":295000,"l52":181100,"eps":12901},
 "035720":{"price":44700,"changePct":-2.83,"t":"May 11","cap":"19.81T","h52":71600,"l52":36300,"eps":1134},
 "402030":{"price":16930,"changePct":6.81,"t":"May 29","cap":"211.92B","h52":45899,"l52":15800,"eps":-867},
 "304100":{"price":18800,"changePct":2.12,"t":"May 29","cap":"236.76B","h52":58900,"l52":17240,"eps":-818},
 "108860":{"price":11090,"changePct":8.30,"t":"May 29","cap":"298.48B","h52":17580,"l52":9330,"eps":-179},
 "338220":{"price":8420,"changePct":-1.52,"t":"Jun 2","cap":"117.90B","h52":28350,"l52":7620,"eps":-463},
 "328130":{"price":16760,"changePct":0.60,"t":"May 29","cap":"1.25T","h52":28381,"l52":15313,"eps":-1107},
 "322510":{"price":4375,"changePct":-6.52,"t":"May 29","cap":"112.55B","h52":9210,"l52":3965,"eps":-562},
 "315640":{"price":2830,"changePct":-1.39,"t":"May 29","cap":"83.12B","h52":6354,"l52":2655,"eps":-504},
 "277810":{"price":763000,"changePct":-3.30,"t":"Jun 2","cap":"14.80T","h52":979000,"l52":249500,"eps":64},
 "454910":{"price":166700,"changePct":20.45,"t":"Jun 2","cap":"10.81T","h52":170000,"l52":46700,"eps":-852},
 "090360":{"price":158800,"changePct":29.95,"t":"Jun 2","cap":"1.55T","h52":158800,"l52":23550,"eps":-211},
 "056080":{"price":20550,"changePct":-2.84,"t":"May 29","cap":"770.87B","h52":49450,"l52":9650,"eps":-227},
 "012510":{"price":120000,"changePct":-0.08,"t":"Jun 2","cap":"3.49T","h52":128700,"l52":54300,"eps":3477},
 "093320":{"price":114800,"changePct":2.50,"t":"May 29","cap":"560.22B","h52":145100,"l52":76600,"eps":4387},
 "079940":{"price":31200,"changePct":-1.58,"t":"Jun 2","cap":"418.73B","h52":36750,"l52":21500,"eps":1350},
 "053800":{"price":61100,"changePct":-0.81,"t":"Jun 2","cap":"679.83B","h52":75000,"l52":57500,"eps":5941},
 "136540":{"price":12150,"changePct":-0.98,"t":"May 15","cap":"149.20B","h52":14580,"l52":10710,"eps":1699},
 "289220":{"price":1789,"changePct":2.05,"t":"Jun 2","cap":"39.92B","h52":8650,"l52":1668,"eps":-817},
 "299900":{"price":286,"changePct":-5.61,"t":"Jun 2","cap":"48.92B","h52":1544,"l52":282,"eps":-138},
}

def cap_str(won):
    try: w = float(won)
    except Exception: return "–"
    if w >= 1e12: return f"{w/1e12:.2f}T"
    if w >= 1e9:  return f"{w/1e9:.2f}B"
    if w >= 1e6:  return f"{w/1e6:.2f}M"
    return str(int(w))

def fetch_prices():
    import FinanceDataReader as fdr
    import pandas as pd
    prices = {c: dict(v) for c, v in SEED.items()}
    listing = None
    try:
        lst = fdr.StockListing("KRX")
        lst["Code"] = lst["Code"].astype(str).str.zfill(6)
        listing = lst.set_index("Code")
    except Exception as e:
        print("[warn] StockListing:", e)
    start = (datetime.date.today() - datetime.timedelta(days=400)).strftime("%Y-%m-%d")
    ok = 0
    for m in META:
        code = m["code"]
        try:
            df = fdr.DataReader(code, start)
            if df is None or len(df) == 0: continue
            close = float(df["Close"].iloc[-1]); prev = float(df["Close"].iloc[-2]) if len(df) >= 2 else close
            rec = prices[code]
            rec["price"] = int(round(close))
            rec["changePct"] = round((close - prev) / prev * 100, 2) if prev else 0.0
            win = df["Close"].tail(252)
            rec["h52"] = int(round(float(win.max()))); rec["l52"] = int(round(float(win.min())))
            rec["t"] = df.index[-1].strftime("%b %d")
            if listing is not None and code in listing.index:
                row = listing.loc[code]
                for col in ("Marcap","MarketCap","marcap"):
                    if col in listing.columns and pd.notna(row.get(col)):
                        rec["cap"] = cap_str(row.get(col)); break
            ok += 1
            print(f"  {code} {rec['price']:,} {rec['changePct']:+.2f}% ({rec['t']})")
        except Exception as e:
            print(f"[warn] {code}:", e)
    print(f"[시세] {ok}/{len(META)}")
    return prices, ok

def fetch_news(query, n=2):
    url = "https://news.google.com/rss/search?q=" + urllib.parse.quote(query + " 주가") + "&hl=ko&gl=KR&ceid=KR:ko"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    items = []
    with urllib.request.urlopen(req, timeout=10) as r:
        root = ET.fromstring(r.read())
    for it in root.iter("item"):
        src = it.find("source")
        items.append({"title": (it.findtext("title") or "").strip(),
                      "link": (it.findtext("link") or "").strip(),
                      "pubDate": (it.findtext("pubDate") or "").strip()[:22],
                      "source": (src.text if src is not None else "") or ""})
        if len(items) >= n: break
    return items

def main():
    if OFFLINE:
        prices, mode, news = SEED, "초기 데이터(스냅샷)", {}
        print("[모드] OFFLINE")
    else:
        prices, ok = fetch_prices()
        mode = f"라이브 {ok}/{len(META)}종목"
        news = {}
        for m in META:
            try:
                news[m["name"]] = fetch_news(m["name"], 2)
            except Exception as e:
                print("[warn] news", m["name"], e); news[m["name"]] = []
        print(f"[뉴스] {sum(1 for v in news.values() if v)}/{len(META)}종목")
    now = datetime.datetime.utcnow() + datetime.timedelta(hours=9)  # KST
    html = (TEMPLATE
            .replace("__META__", json.dumps(META, ensure_ascii=False))
            .replace("__PRICES__", json.dumps(prices, ensure_ascii=False))
            .replace("__NEWS__", json.dumps(news, ensure_ascii=False))
            .replace("__DATE__", now.strftime("%Y-%m-%d %H:%M"))
            .replace("__MODE__", mode))
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print("[생성]", out)

TEMPLATE = r"""<!doctype html>
<html lang="ko">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI 관련주 대시보드</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.5.0/dist/chart.umd.js"></script>
<style>
  :root{color-scheme:light;} *{box-sizing:border-box;}
  body{margin:0;background:#f6f7f9;color:#1a1d21;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Malgun Gothic",sans-serif;font-size:14px;line-height:1.5;}
  .wrap{max-width:1180px;margin:0 auto;padding:18px 16px 60px;}
  h1{font-size:20px;margin:0 0 2px;} .sub{color:#6b7280;font-size:12.5px;}
  .card{background:#fff;border:1px solid #e6e8eb;border-radius:12px;padding:14px 16px;margin-top:14px;}
  .kpis{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;margin-top:14px;}
  .kpi{background:#fff;border:1px solid #e6e8eb;border-radius:12px;padding:12px;}
  .kpi .n{font-size:20px;font-weight:700;} .kpi .l{font-size:11.5px;color:#6b7280;margin-top:2px;}
  .up{color:#dc2626;} .down{color:#2563eb;}
  .warn{background:#fff7ed;border:1px solid #fed7aa;color:#9a3412;} .warn b{color:#7c2d12;}
  .pill{font-size:11px;padding:2px 8px;border-radius:999px;background:#16a34a;color:#fff;}
  .rankrow{display:flex;gap:8px;align-items:flex-start;padding:6px 0;border-bottom:1px dashed #eee;} .rankrow:last-child{border-bottom:0;}
  .rk{flex:0 0 26px;height:26px;border-radius:50%;background:#111827;color:#fff;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:12px;}
  .charts{display:grid;grid-template-columns:1.1fr 0.8fr 1.1fr;gap:14px;}
  .chartbox{background:#fff;border:1px solid #e6e8eb;border-radius:12px;padding:12px;} .chartbox h3{font-size:13px;margin:0 0 8px;color:#374151;}
  canvas{max-height:250px;}
  .controls{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:14px;}
  select,input[type=text]{font-size:13px;padding:7px 9px;border:1px solid #d1d5db;border-radius:8px;background:#fff;color:#111;} input[type=text]{min-width:160px;}
  table{width:100%;border-collapse:collapse;margin-top:4px;font-size:13px;}
  th,td{text-align:left;padding:7px 8px;border-bottom:1px solid #eef0f2;vertical-align:top;}
  th{position:sticky;top:0;background:#fafbfc;cursor:pointer;user-select:none;white-space:nowrap;font-size:11.5px;color:#374151;}
  th.num,td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap;}
  td.name{font-weight:600;white-space:nowrap;} td.name .code{color:#9ca3af;font-weight:400;font-size:11px;}
  .chip{display:inline-block;padding:1px 7px;border-radius:999px;font-size:11px;font-weight:700;}
  .g-B{background:#dcfce7;color:#166534;} .g-C{background:#fef9c3;color:#854d0e;} .g-D{background:#fee2e2;color:#991b1b;} .g-x{background:#eef1f4;color:#6b7280;}
  .mk{display:inline-block;padding:1px 6px;border-radius:6px;font-size:10.5px;background:#eef2ff;color:#3730a3;} .mk.kosdaq{background:#ecfeff;color:#155e75;}
  .comment{color:#374151;max-width:280px;font-size:12px;} .note{color:#9ca3af;font-size:11px;}
  .w52{width:84px;} .w52 .bar{position:relative;height:6px;background:#eef0f2;border-radius:4px;margin-top:3px;} .w52 .dot{position:absolute;top:-2px;width:10px;height:10px;border-radius:50%;background:#111827;transform:translateX(-50%);}
  .nbtn{font-size:11px;padding:3px 8px;border:1px solid #d1d5db;border-radius:7px;background:#fff;cursor:pointer;white-space:nowrap;} .nbtn:hover{background:#f3f4f6;}
  .newscell{font-size:12px;color:#374151;background:#f9fafb;border-radius:8px;padding:8px 10px;margin-top:6px;} .newscell a{color:#1d4ed8;text-decoration:none;} .newscell .dt{color:#9ca3af;font-size:10.5px;}
  .headline{background:#fff;border:1px solid #e6e8eb;border-radius:10px;padding:9px 12px;margin-top:8px;} .headline .t{font-weight:600;font-size:13px;}
  .src{font-size:11px;color:#94a3b8;margin-top:4px;}
  @media(max-width:900px){.kpis{grid-template-columns:repeat(3,1fr);}.charts{grid-template-columns:1fr;}.comment{max-width:none;}}
</style>
<body>
<div class="wrap">
  <h1>AI 관련주 대시보드</h1>
  <div class="sub">갱신 <b>__DATE__</b> · <span class="pill">__MODE__</span> · 평일 장중 매시 + 18:10 자동 갱신(KST) · 시세 KRX 종가 · 뉴스 Google News</div>

  <div class="kpis" id="kpis"></div>

  <div class="card warn">
    <b>⚠️ 캐시 등급 vs 현재가</b> — 캐시 등급(D 다수)은 약 1년 전 어닝쇼크 기준. 지금은 AI 슈퍼사이클로 대부분 52주 고점권입니다.
    <b>캐시 등급만으로 판단하지 말고</b> 현재가·등락·52주 위치·뉴스를 함께 보세요.
  </div>

  <div class="charts">
    <div class="chartbox"><h3>등락률 (상위·하위)</h3><canvas id="moveChart"></canvas></div>
    <div class="chartbox"><h3>캐시 등급 분포</h3><canvas id="gradeChart"></canvas></div>
    <div class="chartbox"><h3>시가총액 상위 10</h3><canvas id="capChart"></canvas></div>
  </div>

  <div class="card">
    <h3 style="margin:0 0 4px;font-size:14px;">★ 카테고리 강도 순위 (필자 종합)</h3>
    <div id="ranks"></div>
  </div>

  <div class="card">
    <h3 style="margin:0 0 2px;font-size:14px;">📰 핵심 뉴스</h3>
    <div id="headlines"><div class="note">뉴스 없음(첫 자동 갱신 후 표시)</div></div>
  </div>

  <div class="card">
    <div class="controls">
      <select id="fCat"><option value="">전체 카테고리</option></select>
      <select id="fMkt"><option value="">전체 시장</option><option>코스피</option><option>코스닥</option></select>
      <select id="fGrade"><option value="">전체 등급</option><option>B</option><option>C</option><option>D</option><option value="-">미수록</option></select>
      <input type="text" id="fSearch" placeholder="종목·코드·키워드 검색">
      <span class="note" id="cnt" style="margin-left:auto;"></span>
    </div>
    <div style="overflow:auto;max-height:680px;margin-top:8px;">
      <table id="tbl"><thead><tr>
        <th data-k="category">카테고리</th><th data-k="name">종목</th><th data-k="market">시장</th><th data-k="grade">등급</th>
        <th class="num" data-k="price">현재가</th><th class="num" data-k="changePct">등락%</th>
        <th class="num" data-k="capNum">시총</th><th class="num" data-k="per">PER</th>
        <th data-k="w52pos">52주 위치</th><th data-k="comment">1Q 실적·코멘트</th><th>뉴스</th>
      </tr></thead><tbody id="tbody"></tbody></table>
    </div>
    <div class="note" style="margin-top:6px;">※ 등락 색: <span class="up">빨강=상승</span>/<span class="down">파랑=하락</span>. 적자 종목은 PER 대신 '적자'. PER=현재가÷직전 EPS 추정. 뉴스는 매일 자동 갱신 시점 기준.</div>
  </div>
  <div class="src">베이스: AI관련주_재무정리 · 시세 FinanceDataReader/KRX · 뉴스 Google News · GitHub Actions 자동 빌드</div>
</div>

<script>
const META = __META__;
const PRICES = __PRICES__;
const NEWSDATA = __NEWS__;
const RANKS = [["1","AI 반도체-HBM/메모리","삼성전자, SK하이닉스"],["2","AI 서버 PCB/기판","이수페타시스, 대덕전자"],["3","AI 후공정/장비","한미반도체, HPSP"],["4","AI 소프트웨어-대형","NAVER, 카카오"],["5","AI 의료영상","뷰노 ★ 유일한 캐시 B등급"]];
const LEADERS=["삼성전자","SK하이닉스","이수페타시스","NAVER","뷰노"];
function capNum(s){ if(!s)return -1; const m=String(s).match(/([\d.]+)\s*([TBM]?)/); if(!m)return -1; let v=parseFloat(m[1]); const u=m[2]; if(u==="T")v*=1e12; else if(u==="B")v*=1e9; else if(u==="M")v*=1e6; return v; }
const STOCKS = META.map(function(m){ const s=Object.assign({},m); const p=PRICES[m.code];
  if(p){ s.price=p.price;s.changePct=p.changePct;s.cap=p.cap;s.capNum=capNum(p.cap);s.h52=p.h52;s.l52=p.l52;s.eps=p.eps;s.t=p.t;
    s.per=(p.eps&&p.eps>0)?+(p.price/p.eps).toFixed(1):null;
    s.w52pos=(p.h52>p.l52)?Math.round((p.price-p.l52)/(p.h52-p.l52)*100):null;
  } else { s.price=null;s.changePct=null;s.capNum=-1;s.per=null;s.w52pos=null; } return s; });
const fmt=n=>n==null?"–":n.toLocaleString("ko-KR");
const gcls=g=>g==="B"?"g-B":g==="C"?"g-C":g==="D"?"g-D":"g-x";
const chCls=v=>v==null?"":v>0?"up":v<0?"down":"";
const chTxt=v=>v==null?"–":(v>0?"+":"")+v.toFixed(2)+"%";
const stripTags=s=>(s||"").replace(/<[^>]*>/g,"");
function renderKpis(){
  const ps=STOCKS.filter(s=>s.changePct!=null);
  const up=ps.filter(s=>s.changePct>0).length, dn=ps.filter(s=>s.changePct<0).length;
  const avg=ps.length?ps.reduce((a,s)=>a+s.changePct,0)/ps.length:0;
  const top=ps.slice().sort((a,b)=>b.changePct-a.changePct)[0]||{name:"-",changePct:null};
  const data=[["총 종목",STOCKS.length,""],["상승",up,"up"],["하락",dn,"down"],["평균 등락",(avg>0?"+":"")+avg.toFixed(1)+"%",avg>0?"up":"down"],["최고 상승",top.name+" "+chTxt(top.changePct),"up"],["캐시 B등급","뷰노 (1)",""]];
  document.getElementById("kpis").innerHTML=data.map(([l,n,c])=>`<div class="kpi"><div class="n ${c}">${n}</div><div class="l">${l}</div></div>`).join("");
}
function renderRanks(){ document.getElementById("ranks").innerHTML=RANKS.map(([r,c,d])=>`<div class="rankrow"><div class="rk">${r}</div><div><b>${c}</b><div class="note">${d}</div></div></div>`).join(""); }
function renderCharts(){
  const ps=STOCKS.filter(s=>s.changePct!=null).slice().sort((a,b)=>b.changePct-a.changePct);
  const movers=[...ps.slice(0,6),...ps.slice(-4)];
  new Chart(document.getElementById("moveChart"),{type:"bar",data:{labels:movers.map(s=>s.name),datasets:[{data:movers.map(s=>s.changePct),backgroundColor:movers.map(s=>s.changePct>0?"#ef4444":"#3b82f6")}]},options:{indexAxis:"y",plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>chTxt(c.raw)}}},maintainAspectRatio:false}});
  const gc={B:0,C:0,D:0,"미수록":0}; STOCKS.forEach(s=>{gc[s.grade==="-"?"미수록":s.grade]++;});
  new Chart(document.getElementById("gradeChart"),{type:"doughnut",data:{labels:Object.keys(gc),datasets:[{data:Object.values(gc),backgroundColor:["#22c55e","#eab308","#ef4444","#cbd5e1"]}]},options:{plugins:{legend:{position:"bottom"}},maintainAspectRatio:false}});
  const cap=STOCKS.filter(s=>s.capNum>0).sort((a,b)=>b.capNum-a.capNum).slice(0,10);
  new Chart(document.getElementById("capChart"),{type:"bar",data:{labels:cap.map(s=>s.name),datasets:[{data:cap.map(s=>s.capNum/1e12),backgroundColor:"#6366f1"}]},options:{indexAxis:"y",plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>c.raw>=1?c.raw.toFixed(1)+"조":(c.raw*1000).toFixed(0)+"십억"}}},scales:{x:{title:{display:true,text:"조 원"}}},maintainAspectRatio:false}});
}
let sortK="changePct",sortDir=-1,fCat,fMkt,fGrade,fSearch;
function filtered(){
  const cat=fCat.value,mkt=fMkt.value,gr=fGrade.value,q=fSearch.value.trim().toLowerCase();
  let rows=STOCKS.filter(s=>(!cat||s.category===cat)&&(!mkt||s.market===mkt)&&(!gr||s.grade===gr)&&(!q||(s.name+s.code+s.comment+s.note+s.category).toLowerCase().includes(q)));
  rows.sort((a,b)=>{let x=a[sortK],y=b[sortK];const numK=["price","changePct","capNum","per","score","w52pos"].includes(sortK);if(numK){x=x==null?-Infinity:x;y=y==null?-Infinity:y;return (x-y)*sortDir;}return (x||"").toString().localeCompare((y||"").toString(),"ko")*sortDir;});
  return rows;
}
function renderTable(){
  const rows=filtered();
  document.getElementById("cnt").textContent=`${rows.length} / ${STOCKS.length} 종목`;
  document.getElementById("tbody").innerHTML=rows.map(s=>{
    const mk=`<span class="mk ${s.market==="코스닥"?"kosdaq":""}">${s.market}</span>`;
    const per=s.per==null?(s.eps!=null&&s.eps<=0?'<span class="note">적자</span>':'–'):s.per;
    const w52=s.w52pos==null?'':`<div class="w52"><div class="note">${s.w52pos}%</div><div class="bar"><div class="dot" style="left:${s.w52pos}%"></div></div></div>`;
    const hasNews=(NEWSDATA[s.name]||[]).length>0;
    const nbtn=hasNews?`<button class="nbtn" data-q="${s.name}">뉴스 ▾</button><div class="nw"></div>`:'<span class="note">-</span>';
    return `<tr><td class="note">${s.category}</td><td class="name">${s.name}<br><span class="code">${s.code}</span></td><td>${mk}</td><td><span class="chip ${gcls(s.grade)}">${s.grade==="-"?"미수록":s.grade}${s.score!=null?" "+s.score:""}</span></td><td class="num">${fmt(s.price)}</td><td class="num ${chCls(s.changePct)}" title="${s.t||""} 기준">${chTxt(s.changePct)}</td><td class="num">${s.cap||"–"}</td><td class="num">${per}</td><td>${w52}</td><td class="comment">${s.comment}<div class="note">${s.note}</div></td><td>${nbtn}</td></tr>`;
  }).join("");
}
function setupSort(){ document.querySelectorAll("#tbl th[data-k]").forEach(th=>{ th.onclick=()=>{const k=th.dataset.k; if(sortK===k)sortDir*=-1; else{sortK=k;sortDir=(["category","name","market","grade"].includes(k))?1:-1;} renderTable();}; }); }
function newsHtml(items){ if(!items||!items.length) return '<div class="note">뉴스 없음</div>'; return items.map(it=>`<div class="newscell"><a href="${it.link}" target="_blank" rel="noopener">${stripTags(it.title)}</a><div class="dt">${it.source||""} · ${it.pubDate||""}</div></div>`).join(""); }
function bindNews(){
  document.getElementById("tbody").addEventListener("click",e=>{
    const b=e.target.closest(".nbtn"); if(!b)return;
    const wrap=b.parentElement.querySelector(".nw");
    if(wrap.dataset.open==="1"){wrap.innerHTML="";wrap.dataset.open="0";b.textContent="뉴스 ▾";return;}
    wrap.innerHTML=newsHtml(NEWSDATA[b.dataset.q]); wrap.dataset.open="1"; b.textContent="뉴스 ▴";
  });
}
function renderHeadlines(){
  const box=document.getElementById("headlines"); let html="";
  LEADERS.forEach(n=>{ const it=(NEWSDATA[n]||[])[0]; if(it) html+=`<div class="headline"><div class="t">${n} · <a href="${it.link}" target="_blank" rel="noopener" style="color:#1d4ed8;text-decoration:none;">${stripTags(it.title)}</a></div><div class="note">${it.source||""} · ${it.pubDate||""}</div></div>`; });
  if(html) box.innerHTML=html;
}
function init(){
  fCat=document.getElementById("fCat");fMkt=document.getElementById("fMkt");fGrade=document.getElementById("fGrade");fSearch=document.getElementById("fSearch");
  [...new Set(META.map(s=>s.category))].forEach(c=>{const o=document.createElement("option");o.textContent=c;fCat.appendChild(o);});
  renderKpis();renderRanks();renderCharts();renderTable();setupSort();bindNews();renderHeadlines();
  ["fCat","fMkt","fGrade","fSearch"].forEach(id=>document.getElementById(id).addEventListener("input",renderTable));
}
init();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
