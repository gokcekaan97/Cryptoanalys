"""
test_signal_engine.py
=====================
Sinyal motorunu sentetik veriyle test eder.
HTML mantığının doğru aktarılıp aktarılmadığını kontrol için.
"""

from signal_engine import (
    Candle, ema, rsi, detect_pattern, detect_trend, detect_volume_trend,
    calculate_long_score, calculate_short_score,
    analyze_timeframe, should_open_long, should_open_short,
)


def test_ema_basic():
    # Sabit seri → EMA = sabit
    assert abs(ema([10.0] * 30, 9) - 10.0) < 1e-6
    print("✓ EMA sabit serisi doğru")


def test_rsi_extremes():
    # Hep yükselen → RSI 100
    closes = [float(i) for i in range(1, 30)]
    assert rsi(closes, 14) == 100.0
    print("✓ RSI sürekli yükseliş = 100")


def test_pattern_bull_engulfing():
    candles = [
        Candle(o=100, h=101, l=98, c=99, v=1000),    # önceki kırmızı
        Candle(o=99, h=104, l=98.5, c=103, v=1500),  # şimdiki büyük yeşil, sarmalıyor
    ]
    p = detect_pattern(candles)
    assert p.label == "Bull Engulfing", f"beklenen Bull Engulfing, gelen {p.label}"
    print("✓ Bull Engulfing tespit ediliyor")


def test_strong_uptrend():
    # 30 mumluk istikrarlı yükseliş
    candles = []
    price = 100.0
    for i in range(30):
        o = price
        c = price * 1.005  # her mum %0.5 yükseliş
        candles.append(Candle(o=o, h=c*1.001, l=o*0.999, c=c, v=1000))
        price = c
    t = detect_trend(candles)
    assert t.direction == "bull"
    assert t.strength == 2, f"beklenen güçlü, gelen {t.strength}"
    print("✓ Güçlü yükseliş trendi yakalandı")


def test_long_score_strong_setup():
    """
    İdeal LONG senaryosu:
      - Güçlü bull trend
      - Bull engulfing pattern
      - RSI 60 (orta-yüksek, aşırı alım değil)
      - Yüksek hacim
    Skor 80+ bekleniyor.
    """
    from signal_engine import TrendResult, PatternResult, VolumeResult
    t = TrendResult("↑ Güçlü Yükseliş", "bull", 2)
    p = PatternResult("Bull Engulfing", "bull")
    v = VolumeResult("🔥 Yüksek", 1.8)
    score = calculate_long_score(t, 60, p, v)
    assert score >= 80, f"beklenen >=80, gelen {score}"
    print(f"✓ İdeal LONG setup → skor={score} (>=80)")


def test_long_score_bearish_setup():
    """Bear trend + bear engulfing → düşük LONG skoru."""
    from signal_engine import TrendResult, PatternResult, VolumeResult
    t = TrendResult("↓ Güçlü Düşüş", "bear", 2)
    p = PatternResult("Bear Engulfing", "bear")
    v = VolumeResult("🔥 Yüksek", 1.8)
    score = calculate_long_score(t, 40, p, v)
    assert score < 30, f"beklenen <30, gelen {score}"
    print(f"✓ Bearish setup'ta LONG skoru düşük → skor={score}")


def test_short_score_strong_setup():
    """İdeal SHORT senaryosu → 80+ bekleniyor."""
    from signal_engine import TrendResult, PatternResult, VolumeResult
    t = TrendResult("↓ Güçlü Düşüş", "bear", 2)
    p = PatternResult("Bear Engulfing", "bear")
    v = VolumeResult("🔥 Yüksek", 1.8)
    score = calculate_short_score(t, 40, p, v)
    assert score >= 80, f"beklenen >=80, gelen {score}"
    print(f"✓ İdeal SHORT setup → skor={score} (>=80)")


def test_short_score_oversold_penalty():
    """RSI çok düşükse (aşırı satım) SHORT skoru cezalandırılmalı."""
    from signal_engine import TrendResult, PatternResult, VolumeResult
    t = TrendResult("↓ Güçlü Düşüş", "bear", 2)
    p = PatternResult("Güçlü Kırmızı", "bear")
    v = VolumeResult("🔥 Yüksek", 1.8)
    score_normal_rsi = calculate_short_score(t, 40, p, v)
    score_oversold = calculate_short_score(t, 15, p, v)
    assert score_oversold < score_normal_rsi, (
        f"aşırı satım SHORT skorunu düşürmeli: normal={score_normal_rsi}, oversold={score_oversold}"
    )
    print(f"✓ Aşırı satım SHORT'u cezalandırıyor (RSI 40→{score_normal_rsi}, RSI 15→{score_oversold})")


def test_trigger_logic():
    """Üçü de >=80 ise tetik, biri düşükse hayır."""
    from signal_engine import TFAnalysis, TrendResult, PatternResult, VolumeResult
    def mk(score):
        return TFAnalysis(
            timeframe="x", long_score=score, short_score=100-score,
            trend=TrendResult("—", "neutral", 0),
            rsi=50, pattern=PatternResult("—", "neutral"),
            volume=VolumeResult("—", 1.0),
        )

    all_high = {"1m": mk(85), "3m": mk(82), "5m": mk(81)}
    assert should_open_long(all_high) is True

    one_low = {"1m": mk(85), "3m": mk(82), "5m": mk(79)}
    assert should_open_long(one_low) is False, "biri 79 ise tetiklenmemeli"
    print("✓ Tetikleme mantığı doğru (üçü de >=80 şartı)")


if __name__ == "__main__":
    test_ema_basic()
    test_rsi_extremes()
    test_pattern_bull_engulfing()
    test_strong_uptrend()
    test_long_score_strong_setup()
    test_long_score_bearish_setup()
    test_short_score_strong_setup()
    test_short_score_oversold_penalty()
    test_trigger_logic()
    print("\n🎉 Tüm testler geçti — sinyal motoru HTML mantığına uygun çalışıyor.")
