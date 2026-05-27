"""
signal_engine.py
================
Crypto3.html dosyasındaki sinyal mantığının birebir Python karşılığı.

HTML referansları:
  - ema()            → satır 927
  - rsi()            → satır 934
  - pattern()        → satır 944
  - trend()          → satır 961
  - volTrend()       → satır 974
  - calculateScore() → satır 985 (LONG)
  - calculateShortScore() → satır 1036 (SHORT)
  - scoreToSignal()  → satır 1018
  - Tetikleme: 1m+3m+5m üçü de >= 80
"""

from typing import List, Dict, Optional, Literal
from dataclasses import dataclass


# ──────────────────────────────────────────────────────────────
# Veri tipleri
# ──────────────────────────────────────────────────────────────
@dataclass
class Candle:
    """Tek bir mum: open, high, low, close, volume."""
    o: float
    h: float
    l: float
    c: float
    v: float

    @classmethod
    def from_binance_kline(cls, kline: list) -> "Candle":
        # Binance kline formatı:
        # [openTime, open, high, low, close, volume, closeTime, ...]
        return cls(
            o=float(kline[1]),
            h=float(kline[2]),
            l=float(kline[3]),
            c=float(kline[4]),
            v=float(kline[5]),
        )


@dataclass
class TrendResult:
    label: str
    direction: Literal["bull", "bear", "neutral"]
    strength: int = 0  # 0, 1, 2


@dataclass
class PatternResult:
    label: str
    sentiment: Literal["bull", "bear", "neutral"]


@dataclass
class VolumeResult:
    label: str
    mult: float


@dataclass
class TFAnalysis:
    """Tek bir timeframe'in tam analizi."""
    timeframe: str
    long_score: int
    short_score: int
    trend: TrendResult
    rsi: Optional[float]
    pattern: PatternResult
    volume: VolumeResult


# ──────────────────────────────────────────────────────────────
# İndikatörler (HTML birebir)
# ──────────────────────────────────────────────────────────────
def ema(values: List[float], period: int) -> Optional[float]:
    """Üstel hareketli ortalama. HTML satır 927."""
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    e = sum(values[:period]) / period
    for i in range(period, len(values)):
        e = values[i] * k + e * (1 - k)
    return e


def rsi(closes: List[float], period: int = 14) -> Optional[float]:
    """RSI hesabı. HTML satır 934."""
    if len(closes) < period + 1:
        return None
    g, l = 0.0, 0.0
    for i in range(len(closes) - period, len(closes)):
        d = closes[i] - closes[i - 1]
        if d > 0:
            g += d
        else:
            l += -d
    if l == 0:
        return 100.0
    return round(100 - 100 / (1 + g / l), 1)


def detect_pattern(candles: List[Candle]) -> PatternResult:
    """Mum formasyonu. HTML satır 944."""
    if len(candles) < 2:
        return PatternResult("—", "neutral")
    cur, prv = candles[-1], candles[-2]
    o, h, lo, cl = cur.o, cur.h, cur.l, cur.c
    po, pc = prv.o, prv.c

    body = abs(cl - o)
    rng = h - lo if h != lo else 1e-9
    up = h - max(o, cl)
    dn = min(o, cl) - lo

    if body / rng < 0.08:
        return PatternResult("Doji", "neutral")
    if dn > body * 2.2 and up < body * 0.5 and cl >= o:
        return PatternResult("Çekiç", "bull")
    if up > body * 2.2 and dn < body * 0.5 and cl <= o:
        return PatternResult("Kayan Yıldız", "bear")
    if pc < po and cl > o and cl >= po and o <= pc:
        return PatternResult("Bull Engulfing", "bull")
    if pc > po and cl < o and cl <= po and o >= pc:
        return PatternResult("Bear Engulfing", "bear")
    if cl > o and body / rng > 0.72:
        return PatternResult("Güçlü Yeşil", "bull")
    if cl < o and body / rng > 0.72:
        return PatternResult("Güçlü Kırmızı", "bear")
    if up > body and dn > body:
        return PatternResult("Spinning Top", "neutral")
    return PatternResult("Yükseliş" if cl > o else "Düşüş",
                         "bull" if cl > o else "bear")


def detect_trend(candles: List[Candle]) -> TrendResult:
    """EMA9 / EMA21 trendi. HTML satır 961."""
    if len(candles) < 21:
        return TrendResult("—", "neutral", 0)
    closes = [c.c for c in candles]
    e9 = ema(closes, 9)
    e21 = ema(closes, 21)
    if e9 is None or e21 is None:
        return TrendResult("—", "neutral", 0)
    last = closes[-1]
    diff = (e9 - e21) / e21

    if last > e9 and e9 > e21 and diff > 0.003:
        return TrendResult("↑ Güçlü Yükseliş", "bull", 2)
    if last < e9 and e9 < e21 and diff < -0.003:
        return TrendResult("↓ Güçlü Düşüş", "bear", 2)
    if abs(diff) < 0.0012:
        return TrendResult("→ Yatay", "neutral", 0)
    if e9 > e21:
        return TrendResult("↗ Hafif Yükseliş", "bull", 1)
    return TrendResult("↘ Hafif Düşüş", "bear", 1)


def detect_volume_trend(candles: List[Candle]) -> VolumeResult:
    """Hacim trendi: son 3 mum / önceki 3 mum. HTML satır 974."""
    if len(candles) < 6:
        return VolumeResult("—", 1.0)
    v = [c.v for c in candles[-6:]]
    recent = (v[3] + v[4] + v[5]) / 3
    older = (v[0] + v[1] + v[2]) / 3
    ratio = recent / (older if older else 1)

    if ratio > 1.35:
        return VolumeResult("🔥 Yüksek", ratio)
    if ratio < 0.7:
        return VolumeResult("❄️ Düşük", ratio)
    return VolumeResult("➡️ Normal", ratio)


# ──────────────────────────────────────────────────────────────
# Skorlama (HTML birebir)
# ──────────────────────────────────────────────────────────────
LONG_PATTERN_WEIGHTS = {
    "Güçlü Yeşil": 18, "Bull Engulfing": 20, "Çekiç": 16,
    "Güçlü Kırmızı": -18, "Bear Engulfing": -20, "Kayan Yıldız": -16,
    "Yükseliş": 8, "Düşüş": -8,
    "Doji": 0, "Spinning Top": 0,
}

SHORT_PATTERN_WEIGHTS = {
    "Güçlü Kırmızı": 18, "Bear Engulfing": 20, "Kayan Yıldız": 16,
    "Güçlü Yeşil": -18, "Bull Engulfing": -20, "Çekiç": -16,
    "Düşüş": 8, "Yükseliş": -8,
    "Doji": 0, "Spinning Top": 0,
}


def calculate_long_score(t: TrendResult, r: Optional[float],
                         p: PatternResult, v: VolumeResult) -> int:
    """HTML satır 985. LONG skoru 0-100."""
    score = 50.0

    if t.direction == "bull":
        score += 12 + (t.strength * 7)
    elif t.direction == "bear":
        score -= 12 + (t.strength * 7)

    score += LONG_PATTERN_WEIGHTS.get(p.label, 0)

    if r is not None:
        if r > 80:
            score -= 12
        elif r > 70:
            score -= 6
        elif r > 55:
            score += 5
        elif r >= 45:
            score += 0
        elif r >= 30:
            score -= 5
        elif r >= 20:
            score += 6
        else:
            score += 12

    if v.mult > 1.5 and score != 50:
        score += 5 if score > 50 else -5
    elif v.mult < 0.6 and score != 50:
        score = 50 + (score - 50) * 0.7

    return round(max(0, min(100, score)))


def calculate_short_score(t: TrendResult, r: Optional[float],
                          p: PatternResult, v: VolumeResult) -> int:
    """HTML satır 1036. SHORT skoru 0-100 (LONG'un asimetrik tersi)."""
    score = 50.0

    if t.direction == "bear":
        score += 12 + (t.strength * 7)
    elif t.direction == "bull":
        score -= 12 + (t.strength * 7)

    score += SHORT_PATTERN_WEIGHTS.get(p.label, 0)

    if r is not None:
        if r > 80:
            score -= 8       # Aşırı alım, tepki riski
        elif r > 70:
            score += 4
        elif r > 55:
            score -= 5
        elif r >= 45:
            score += 0
        elif r >= 30:
            score += 5
        elif r >= 20:
            score -= 4
        else:
            score -= 14      # Çok aşırı satım — SHORT açma

    if v.mult > 1.5 and score != 50:
        score += 5 if score > 50 else -5
    elif v.mult < 0.6 and score != 50:
        score = 50 + (score - 50) * 0.7

    return round(max(0, min(100, score)))


def analyze_timeframe(timeframe: str, candles: List[Candle]) -> TFAnalysis:
    """Bir timeframe için tam analiz çıkarır."""
    t = detect_trend(candles)
    closes = [c.c for c in candles]
    r = rsi(closes, 14)
    p = detect_pattern(candles)
    v = detect_volume_trend(candles)

    return TFAnalysis(
        timeframe=timeframe,
        long_score=calculate_long_score(t, r, p, v),
        short_score=calculate_short_score(t, r, p, v),
        trend=t,
        rsi=r,
        pattern=p,
        volume=v,
    )


# ──────────────────────────────────────────────────────────────
# Tetikleme kararı (HTML satır 2073, 2193)
# ──────────────────────────────────────────────────────────────
WATCH_SCORE_THRESHOLD = 80


def should_open_long(analyses: Dict[str, TFAnalysis]) -> bool:
    """1m, 3m, 5m üçünün LONG skoru da >= 80 ise tetik."""
    needed = ["1m", "3m", "5m"]
    if not all(tf in analyses for tf in needed):
        return False
    return all(analyses[tf].long_score >= WATCH_SCORE_THRESHOLD for tf in needed)


def should_open_short(analyses: Dict[str, TFAnalysis]) -> bool:
    """1m, 3m, 5m üçünün SHORT skoru da >= 80 ise tetik."""
    needed = ["1m", "3m", "5m"]
    if not all(tf in analyses for tf in needed):
        return False
    return all(analyses[tf].short_score >= WATCH_SCORE_THRESHOLD for tf in needed)
