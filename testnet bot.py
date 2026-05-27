"""
testnet_bot.py
==============
Crypto3.html sinyal mantığını Binance Futures TESTNET'inde çalıştırır.

ÖNEMLİ:
  - Bu kod SADECE testnet'e bağlanır (testnet.binancefuture.com).
  - Gerçek para riski yoktur, testnet bakiyesi sahte USDT'dir.
  - testnet.binancefuture.com adresinden ücretsiz API key alabilirsin.

KULLANIM:
  1) pip install python-binance pandas
  2) .env dosyasına TESTNET_API_KEY ve TESTNET_API_SECRET koy
  3) python testnet_bot.py

STRATEJİ:
  - Her 60 saniyede top/bottom moverları yenile
  - Her sembol için 1m+3m+5m mum verilerini çek
  - HTML mantığına göre LONG/SHORT skoru hesapla
  - Üçü de >= 80 ise testnet'te pozisyon aç
  - %1 stop-loss, %1.5 take-profit (basit, edit edilebilir)
  - Tüm sinyalleri ve işlemleri CSV'ye logla
"""

import os
import time
import csv
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional
from dataclasses import asdict

from binance.client import Client
from binance.exceptions import BinanceAPIException

from signal_engine import (
    Candle, TFAnalysis,
    analyze_timeframe,
    should_open_long, should_open_short,
    WATCH_SCORE_THRESHOLD,
)


# ──────────────────────────────────────────────────────────────
# AYARLAR
# ──────────────────────────────────────────────────────────────
API_KEY = os.environ.get("TESTNET_API_KEY", "")
API_SECRET = os.environ.get("TESTNET_API_SECRET", "")

TIMEFRAMES = ["1m", "3m", "5m"]
TF_KLINE_LIMIT = 50         # Her TF için son 50 mum (EMA21 + buffer)
TOP_N_MOVERS = 30           # 24h en çok yükselen/düşen kaç tane?
MIN_QUOTE_VOLUME = 1_000_000

LOOP_INTERVAL_SEC = 60      # Her dakikada bir tüm taramayı yap
SCORE_THRESHOLD = WATCH_SCORE_THRESHOLD  # 80

# --- Risk parametreleri (testnet'te bile dikkatli olalım ki gerçek davranışı simüle edelim) ---
LEVERAGE = 3                # Düşük kaldıraç — sadece davranışı görmek için
POSITION_USDT = 50          # Her pozisyon ~50 USDT nominal değer (testnet bakiyesi 10K-15K USDT genelde)
STOP_LOSS_PCT = 0.01        # %1
TAKE_PROFIT_PCT = 0.015     # %1.5
MAX_CONCURRENT_POSITIONS = 5

# --- Dosyalar ---
SIGNAL_LOG = "signals.csv"
TRADE_LOG = "trades.csv"

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("testnet_bot")


# ──────────────────────────────────────────────────────────────
# BINANCE CLIENT (TESTNET)
# ──────────────────────────────────────────────────────────────
def make_client() -> Client:
    """Binance Futures Testnet client'ı."""
    if not API_KEY or not API_SECRET:
        raise RuntimeError(
            "TESTNET_API_KEY ve TESTNET_API_SECRET ortam değişkenleri lazım. "
            "https://testnet.binancefuture.com adresinden alabilirsin."
        )
    client = Client(API_KEY, API_SECRET, testnet=True)
    # Futures testnet endpoint'ini zorla
    client.FUTURES_URL = "https://testnet.binancefuture.com/fapi"
    return client


# ──────────────────────────────────────────────────────────────
# COIN HAVUZU (HTML satır 1677)
# ──────────────────────────────────────────────────────────────
def fetch_movers(client: Client) -> tuple[List[str], List[str]]:
    """24h ticker'dan top/bottom mover listelerini çıkar."""
    tickers = client.futures_ticker()
    usdt_pairs = []
    for t in tickers:
        if not t["symbol"].endswith("USDT"):
            continue
        try:
            qv = float(t["quoteVolume"])
            chg = float(t["priceChangePercent"])
        except (KeyError, ValueError):
            continue
        if qv < MIN_QUOTE_VOLUME:
            continue
        usdt_pairs.append((t["symbol"], chg))

    usdt_pairs.sort(key=lambda x: x[1], reverse=True)
    top = [s for s, _ in usdt_pairs[:TOP_N_MOVERS]]
    bottom = [s for s, c in usdt_pairs if c < 0][-TOP_N_MOVERS:]
    return top, bottom


# ──────────────────────────────────────────────────────────────
# MUM VERİSİ
# ──────────────────────────────────────────────────────────────
def fetch_candles(client: Client, symbol: str, interval: str,
                  limit: int = TF_KLINE_LIMIT) -> List[Candle]:
    """Tek bir symbol/TF için mum verisini Candle listesi olarak çek."""
    klines = client.futures_klines(symbol=symbol, interval=interval, limit=limit)
    return [Candle.from_binance_kline(k) for k in klines]


def analyze_symbol(client: Client, symbol: str) -> Optional[Dict[str, TFAnalysis]]:
    """Bir sembol için 1m+3m+5m tam analiz."""
    try:
        analyses = {}
        for tf in TIMEFRAMES:
            candles = fetch_candles(client, symbol, tf)
            if len(candles) < 22:  # EMA21 için minimum
                return None
            analyses[tf] = analyze_timeframe(tf, candles)
        return analyses
    except BinanceAPIException as e:
        log.warning("API hatası %s: %s", symbol, e)
        return None


# ──────────────────────────────────────────────────────────────
# POZİSYON YÖNETİMİ
# ──────────────────────────────────────────────────────────────
def get_open_positions(client: Client) -> List[dict]:
    """Açık pozisyonları (sıfırdan farklı amount) döndürür."""
    positions = client.futures_position_information()
    return [p for p in positions if float(p["positionAmt"]) != 0]


def round_qty(qty: float, step_size: float) -> float:
    """LOT_SIZE filtresine göre yuvarla."""
    precision = max(0, str(step_size).rstrip("0")[::-1].find(".") if "." in str(step_size) else 0)
    return round(qty - (qty % step_size), precision)


def get_symbol_filters(client: Client, symbol: str) -> Optional[dict]:
    """Sembol için tickSize ve stepSize."""
    info = client.futures_exchange_info()
    for s in info["symbols"]:
        if s["symbol"] != symbol:
            continue
        out = {}
        for f in s["filters"]:
            if f["filterType"] == "LOT_SIZE":
                out["stepSize"] = float(f["stepSize"])
                out["minQty"] = float(f["minQty"])
            elif f["filterType"] == "PRICE_FILTER":
                out["tickSize"] = float(f["tickSize"])
        return out
    return None


def open_position(client: Client, symbol: str, side: str,
                  current_price: float) -> Optional[dict]:
    """
    Testnet'te pozisyon açar + stop-loss ve take-profit emirleri koyar.
    side: 'BUY' (long) veya 'SELL' (short)
    """
    try:
        # Kaldıraç ayarla
        client.futures_change_leverage(symbol=symbol, leverage=LEVERAGE)

        filters = get_symbol_filters(client, symbol)
        if not filters:
            log.warning("Filter bilgisi yok: %s", symbol)
            return None

        # Miktar hesabı
        notional = POSITION_USDT * LEVERAGE
        raw_qty = notional / current_price
        qty = round_qty(raw_qty, filters["stepSize"])
        if qty < filters["minQty"]:
            log.warning("Qty min altında %s: %s < %s", symbol, qty, filters["minQty"])
            return None

        # Ana emir (market)
        order = client.futures_create_order(
            symbol=symbol,
            side=side,
            type="MARKET",
            quantity=qty,
        )

        # SL/TP fiyatları
        tick = filters["tickSize"]
        if side == "BUY":
            sl_price = round_qty(current_price * (1 - STOP_LOSS_PCT), tick)
            tp_price = round_qty(current_price * (1 + TAKE_PROFIT_PCT), tick)
            close_side = "SELL"
        else:
            sl_price = round_qty(current_price * (1 + STOP_LOSS_PCT), tick)
            tp_price = round_qty(current_price * (1 - TAKE_PROFIT_PCT), tick)
            close_side = "BUY"

        # Stop-loss (STOP_MARKET, reduceOnly)
        client.futures_create_order(
            symbol=symbol, side=close_side, type="STOP_MARKET",
            stopPrice=sl_price, closePosition=True, timeInForce="GTC",
        )
        # Take-profit (TAKE_PROFIT_MARKET, reduceOnly)
        client.futures_create_order(
            symbol=symbol, side=close_side, type="TAKE_PROFIT_MARKET",
            stopPrice=tp_price, closePosition=True, timeInForce="GTC",
        )

        log.info("✅ %s %s @ %.6f | qty=%s | SL=%.6f | TP=%.6f",
                 side, symbol, current_price, qty, sl_price, tp_price)

        return {
            "symbol": symbol, "side": side, "qty": qty,
            "entry": current_price, "sl": sl_price, "tp": tp_price,
            "order_id": order.get("orderId"),
        }
    except BinanceAPIException as e:
        log.error("Pozisyon açılamadı %s: %s", symbol, e)
        return None


# ──────────────────────────────────────────────────────────────
# LOGGING (CSV)
# ──────────────────────────────────────────────────────────────
def init_csv():
    """CSV başlıklarını oluşturur (yoksa)."""
    if not os.path.exists(SIGNAL_LOG):
        with open(SIGNAL_LOG, "w", newline="") as f:
            csv.writer(f).writerow([
                "ts", "symbol", "side",
                "score_1m", "score_3m", "score_5m",
                "rsi_1m", "rsi_3m", "rsi_5m",
                "trend_1m", "trend_3m", "trend_5m",
                "pattern_1m", "pattern_3m", "pattern_5m",
                "vol_mult_1m", "vol_mult_3m", "vol_mult_5m",
                "triggered",
            ])
    if not os.path.exists(TRADE_LOG):
        with open(TRADE_LOG, "w", newline="") as f:
            csv.writer(f).writerow([
                "ts", "symbol", "side", "qty", "entry", "sl", "tp", "order_id",
            ])


def log_signal(symbol: str, side: str, a: Dict[str, TFAnalysis], triggered: bool):
    with open(SIGNAL_LOG, "a", newline="") as f:
        csv.writer(f).writerow([
            datetime.now(timezone.utc).isoformat(),
            symbol, side,
            a["1m"].long_score if side == "LONG" else a["1m"].short_score,
            a["3m"].long_score if side == "LONG" else a["3m"].short_score,
            a["5m"].long_score if side == "LONG" else a["5m"].short_score,
            a["1m"].rsi, a["3m"].rsi, a["5m"].rsi,
            a["1m"].trend.label, a["3m"].trend.label, a["5m"].trend.label,
            a["1m"].pattern.label, a["3m"].pattern.label, a["5m"].pattern.label,
            round(a["1m"].volume.mult, 2), round(a["3m"].volume.mult, 2), round(a["5m"].volume.mult, 2),
            triggered,
        ])


def log_trade(result: dict):
    with open(TRADE_LOG, "a", newline="") as f:
        csv.writer(f).writerow([
            datetime.now(timezone.utc).isoformat(),
            result["symbol"], result["side"], result["qty"],
            result["entry"], result["sl"], result["tp"], result["order_id"],
        ])


# ──────────────────────────────────────────────────────────────
# ANA DÖNGÜ
# ──────────────────────────────────────────────────────────────
def main_loop(client: Client):
    log.info("🚀 Testnet bot başladı (eşik=%s, kaldıraç=%sx, poz=%s USDT)",
             SCORE_THRESHOLD, LEVERAGE, POSITION_USDT)
    init_csv()

    # Pozisyon var mı diye kontrol için sembolleri takip ediyoruz
    open_symbols: set[str] = set()

    while True:
        try:
            # 1) Açık pozisyonları senkronize et
            positions = get_open_positions(client)
            open_symbols = {p["symbol"] for p in positions}
            log.info("📊 Açık pozisyon: %s adet (%s)",
                     len(open_symbols), ", ".join(sorted(open_symbols)) or "—")

            # 2) Coin havuzunu yenile
            top, bottom = fetch_movers(client)
            log.info("🔄 Top %s LONG adayı, Bottom %s SHORT adayı taranıyor",
                     len(top), len(bottom))

            # 3) LONG taraması
            for symbol in top:
                if symbol in open_symbols:
                    continue
                if len(open_symbols) >= MAX_CONCURRENT_POSITIONS:
                    log.info("⏸ Max pozisyon sayısına ulaşıldı, yeni LONG aranmıyor")
                    break

                analyses = analyze_symbol(client, symbol)
                if analyses is None:
                    continue

                triggered = should_open_long(analyses)
                log_signal(symbol, "LONG", analyses, triggered)

                if triggered:
                    scores = [analyses[tf].long_score for tf in TIMEFRAMES]
                    log.info("🎯 LONG sinyali: %s | skor=%s", symbol, scores)
                    price = float(client.futures_mark_price(symbol=symbol)["markPrice"])
                    result = open_position(client, symbol, "BUY", price)
                    if result:
                        log_trade(result)
                        open_symbols.add(symbol)

                time.sleep(0.15)  # Rate limit'e nazik

            # 4) SHORT taraması
            for symbol in bottom:
                if symbol in open_symbols:
                    continue
                if len(open_symbols) >= MAX_CONCURRENT_POSITIONS:
                    log.info("⏸ Max pozisyon sayısına ulaşıldı, yeni SHORT aranmıyor")
                    break

                analyses = analyze_symbol(client, symbol)
                if analyses is None:
                    continue

                triggered = should_open_short(analyses)
                log_signal(symbol, "SHORT", analyses, triggered)

                if triggered:
                    scores = [analyses[tf].short_score for tf in TIMEFRAMES]
                    log.info("🎯 SHORT sinyali: %s | skor=%s", symbol, scores)
                    price = float(client.futures_mark_price(symbol=symbol)["markPrice"])
                    result = open_position(client, symbol, "SELL", price)
                    if result:
                        log_trade(result)
                        open_symbols.add(symbol)

                time.sleep(0.15)

            log.info("💤 %s saniye bekleniyor...\n", LOOP_INTERVAL_SEC)
            time.sleep(LOOP_INTERVAL_SEC)

        except KeyboardInterrupt:
            log.info("👋 Bot durduruluyor (Ctrl+C)")
            break
        except Exception as e:
            log.exception("Beklenmedik hata: %s", e)
            time.sleep(10)


if __name__ == "__main__":
    client = make_client()
    # Bağlantı testi
    try:
        balance = client.futures_account_balance()
        usdt = next((b for b in balance if b["asset"] == "USDT"), None)
        if usdt:
            log.info("💰 Testnet bakiyesi: %s USDT", usdt["balance"])
    except Exception as e:
        log.error("Testnet bağlantısı kurulamadı: %s", e)
        raise

    main_loop(client)
