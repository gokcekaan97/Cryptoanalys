# Crypto3 Testnet Bot

Crypto3.html’deki sinyal mantığını **Binance Futures Testnet**’inde çalıştıran Python botu.

## Çok önemli — bunu okumadan kullanma

- **Sadece testnet.** Bu kod canlı Binance hesabına bağlanmaz. `testnet=True` zorla set edilmiş.
- **Sahte para.** Testnet bakiyesi gerçek değil. Hesabını açtığında 15.000 USDT testnet bakiyesi gelir.
- **Amaç edge ölçmek.** Birkaç hafta çalıştırıp gerçekten kâr ediyor mu, hangi koşullarda zarar ediyor onu görmek için.
- **Canlıya geçişi sen karar verirsin.** Bu kod bilerek `testnet=True` ile kilitli. Canlıya geçirmeden önce backtesting yap, slippage hesapla, position sizing’i tekrar düşün — ve o adımı kendi sorumluluğunda al.

## Kurulum (5 dakika)

### 1. API key al

1. <https://testnet.binancefuture.com> adresine git
1. Sağ üstten Google/GitHub ile giriş yap → otomatik 15.000 USDT testnet bakiyesi gelir
1. Sağ üstte profil → **API Key** → key ve secret’ı kopyala

### 2. Bağımlılıklar

```bash
pip install python-binance
```

### 3. API anahtarlarını ortam değişkenine koy

```bash
# macOS/Linux
export TESTNET_API_KEY="..."
export TESTNET_API_SECRET="..."

# veya .env dosyası kullanmak istersen python-dotenv ekle
```

### 4. Önce sinyal motorunu test et

```bash
python test_signal_engine.py
```

Tüm testler ✓ olmalı.

### 5. Botu başlat

```bash
python testnet_bot.py
```

Bot şunu yapacak:

- Her dakika top 30 yükselen + 30 düşen USDT pariteyi tarar
- Her sembol için 1m+3m+5m skorları hesaplar
- Üçü de ≥80 ise testnet’te pozisyon açar (3x kaldıraç, 50 USDT nominal)
- Otomatik %1 stop-loss + %1.5 take-profit emirleri koyar
- Her şeyi `signals.csv` ve `trades.csv` dosyalarına yazar

## Bir kaç hafta sonra analiz

`signals.csv` ve `trades.csv`’yi alıp şunlara bakacaksın:

- Kaç sinyal tetiklendi? Kaçı kâr, kaçı zarar?
- LONG mu SHORT mu daha çok kazandırdı?
- Hangi RSI bölgesinde tetiklenen sinyaller daha iyi performans gösterdi?
- Hangi pattern’ler false signal verdi?
- Win rate × ortalama R/R = pozitif mi negatif mi?

Bu analiz olmadan canlıya geçmek **kumar**. Bir cümle ile özetleyelim:

> Testnet’te 100+ işlemde net pozitif değilse, canlıda kesinlikle pozitif olmayacak (çünkü canlıda slippage, funding fee, spread var).

## HTML sinyal mantığının zayıf yönleri (tekrar)

1. **Momentum trap**: zaten en çok yükselenleri LONG’luyor → tepeye yakın giriş
1. **Backward-looking indikatörler**: 3 TF de >=80 olduğunda hareket bitmiş olabilir
1. **TF korelasyonu**: 1m/3m/5m bağımsız değil, “üçü de >=80” göründüğü kadar güçlü değil
1. **Hacim baseline çok kısa**: 6 mum yeterli değil
1. **SL/TP optimize edilmemiş**: ben %1/%1.5 koydum, bu keyfi, ATR bazlı olmalı

## Dosya yapısı

```
testnet_bot/
├── signal_engine.py        # HTML'deki sinyal mantığının Python karşılığı
├── testnet_bot.py          # Binance Testnet bağlantısı + emir yönetimi
├── test_signal_engine.py   # Birim testleri
├── signals.csv             # (çalışınca oluşur) tüm üretilen sinyaller
└── trades.csv              # (çalışınca oluşur) açılan testnet pozisyonları
```