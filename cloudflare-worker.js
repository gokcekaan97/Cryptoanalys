// Cloudflare Worker - Binance Futures Proxy
// Türkiye'den fapi.binance.com'a CORS açık ve engellemesiz erişim

export default {
  async fetch(request) {
    const url = new URL(request.url);

    // CORS preflight için
    if (request.method === 'OPTIONS') {
      return new Response(null, {
        headers: {
          'Access-Control-Allow-Origin': '*',
          'Access-Control-Allow-Methods': 'GET, OPTIONS',
          'Access-Control-Allow-Headers': '*',
          'Access-Control-Max-Age': '86400',
        }
      });
    }

    // /fapi/* yollarını fapi.binance.com'a yönlendir
    // /api/* yollarını api.binance.com'a yönlendir
    let target;
    if (url.pathname.startsWith('/fapi/')) {
      target = 'https://fapi.binance.com' + url.pathname + url.search;
    } else if (url.pathname.startsWith('/api/')) {
      target = 'https://api.binance.com' + url.pathname + url.search;
    } else {
      return new Response(JSON.stringify({
        ok: true,
        usage: 'GET /fapi/v1/klines?symbol=BTCUSDT&interval=5m  or  /api/v3/...'
      }), {
        headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' }
      });
    }

    try {
      const upstream = await fetch(target, {
        headers: { 'User-Agent': 'Mozilla/5.0 BinanceProxy/1.0' }
      });
      const body = await upstream.text();
      return new Response(body, {
        status: upstream.status,
        headers: {
          'Content-Type': upstream.headers.get('Content-Type') || 'application/json',
          'Access-Control-Allow-Origin': '*',
          'Cache-Control': 'no-store',
        }
      });
    } catch (e) {
      return new Response(JSON.stringify({ error: e.message }), {
        status: 502,
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*'
        }
      });
    }
  }
};
