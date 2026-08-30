# -*- coding: utf-8 -*-
"""
106 보조지표 엔진 — 계산 → 정규화 → 중복가중 축소 → 카테고리/종합 점수

설계 원칙 (HB Radar 분석문서의 ①~⑦ 결정사항 반영)
--------------------------------------------------------------
③ 정규화 : 지표마다 스케일이 제각각(MACD는 원화 단위, RSI는 0~100)이므로
           각 지표를 "과거 RANK_WIN일 백분위"로 변환해 0~100으로 통일한다.
           → 종목 간 비교가 가능해지고, 분포가 넓게 퍼져 판별력이 생긴다.
           On/Off 형태의 지표(슈퍼트렌드·캔들패턴 등)는 백분위가 무의미하므로
           mode='direct'로 두고 -1~+1을 그대로 0~100에 매핑한다.

① 지표 중복 : 106개 중 상당수가 사실상 같은 정보다(SMA5~SMA200 등).
           지표마다 redundancy group(grp)을 부여하고 가중치를 1/그룹크기로 준다.
           → 화면에는 106개가 모두 보이지만, 점수에서는 같은 정보를 여러 번 세지 않는다.

② 카테고리 가중치 : 8개 카테고리의 가중치를 CATEGORY_W에 명시한다(비공개 아님).
           카테고리 내부는 위의 그룹가중 평균, 카테고리 간은 CATEGORY_W 가중 평균.

④ 판정 임계값 : 정규화 점수 기준 65 이상 매수 / 35 이하 매도 / 그 사이 보합.
⑤ 등급 구간   : 70+ 강세 / 55~69 상승우위 / 45~54 중립 / 30~44 하락우위 / 30미만 약세

입력  : Open/High/Low/Close/Volume 컬럼을 가진 DataFrame (DatetimeIndex, 일봉)
출력  : compute(df) → dict
        {"score": [...], "cat": {"이동평균": [...], ...},
         "cnt": {"buy": [...], "hold": [...], "sell": [...]},
         "last": [{"key","name","cat","val","score","sig"}, ...106개]}

외부 라이브러리: pandas / numpy 만 사용 (TA-Lib 불필요)
"""
import numpy as np
import pandas as pd

RANK_WIN = 250      # 백분위 정규화 창(약 1년)
RANK_MIN = 60       # 최소 표본
BUY_TH, SELL_TH = 65.0, 35.0

CATEGORY_W = {
    "추세":     0.20,
    "모멘텀":   0.20,
    "이동평균": 0.18,
    "거래량":   0.15,
    "변동성":   0.12,
    "지지저항": 0.07,
    "통계":     0.04,
    "캔들패턴": 0.04,
}

# ────────────────────────────── 기본 계산 도구 ──────────────────────────────
def _sma(s, n):  return s.rolling(n, min_periods=n).mean()
def _ema(s, n):  return s.ewm(span=n, adjust=False, min_periods=n).mean()
def _std(s, n):  return s.rolling(n, min_periods=n).std(ddof=0)


def _wma(s, n):
    w = np.arange(1, n + 1, dtype=float)
    return s.rolling(n, min_periods=n).apply(lambda x: float(np.dot(x, w) / w.sum()), raw=True)


def _dema(s, n):
    e = _ema(s, n)
    return 2 * e - _ema(e, n)


def _tema(s, n):
    e1 = _ema(s, n); e2 = _ema(e1, n); e3 = _ema(e2, n)
    return 3 * e1 - 3 * e2 + e3


def _vwma(c, v, n):
    return (c * v).rolling(n, min_periods=n).sum() / v.rolling(n, min_periods=n).sum()


def _tr(h, l, c):
    pc = c.shift(1)
    return pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)


def _rma(s, n):
    """Wilder 평활 (RSI/ADX/ATR 표준)"""
    return s.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


def _atr(h, l, c, n=14):
    return _rma(_tr(h, l, c), n)


def _rsi(c, n):
    d = c.diff()
    up = _rma(d.clip(lower=0), n)
    dn = _rma((-d).clip(lower=0), n)
    rs = up / dn.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


def _stoch_k(h, l, c, n, slowing):
    ll = l.rolling(n, min_periods=n).min()
    hh = h.rolling(n, min_periods=n).max()
    rng = (hh - ll).replace(0, np.nan)
    return ((c - ll) / rng * 100).rolling(slowing, min_periods=slowing).mean()


def _macd(c, f=12, s=26, sig=9):
    line = _ema(c, f) - _ema(c, s)
    signal = _ema(line, sig)
    return line, signal, line - signal


def _linreg_slope(s, n):
    x = np.arange(n, dtype=float)
    xm = x.mean(); den = ((x - xm) ** 2).sum()
    return s.rolling(n, min_periods=n).apply(
        lambda y: float(((x - xm) * (y - y.mean())).sum() / den), raw=True)


def _psar(h, l, af0=0.02, afmax=0.2):
    hi = h.to_numpy(float); lo = l.to_numpy(float); n = len(hi)
    out = np.full(n, np.nan)
    if n < 3:
        return pd.Series(out, index=h.index)
    bull = True; af = af0; ep = hi[0]; sar = lo[0]
    for i in range(1, n):
        sar = sar + af * (ep - sar)
        if bull:
            sar = min(sar, lo[i - 1], lo[max(i - 2, 0)])
            if lo[i] < sar:
                bull = False; sar = ep; ep = lo[i]; af = af0
            elif hi[i] > ep:
                ep = hi[i]; af = min(af + af0, afmax)
        else:
            sar = max(sar, hi[i - 1], hi[max(i - 2, 0)])
            if hi[i] > sar:
                bull = True; sar = ep; ep = hi[i]; af = af0
            elif lo[i] < ep:
                ep = lo[i]; af = min(af + af0, afmax)
        out[i] = sar
    return pd.Series(out, index=h.index)


def _supertrend(h, l, c, n=10, mult=3.0):
    atr = _atr(h, l, c, n)
    hl2 = (h + l) / 2
    ub = (hl2 + mult * atr).to_numpy(float)
    lb = (hl2 - mult * atr).to_numpy(float)
    cl = c.to_numpy(float); N = len(cl)
    dirn = np.full(N, np.nan); fu = np.full(N, np.nan); fl = np.full(N, np.nan)
    d = 1
    for i in range(N):
        if np.isnan(ub[i]):
            continue
        pu = fu[i - 1] if i and not np.isnan(fu[i - 1]) else ub[i]
        pl = fl[i - 1] if i and not np.isnan(fl[i - 1]) else lb[i]
        fu[i] = ub[i] if (ub[i] < pu or cl[i - 1] > pu) else pu
        fl[i] = lb[i] if (lb[i] > pl or cl[i - 1] < pl) else pl
        if cl[i] > fu[i]:
            d = 1
        elif cl[i] < fl[i]:
            d = -1
        dirn[i] = d
    return pd.Series(dirn, index=c.index)


def _entropy(s, n=20, bins=8):
    def f(x):
        hgram, _ = np.histogram(x, bins=bins)
        p = hgram[hgram > 0] / hgram.sum()
        return float(-(p * np.log(p)).sum() / np.log(bins))
    return s.rolling(n, min_periods=n).apply(f, raw=True)


# ────────────────────────── 106지표 정의 ──────────────────────────
# 각 항목: (key, 표시명, 카테고리, 중복그룹, mode, 값함수, bull함수)
#   mode 'rank'   : bull 값을 과거 백분위로 정규화
#   mode 'direct' : bull 값이 이미 -1~+1 → 그대로 0~100 매핑
#   bull 은 "클수록 강세"가 되도록 방향을 맞춘 값.
#   과열지표(RSI·스토캐스틱·CCI 등)는 역추세 관점(과매도=강세)으로 부호를 뒤집는다.

def _build(df):
    o, h, l, c = df["Open"], df["High"], df["Low"], df["Close"]
    v = df["Volume"].astype(float).replace(0, np.nan)
    p = c.replace(0, np.nan)
    ind = []   # (key, name, cat, grp, mode, val, bull)

    def add(key, name, cat, grp, mode, val, bull):
        ind.append((key, name, cat, grp, mode, val, bull))

    # ───────── 이동평균 23 ─────────
    ma_defs = [
        ("SMA5", "SMA 5", 5, _sma(c, 5), "MA_S"), ("SMA10", "SMA 10", 10, _sma(c, 10), "MA_S"),
        ("SMA20", "SMA 20", 20, _sma(c, 20), "MA_M"), ("SMA50", "SMA 50", 50, _sma(c, 50), "MA_M"),
        ("SMA60", "SMA 60", 60, _sma(c, 60), "MA_M"), ("SMA120", "SMA 120", 120, _sma(c, 120), "MA_L"),
        ("SMA200", "SMA 200", 200, _sma(c, 200), "MA_L"),
        ("EMA12", "EMA 12", 12, _ema(c, 12), "MA_S"), ("EMA20", "EMA 20", 20, _ema(c, 20), "MA_M"),
        ("EMA26", "EMA 26", 26, _ema(c, 26), "MA_M"), ("EMA50", "EMA 50", 50, _ema(c, 50), "MA_M"),
        ("EMA200", "EMA 200", 200, _ema(c, 200), "MA_L"),
        ("WMA20", "WMA 20", 20, _wma(c, 20), "MA_M"), ("WMA200", "WMA 200", 200, _wma(c, 200), "MA_L"),
        ("DEMA20", "DEMA 20", 20, _dema(c, 20), "MA_M"), ("TEMA20", "TEMA 20", 20, _tema(c, 20), "MA_M"),
        ("VWMA20", "VWMA 20", 20, _vwma(c, v, 20), "MA_M"),
    ]
    for key, nm, span, series, grp in ma_defs:
        slope = (series - series.shift(max(3, span // 4))) / p    # 기울기(가격 대비)
        add(key, nm + " 기울기", "이동평균", grp, "rank", series, slope)

    s5, s20, s60 = _sma(c, 5), _sma(c, 20), _sma(c, 60)
    s50, s200 = _sma(c, 50), _sma(c, 200)
    add("X_5_20", "5/20 크로스", "이동평균", "MA_X", "rank", s5 / s20 - 1, s5 / s20 - 1)
    add("X_20_60", "20/60 크로스", "이동평균", "MA_X", "rank", s20 / s60 - 1, s20 / s60 - 1)
    add("X_GMA", "골든/데드 크로스(50·200)", "이동평균", "MA_X", "rank", s50 / s200 - 1, s50 / s200 - 1)
    add("P_SMA20", "종가 vs SMA20", "이동평균", "MA_P", "rank", c / s20 - 1, c / s20 - 1)
    add("P_SMA60", "종가 vs SMA60", "이동평균", "MA_P", "rank", c / s60 - 1, c / s60 - 1)
    add("P_SMA200", "종가 vs SMA200", "이동평균", "MA_P", "rank", c / s200 - 1, c / s200 - 1)

    # ───────── 모멘텀 25 ─────────
    for n in (7, 14, 21):
        r = _rsi(c, n)
        add(f"RSI{n}", f"RSI {n}", "모멘텀", "OSC_RSI", "rank", r, -(r - 50))
    sk = _stoch_k(h, l, c, 14, 3); sd = sk.rolling(3, min_periods=3).mean()
    add("STOCH_K", "스토캐스틱 %K", "모멘텀", "OSC_ST", "rank", sk, -(sk - 50))
    add("STOCH_D", "스토캐스틱 %D", "모멘텀", "OSC_ST", "rank", sd, -(sd - 50))
    r14 = _rsi(c, 14)
    rmin = r14.rolling(14, min_periods=14).min(); rmax = r14.rolling(14, min_periods=14).max()
    srk = ((r14 - rmin) / (rmax - rmin).replace(0, np.nan) * 100).rolling(3, min_periods=3).mean()
    srd = srk.rolling(3, min_periods=3).mean()
    add("STOCHRSI_K", "StochRSI %K", "모멘텀", "OSC_ST", "rank", srk, -(srk - 50))
    add("STOCHRSI_D", "StochRSI %D", "모멘텀", "OSC_ST", "rank", srd, -(srd - 50))
    ml, ms, mh = _macd(c)
    add("MACD_SIG", "MACD vs 시그널", "모멘텀", "MACD", "rank", ml - ms, (ml - ms) / p)
    add("MACD_HIST", "MACD 히스토그램 변화", "모멘텀", "MACD", "rank", mh, mh.diff() / p)
    add("MACD_LINE", "MACD 라인", "모멘텀", "MACD", "rank", ml, ml / p)
    tp = (h + l + c) / 3
    cci = (tp - _sma(tp, 20)) / (0.015 * tp.rolling(20, min_periods=20).apply(
        lambda x: float(np.abs(x - x.mean()).mean()), raw=True))
    add("CCI20", "CCI 20", "모멘텀", "IND", "rank", cci, -cci)
    hh14 = h.rolling(14, min_periods=14).max(); ll14 = l.rolling(14, min_periods=14).min()
    wr = (hh14 - c) / (hh14 - ll14).replace(0, np.nan) * -100
    add("WILLR", "Williams %R", "모멘텀", "OSC_ST", "rank", wr, wr + 50)
    add("ROC12", "ROC 12", "모멘텀", "ROC", "rank", c.pct_change(12) * 100, c.pct_change(12))
    add("ROC25", "ROC 25", "모멘텀", "ROC", "rank", c.pct_change(25) * 100, c.pct_change(25))
    add("MOM10", "Momentum 10", "모멘텀", "ROC", "rank", c - c.shift(10), (c - c.shift(10)) / p)
    ao = _sma((h + l) / 2, 5) - _sma((h + l) / 2, 34)
    add("AO", "Awesome Oscillator", "모멘텀", "IND", "rank", ao, ao / p)
    pc1 = c.diff()
    tsi = (_ema(_ema(pc1, 25), 13) / _ema(_ema(pc1.abs(), 25), 13).replace(0, np.nan)) * 100
    add("TSI", "TSI", "모멘텀", "MACD", "rank", tsi, tsi)
    bp = c - pd.concat([l, c.shift(1)], axis=1).min(axis=1)
    trr = _tr(h, l, c).replace(0, np.nan)
    uo = 100 * ((4 * bp.rolling(7).sum() / trr.rolling(7).sum())
                + (2 * bp.rolling(14).sum() / trr.rolling(14).sum())
                + (bp.rolling(28).sum() / trr.rolling(28).sum())) / 7
    add("UO", "Ultimate Oscillator", "모멘텀", "IND", "rank", uo, -(uo - 50))
    bbw = (4 * _std(c, 20)) / _sma(c, 20)
    kcw = (2 * 1.5 * _atr(h, l, c, 20)) / _sma(c, 20)
    add("SQUEEZE", "볼린저/켈트너 스퀴즈", "모멘텀", "IND", "rank", bbw - kcw, -(bbw - kcw))
    kdj_j = 3 * sk - 2 * sd
    add("KDJ", "KDJ (K+D)", "모멘텀", "OSC_ST", "rank", kdj_j, -(kdj_j - 50))
    su = pc1.clip(lower=0).rolling(14).sum(); sdn = (-pc1).clip(lower=0).rolling(14).sum()
    cmo = (su - sdn) / (su + sdn).replace(0, np.nan) * 100
    add("CMO14", "CMO 14", "모멘텀", "OSC_RSI", "rank", cmo, -cmo)
    ppo = (_ema(c, 12) - _ema(c, 26)) / _ema(c, 26) * 100
    add("PPO", "PPO", "모멘텀", "MACD", "rank", ppo, ppo)
    mid9 = (h.rolling(9).max() + l.rolling(9).min()) / 2
    x = ((tp - mid9) / (h.rolling(9).max() - l.rolling(9).min()).replace(0, np.nan)).clip(-0.499, 0.499)
    fish = np.log((1 + 2 * x) / (1 - 2 * x))
    fish = fish.ewm(alpha=0.5, adjust=False).mean()
    add("FISHER", "Fisher Transform", "모멘텀", "IND", "rank", fish, -fish)
    cop = _wma(c.pct_change(14) * 100 + c.pct_change(11) * 100, 10)
    add("COPPOCK", "Coppock Curve", "모멘텀", "ROC", "rank", cop, cop)
    num = (c - o) + 2 * (c.shift(1) - o.shift(1)) + 2 * (c.shift(2) - o.shift(2)) + (c.shift(3) - o.shift(3))
    den = (h - l) + 2 * (h.shift(1) - l.shift(1)) + 2 * (h.shift(2) - l.shift(2)) + (h.shift(3) - l.shift(3))
    rvgi = (num / 6).rolling(10).mean() / (den / 6).rolling(10).mean().replace(0, np.nan)
    add("RVGI", "RVGI", "모멘텀", "IND", "rank", rvgi, rvgi)

    # ───────── 추세 18 ─────────
    upm = h.diff(); dnm = -l.diff()
    plus_dm = ((upm > dnm) & (upm > 0)) * upm
    minus_dm = ((dnm > upm) & (dnm > 0)) * dnm
    atr14 = _atr(h, l, c, 14)
    di_p = 100 * _rma(plus_dm, 14) / atr14.replace(0, np.nan)
    di_m = 100 * _rma(minus_dm, 14) / atr14.replace(0, np.nan)
    dx = ((di_p - di_m).abs() / (di_p + di_m).replace(0, np.nan)) * 100
    adx = _rma(dx, 14)
    add("ADX_DI", "ADX DI+ vs DI−", "추세", "ADX", "rank", di_p - di_m, di_p - di_m)
    add("ADX", "ADX 추세강도", "추세", "ADX", "rank", adx, adx * np.sign(di_p - di_m))
    add("DI_P", "DI+", "추세", "ADX", "rank", di_p, di_p)
    add("DI_M", "DI−", "추세", "ADX", "rank", di_m, -di_m)
    au = h.rolling(25, min_periods=25).apply(lambda x: float(np.argmax(x)), raw=True) / 24 * 100
    ad_ = l.rolling(25, min_periods=25).apply(lambda x: float(np.argmin(x)), raw=True) / 24 * 100
    add("AROON_OSC", "Aroon Up−Down", "추세", "AROON", "rank", au - ad_, au - ad_)
    add("AROON_UP", "Aroon Up", "추세", "AROON", "rank", au, au)
    add("AROON_DN", "Aroon Down", "추세", "AROON", "rank", ad_, -ad_)
    vp = (h - l.shift(1)).abs().rolling(14).sum() / trr.rolling(14).sum()
    vm = (l - h.shift(1)).abs().rolling(14).sum() / trr.rolling(14).sum()
    add("VORTEX", "Vortex VI+ vs VI−", "추세", "IND", "rank", vp - vm, vp - vm)
    tenkan = (h.rolling(9).max() + l.rolling(9).min()) / 2
    kijun = (h.rolling(26).max() + l.rolling(26).min()) / 2
    spa = ((tenkan + kijun) / 2).shift(26)
    spb = ((h.rolling(52).max() + l.rolling(52).min()) / 2).shift(26)
    add("ICH_TK", "일목 전환선/기준선", "추세", "ICH", "rank", tenkan - kijun, (tenkan - kijun) / p)
    cloud_top = pd.concat([spa, spb], axis=1).max(axis=1)
    cloud_bot = pd.concat([spa, spb], axis=1).min(axis=1)
    cpos = np.where(c > cloud_top, 1.0, np.where(c < cloud_bot, -1.0, 0.0))
    add("ICH_CLOUD", "일목 구름대 위치", "추세", "ICH", "direct", pd.Series(cpos, index=c.index),
        pd.Series(cpos, index=c.index))
    add("ICH_TREND", "일목 구름 두께 추세", "추세", "ICH", "rank", spa - spb, (spa - spb) / p)
    st = _supertrend(h, l, c)
    add("SUPERTREND", "슈퍼트렌드", "추세", "IND", "direct", st, st)
    sar = _psar(h, l)
    add("PSAR", "Parabolic SAR", "추세", "IND", "direct", sar, np.sign(c - sar).fillna(0))
    dpo = c.shift(11) - _sma(c, 20)
    add("DPO20", "DPO 20", "추세", "IND", "rank", dpo, dpo / p)
    chop = 100 * np.log10(trr.rolling(14).sum()
                          / (h.rolling(14).max() - l.rolling(14).min()).replace(0, np.nan)) / np.log10(14)
    add("CHOP", "Choppiness Index", "추세", "IND", "rank", chop, -chop)
    trix = _ema(_ema(_ema(np.log(p), 15), 15), 15).diff() * 10000
    add("TRIX", "TRIX 시그널", "추세", "IND", "rank", trix, trix - _ema(trix, 9))
    lrs = _linreg_slope(c, 20)
    add("LINREG", "선형회귀 기울기 20", "추세", "IND", "rank", lrs, lrs / p)
    qst = _sma(c - o, 10)
    add("QSTICK", "Qstick 10", "추세", "IND", "rank", qst, qst / p)

    # ───────── 변동성 13 ─────────
    mid20 = _sma(c, 20); sd20 = _std(c, 20)
    pctb = (c - (mid20 - 2 * sd20)) / (4 * sd20).replace(0, np.nan) * 100
    add("BB_PCTB", "볼린저 %B", "변동성", "BAND", "rank", pctb, -(pctb - 50))
    add("ATR14", "ATR 14", "변동성", "VOLLV", "rank", atr14, -atr14 / p)
    natr = atr14 / p * 100
    add("NATR", "NATR", "변동성", "VOLLV", "rank", natr, -natr)
    kc_m = _ema(c, 20); kc_a = _atr(h, l, c, 20)
    kcp = (c - (kc_m - 1.5 * kc_a)) / (3 * kc_a).replace(0, np.nan) * 100
    add("KC_POS", "켈트너 채널 위치", "변동성", "BAND", "rank", kcp, -(kcp - 50))
    dch = h.rolling(20).max(); dcl = l.rolling(20).min()
    dcp = (c - dcl) / (dch - dcl).replace(0, np.nan) * 100
    add("DC_POS", "돈치안 채널 위치", "변동성", "BAND", "rank", dcp, -(dcp - 50))
    ret = np.log(p / p.shift(1))
    hv20 = ret.rolling(20).std(ddof=0) * np.sqrt(252) * 100
    hv60 = ret.rolling(60).std(ddof=0) * np.sqrt(252) * 100
    add("HV20", "역사적 변동성 20", "변동성", "VOLLV", "rank", hv20, -hv20)
    add("HV60", "역사적 변동성 60", "변동성", "VOLLV", "rank", hv60, -hv60)
    ce_l = h.rolling(22).max() - 3 * _atr(h, l, c, 22)
    ce_s = l.rolling(22).min() + 3 * _atr(h, l, c, 22)
    add("CE_LONG", "샹들리에 Exit(롱)", "변동성", "CE", "rank", ce_l, (c - ce_l) / p)
    add("CE_SHORT", "샹들리에 Exit(숏)", "변동성", "CE", "rank", ce_s, (c - ce_s) / p)
    ehl = _ema(h - l, 9); mass = (ehl / _ema(ehl, 9).replace(0, np.nan)).rolling(25).sum()
    add("MASS", "Mass Index", "변동성", "IND", "rank", mass, -mass)
    dd = c / c.cummax() * 100 - 100
    ulcer = np.sqrt((dd ** 2).rolling(14).mean())
    add("ULCER", "Ulcer Index", "변동성", "IND", "rank", ulcer, -ulcer)
    add("STDDEV20", "표준편차 20", "변동성", "VOLLV", "rank", sd20, -sd20 / p)
    add("TRUERANGE", "True Range", "변동성", "VOLLV", "rank", trr, -trr / p)

    # ───────── 거래량 12 ─────────
    obv = (np.sign(c.diff()).fillna(0) * v.fillna(0)).cumsum()
    add("OBV_SMA", "OBV vs SMA20", "거래량", "OBV", "rank", obv, obv - _sma(obv, 20))
    add("OBV_TREND", "OBV 추세", "거래량", "OBV", "rank", obv, obv.diff(10))
    tpv = (tp * v).cumsum() / v.cumsum()
    add("VWAP", "종가 vs 누적 VWAP", "거래량", "IND", "rank", tpv, c / tpv - 1)
    mfm = ((c - l) - (h - c)) / (h - l).replace(0, np.nan)
    cmf = (mfm * v).rolling(20).sum() / v.rolling(20).sum()
    add("CMF20", "차이킨 자금흐름 20", "거래량", "MF", "rank", cmf, cmf)
    rmf = tp * v
    pos = rmf.where(tp > tp.shift(1), 0).rolling(14).sum()
    neg = rmf.where(tp < tp.shift(1), 0).rolling(14).sum()
    mfi = 100 - 100 / (1 + pos / neg.replace(0, np.nan))
    add("MFI14", "MFI 14", "거래량", "MF", "rank", mfi, -(mfi - 50))
    pvt = (c.pct_change() * v).cumsum()
    add("PVT", "PVT", "거래량", "OBV", "rank", pvt, pvt.diff(10))
    nvi = pd.Series(1000.0, index=c.index)
    chg = c.pct_change().fillna(0); vdn = v.diff() < 0
    nvi = (1 + chg.where(vdn, 0)).cumprod() * 1000
    add("NVI", "NVI", "거래량", "IND", "rank", nvi, nvi / _sma(nvi, 60) - 1)
    adl = (mfm * v).fillna(0).cumsum()
    adosc = _ema(adl, 3) - _ema(adl, 10)
    add("ADOSC", "Chaikin A/D Oscillator", "거래량", "MF", "rank", adosc, adosc)
    add("VOL_RATIO", "거래량 비율(당일/20일)", "거래량", "VOLQ", "rank",
        v / _sma(v, 20), np.sign(c.diff()).fillna(0) * (v / _sma(v, 20)))
    dm_ = ((h + l) / 2) - ((h.shift(1) + l.shift(1)) / 2)
    cm_ = trr.rolling(34).sum()
    kvo = _ema(v * dm_.apply(np.sign) * (2 * (trr / cm_.replace(0, np.nan)) - 1).abs() * 100, 34) \
        - _ema(v * dm_.apply(np.sign) * (2 * (trr / cm_.replace(0, np.nan)) - 1).abs() * 100, 55)
    add("KVO", "Klinger Volume Oscillator", "거래량", "MF", "rank", kvo, kvo)
    add("VOL_SMA_RATIO", "거래량 SMA5/SMA20", "거래량", "VOLQ", "rank",
        _sma(v, 5) / _sma(v, 20), np.sign(c.diff(5)).fillna(0) * (_sma(v, 5) / _sma(v, 20)))
    add("ADLINE", "A/D Line 추세", "거래량", "OBV", "rank", adl, adl.diff(10))

    # ───────── 지지저항 5 ─────────
    # 피벗 4종의 bull 은 (종가−피벗)을 ATR 로 정규화하고 5일 평활한다.
    # 원값 그대로 쓰면 사실상 "전일 대비 하루 등락률"을 네 번 세는 것이 되어
    # 어제 급등한 종목이 이 카테고리를 독식한다 (2026-08-29 실데이터에서 확인).
    ph, pl_, pc_ = h.shift(1), l.shift(1), c.shift(1)
    atr_n = atr14.replace(0, np.nan)
    def _pivsm(dist):
        return (dist / atr_n).rolling(5, min_periods=3).mean()
    pp = (ph + pl_ + pc_) / 3
    add("PIVOT", "피벗 포인트", "지지저항", "PIV", "rank", pp, _pivsm(c - pp))
    rng1 = (ph - pl_)
    fib_p = pp
    add("FIB", "피보나치 피벗", "지지저항", "PIV", "rank", fib_p,
        ((c - (pp - 0.382 * rng1)) / (0.764 * rng1).replace(0, np.nan) - 0.5)
        .rolling(5, min_periods=3).mean())
    cam = pc_ + rng1 * 1.1 / 12
    add("CAMARILLA", "카마릴라 피벗", "지지저항", "PIV", "rank", cam, _pivsm(c - cam))
    wood = (ph + pl_ + 2 * c) / 4
    add("WOODIE", "우디 피벗", "지지저항", "PIV", "rank", wood, _pivsm(c - wood))
    w52h = c.rolling(252, min_periods=60).max(); w52l = c.rolling(252, min_periods=60).min()
    add("WEEK52", "52주 위치", "지지저항", "IND", "rank", (c - w52l) / (w52h - w52l).replace(0, np.nan) * 100,
        (c - w52l) / (w52h - w52l).replace(0, np.nan))

    # ───────── 통계 5 ─────────
    z20 = (c - mid20) / sd20.replace(0, np.nan)
    add("ZSCORE20", "Z-Score 20", "통계", "BAND", "rank", z20, -z20)
    skew = ret.rolling(60, min_periods=30).skew()
    add("SKEW", "수익률 왜도 60", "통계", "IND", "rank", skew, skew)
    kurt = ret.rolling(60, min_periods=30).kurt()
    add("KURT", "수익률 첨도 60", "통계", "IND", "rank", kurt, -kurt)
    add("VARIANCE", "수익률 분산 20", "통계", "IND", "rank",
        ret.rolling(20).var(ddof=0) * 1e4, -ret.rolling(20).var(ddof=0))
    ent = _entropy(ret.fillna(0), 20)
    add("ENTROPY", "수익률 엔트로피 20", "통계", "IND", "rank", ent, -ent)

    # ───────── 캔들패턴 5 ─────────
    ha_c = (o + h + l + c) / 4
    ha_o = ha_c.copy()
    hv_ = ha_c.to_numpy(float); ov = ((o + c) / 2).to_numpy(float)
    arr = np.full(len(hv_), np.nan)
    if len(hv_):
        arr[0] = ov[0]
        for i in range(1, len(hv_)):
            arr[i] = (arr[i - 1] + hv_[i - 1]) / 2
    ha_o = pd.Series(arr, index=c.index)
    add("HA_TREND", "하이킨아시 추세", "캔들패턴", "IND", "direct",
        np.sign(ha_c - ha_o).fillna(0), np.sign(ha_c - ha_o).fillna(0))
    body = (c - o); rng2 = (h - l).replace(0, np.nan)
    ups = h - pd.concat([o, c], axis=1).max(axis=1)
    dns = pd.concat([o, c], axis=1).min(axis=1) - l
    doji = ((body.abs() / rng2) < 0.1)
    trend_dn = c < _sma(c, 20)
    add("DOJI", "도지", "캔들패턴", "CAND", "direct",
        doji.astype(float), (doji & trend_dn).astype(float) - (doji & ~trend_dn).astype(float))
    bull_eng = (c > o) & (c.shift(1) < o.shift(1)) & (c >= o.shift(1)) & (o <= c.shift(1))
    bear_eng = (c < o) & (c.shift(1) > o.shift(1)) & (c <= o.shift(1)) & (o >= c.shift(1))
    add("ENGULFING", "장악형", "캔들패턴", "CAND", "direct",
        bull_eng.astype(float) - bear_eng.astype(float),
        bull_eng.astype(float) - bear_eng.astype(float))
    hammer = (dns > 2 * body.abs()) & (ups < body.abs())
    shoot = (ups > 2 * body.abs()) & (dns < body.abs())
    add("HAMMER", "망치형/유성형", "캔들패턴", "CAND", "direct",
        hammer.astype(float) - shoot.astype(float), hammer.astype(float) - shoot.astype(float))
    marubozu = (body.abs() / rng2 > 0.85)
    add("CANDLE", "장대양봉/장대음봉", "캔들패턴", "CAND", "direct",
        (marubozu * np.sign(body)).fillna(0), (marubozu * np.sign(body)).fillna(0))

    return ind


# ────────────────────────── 점수화 ──────────────────────────
def _normalize(bull, mode):
    b = pd.Series(bull).astype(float).replace([np.inf, -np.inf], np.nan)
    if mode == "direct":
        return (b.clip(-1, 1) + 1) * 50
    r = b.rolling(RANK_WIN, min_periods=RANK_MIN).rank(pct=True)
    return r * 100


def compute(df, keep=None, keep_detail=250):
    """OHLCV DataFrame → 106지표 점수 묶음

    keep        : 종합점수(score) 를 몇 봉 저장할지
    keep_detail : 카테고리·판정카운트를 몇 봉 저장할지(용량 절감용, 기본 250봉)
    """
    df = df.copy()
    if "Open" not in df or df["Open"].isna().all():
        df["Open"] = df["Close"]
    if "Volume" not in df:
        df["Volume"] = np.nan
    for col in ("Open", "High", "Low", "Close"):
        df[col] = df[col].astype(float).ffill()

    ind = _build(df)
    if len(ind) != 106:
        raise AssertionError(f"지표 개수가 106이 아님: {len(ind)}")

    idx = df.index
    # 중복그룹 크기 → 지표별 가중치 1/그룹크기
    gsize = {}
    for _, _, _, grp, _, _, _ in ind:
        gsize[grp] = gsize.get(grp, 0) + 1

    rows, cat_num, cat_den = [], {}, {}
    buy = pd.Series(0.0, idx); hold = pd.Series(0.0, idx); sell = pd.Series(0.0, idx)

    for key, name, cat, grp, mode, val, bull in ind:
        sc = _normalize(bull, mode).reindex(idx)
        w = 1.0 if grp == "IND" else 1.0 / gsize[grp]
        cat_num[cat] = cat_num.get(cat, pd.Series(0.0, idx)).add(sc.fillna(50.0) * w, fill_value=0)
        cat_den[cat] = cat_den.get(cat, 0.0) + w
        buy = buy.add((sc >= BUY_TH).astype(float), fill_value=0)
        sell = sell.add((sc <= SELL_TH).astype(float), fill_value=0)
        hold = hold.add(((sc > SELL_TH) & (sc < BUY_TH)).astype(float), fill_value=0)
        rows.append((key, name, cat, grp, round(w, 4), val, sc))

    cats_raw = {k: (cat_num[k] / cat_den[k]) for k in cat_num}
    # ── 카테고리 분산 균등화 ──
    # 지표 수가 적은 카테고리(지지저항·캔들패턴)는 점수 표준편차가 20을 넘고
    # 지표가 많은 카테고리(모멘텀)는 5 안팎이라, 명시한 가중치와 무관하게
    # 변동폭 큰 카테고리가 종합을 흔든다 (2026-08-29 실데이터: 지지저항 σ22 vs 모멘텀 σ5.5).
    # 각 카테고리 점수를 자기 과거 RANK_WIN일 백분위로 한 번 더 정규화해
    # 모든 카테고리가 같은 폭(0~100 균등분포)을 갖게 한 뒤 가중 평균한다.
    cats = {k: v.rolling(RANK_WIN, min_periods=RANK_MIN).rank(pct=True) * 100
            for k, v in cats_raw.items()}
    tw = sum(CATEGORY_W[k] for k in cats)
    score = sum(cats[k].fillna(cats_raw[k]) * CATEGORY_W[k] for k in cats) / tw

    n = len(idx) if keep is None else min(keep, len(idx))
    nd_ = min(keep_detail or n, n)
    sl = slice(len(idx) - n, len(idx))
    sl2 = slice(len(idx) - nd_, len(idx))

    def arr(s, nd=1, s_=None):
        seq = s.iloc[s_ or sl]
        if nd == 0:
            return [None if pd.isna(x) else int(round(float(x))) for x in seq]
        return [None if pd.isna(x) else round(float(x), nd) for x in seq]

    last = []
    for key, name, cat, grp, w, val, sc in rows:
        v = val.iloc[-1] if len(val) else np.nan
        s = sc.iloc[-1] if len(sc) else np.nan
        s_ = None if pd.isna(s) else round(float(s), 1)
        last.append({
            "k": key, "n": name, "c": cat, "g": grp, "w": w,
            "v": None if pd.isna(v) else round(float(v), 4),
            "s": s_,
            "j": 0 if s_ is None else (1 if s_ >= BUY_TH else (-1 if s_ <= SELL_TH else 0)),
        })

    return {
        "score": arr(score),
        "detail_n": nd_,
        "cat": {k: arr(cats[k], 0, sl2) for k in cats},
        "cnt": {"buy": arr(buy, 0, sl2), "hold": arr(hold, 0, sl2), "sell": arr(sell, 0, sl2)},
        "last": last,
        "w": {"category": CATEGORY_W, "group_size": gsize,
              "rank_win": RANK_WIN, "buy_th": BUY_TH, "sell_th": SELL_TH},
    }


def grade(s):
    if s is None:
        return "-"
    if s >= 70:  return "강세"
    if s >= 55:  return "상승우위"
    if s >= 45:  return "중립"
    if s >= 30:  return "하락우위"
    return "약세"
