"""
High-availability Cryptocurrency Market Data and Trading Intelligence Client.
Provides deterministic, multi-source resilience (Binance, Bybit, OKX, KuCoin)
with strict error sanitization and zero upstream HTML leakage.
"""

import json
import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional, List, Tuple, Dict, Any
from trading.models import (
    PriceTicker,
    Ticker24h,
    OrderBookDepth,
    Candle,
    TechnicalAnalysisSummary,
    MarketStructureSummary,
    MultiTimeframeSummary,
    TradeSetupEvaluation,
    MarketState,
)

logger = logging.getLogger("worker.trading.market")

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

BINANCE_HOSTS = [
    "https://api.binance.com",
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com",
    "https://data-api.binance.vision",
    "https://api.binance.us",
]


class BinanceAPIError(Exception):
    """Custom exception for Market / Binance API errors."""
    def __init__(self, message: str, status_code: Optional[int] = None, error_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code


def handle_binance_error_response(status: int, resp_text: str) -> None:
    """
    Deterministically sanitizes and handles HTTP error responses.
    Guarantees raw upstream HTML/error bodies (CloudFront, Cloudflare, Ray IDs, etc.)
    never leak into exceptions, logs, Telegram, or Gemini context.
    """
    if status == 429:
        raise BinanceAPIError("Rate limit reached (HTTP 429).", status_code=429)
    if status == 418:
        raise BinanceAPIError("IP temporarily banned by Binance (HTTP 418).", status_code=418)

    error_code = None
    if resp_text and isinstance(resp_text, str):
        trimmed = resp_text.strip()
        if trimmed.startswith("{") and trimmed.endswith("}"):
            try:
                err_json = json.loads(trimmed)
                if isinstance(err_json, dict):
                    raw_code = err_json.get("code") or err_json.get("retCode")
                    if isinstance(raw_code, (int, float)):
                        error_code = int(raw_code)
                    elif isinstance(raw_code, str) and (raw_code.isdigit() or (raw_code.startswith("-") and raw_code[1:].isdigit())):
                        error_code = int(raw_code)
            except Exception:
                pass

    if error_code is not None:
        raise BinanceAPIError(f"Binance returned error status {status} (code {error_code}).", status_code=status, error_code=error_code)

    raise BinanceAPIError(f"Binance returned error status {status}.", status_code=status)


class BinanceClient:
    """
    Resilient Cryptocurrency Spot REST client with multi-exchange fallback
    (Binance Primary Cluster + Bybit + OKX + KuCoin secondary fallbacks).
    """
    BASE_URL = "https://data-api.binance.vision"

    def __init__(self, http_fetch_fn):
        self.fetch_fn = http_fetch_fn

    @staticmethod
    def normalize_symbol(raw_symbol: str) -> str:
        """
        Normalizes and strictly validates cryptocurrency trading pair symbols.
        Converts to uppercase alphanumeric. Appends USDT if single coin ticker (e.g. BTC -> BTCUSDT).
        """
        cleaned = raw_symbol.strip().upper().replace("/", "").replace("-", "").replace("_", "")
        if not cleaned.isalnum():
            raise ValueError(f"Invalid symbol {raw_symbol}: Symbol must contain only alphanumeric characters.")
        if len(cleaned) < 2 or len(cleaned) > 20:
            raise ValueError(f"Invalid symbol {raw_symbol}: Symbol length must be between 2 and 20 characters.")
        
        if cleaned == "USDT":
            return "USDT"

        major_coins = (
            "BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT",
            "NEAR", "SUI", "APT", "MATIC", "LTC", "PEPE", "SHIB", "TRX", "TON",
            "BCH", "UNI", "XLM", "ICP", "ETC", "FIL", "HBAR", "RENDER", "ATOM", "TAO"
        )
        if cleaned in major_coins:
            return f"{cleaned}USDT"
            
        return cleaned

    @staticmethod
    def _split_base_quote(symbol: str) -> Tuple[str, str]:
        sym = symbol.upper()
        for q in ("USDT", "USDC", "FDUSD", "BUSD", "USD", "EUR", "BTC", "ETH"):
            if sym.endswith(q) and len(sym) > len(q):
                return sym[:-len(q)], q
        return sym, "USDT"

    async def _safe_fetch(self, url: str, headers: Optional[dict] = None):
        h = dict(DEFAULT_HEADERS)
        if headers:
            h.update(headers)
        return await self.fetch_fn(url, method="GET", headers=h)

    async def get_price(self, symbol: str) -> PriceTicker:
        """Fetches the latest spot price with multi-endpoint & multi-exchange fallback."""
        norm_symbol = self.normalize_symbol(symbol)
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Special handling for USDT stablecoin peg
        if norm_symbol == "USDT":
            return PriceTicker(symbol="USDT", price=1.0000, timestamp=now_iso, source="Tether USD Peg")

        last_error = None

        # 1. Try Binance endpoints cluster
        for base in BINANCE_HOSTS:
            url = f"{base}/api/v3/ticker/price?symbol={norm_symbol}"
            try:
                resp = await self._safe_fetch(url)
                status = getattr(resp, "status", 200)
                resp_text = await resp.text()

                if status == 200:
                    try:
                        data = json.loads(resp_text)
                    except Exception:
                        raise BinanceAPIError("Malformed response received from Binance API.")

                    if isinstance(data, dict) and "price" in data:
                        return PriceTicker(
                            symbol=data.get("symbol", norm_symbol),
                            price=float(data["price"]),
                            timestamp=now_iso,
                            source="Binance Spot"
                        )
                    raise BinanceAPIError("Malformed response received from Binance API.")
                elif status >= 400:
                    try:
                        handle_binance_error_response(status, resp_text)
                    except BinanceAPIError as be:
                        last_error = be
                        if status in (400, 429, 418):
                            raise
            except BinanceAPIError as be:
                last_error = be
                if be.status_code in (400, 429, 418) or "Malformed" in str(be):
                    raise
            except Exception as e:
                logger.warning(f"Binance host {base} price request failed: {e}")
                last_error = e

        # 2. Fallback: Bybit Spot
        try:
            bybit_url = f"https://api.bybit.com/v5/market/tickers?category=spot&symbol={norm_symbol}"
            resp = await self._safe_fetch(bybit_url)
            if getattr(resp, "status", 200) == 200:
                data = json.loads(await resp.text())\n                if data.get("retCode") == 0:
                    items = data.get("result", {}).get("list", [])
                    if items and "lastPrice" in items[0]:
                        return PriceTicker(
                            symbol=norm_symbol,
                            price=float(items[0]["lastPrice"]),
                            timestamp=now_iso,
                            source="Bybit Spot"
                        )
        except Exception as e:
            logger.warning(f"Bybit price fallback failed: {e}")

        # 3. Fallback: OKX Spot
        try:
            base_coin, quote_coin = self._split_base_quote(norm_symbol)
            okx_inst = f"{base_coin}-{quote_coin}"
            okx_url = f"https://www.okx.com/api/v5/market/ticker?instId={okx_inst}"
            resp = await self._safe_fetch(okx_url)
            if getattr(resp, "status", 200) == 200:
                data = json.loads(await resp.text())
                if data.get("code") == "0" and data.get("data"):
                    return PriceTicker(
                        symbol=norm_symbol,
                        price=float(data["data"][0]["last"]),
                        timestamp=now_iso,
                        source="OKX Spot"
                    )
        except Exception as e:
            logger.warning(f"OKX price fallback failed: {e}")

        # 4. Fallback: KuCoin Spot
        try:
            base_coin, quote_coin = self._split_base_quote(norm_symbol)
            ku_sym = f"{base_coin}-{quote_coin}"
            ku_url = f"https://api.kucoin.com/api/v1/market/orderbook/level1?symbol={ku_sym}"
            resp = await self._safe_fetch(ku_url)
            if getattr(resp, "status", 200) == 200:
                data = json.loads(await resp.text())
                if data.get("code") == "200000" and data.get("data") and "price" in data["data"]:
                    return PriceTicker(
                        symbol=norm_symbol,
                        price=float(data["data"]["price"]),
                        timestamp=now_iso,
                        source="KuCoin Spot"
                    )
        except Exception as e:
            logger.warning(f"KuCoin price fallback failed: {e}")

        if isinstance(last_error, BinanceAPIError):
            raise last_error
        raise BinanceAPIError("Failed to retrieve market price from exchange feeds.")

    async def get_24h_ticker(self, symbol: str) -> Ticker24h:
        """Fetches 24-hour rolling statistics with multi-exchange fallback."""
        norm_symbol = self.normalize_symbol(symbol)
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Special handling for USDT
        if norm_symbol == "USDT":
            return Ticker24h(
                symbol="USDT",
                last_price=1.0000,
                price_change=0.0,
                price_change_percent=0.0,
                high_price=1.0005,
                low_price=0.9995,
                volume=100000000.0,
                quote_volume=100000000.0,
                timestamp=now_iso,
                source="Tether USD Peg"
            )

        last_error = None

        # 1. Try Binance endpoints cluster
        for base in BINANCE_HOSTS:
            url = f"{base}/api/v3/ticker/24hr?symbol={norm_symbol}"
            try:
                resp = await self._safe_fetch(url)
                status = getattr(resp, "status", 200)
                resp_text = await resp.text()

                if status == 200:
                    try:
                        data = json.loads(resp_text)
                    except Exception:
                        raise BinanceAPIError("Malformed response received from Binance API.")

                    if isinstance(data, dict) and "lastPrice" in data:
                        return Ticker24h(
                            symbol=data.get("symbol", norm_symbol),
                            last_price=float(data["lastPrice"]),
                            price_change=float(data.get("priceChange", 0.0)),
                            price_change_percent=float(data.get("priceChangePercent", 0.0)),
                            high_price=float(data.get("highPrice", 0.0)),
                            low_price=float(data.get("lowPrice", 0.0)),
                            volume=float(data.get("volume", 0.0)),
                            quote_volume=float(data.get("quoteVolume", 0.0)),
                            timestamp=now_iso,
                            source="Binance Spot"
                        )
                    raise BinanceAPIError("Malformed response received from Binance API.")
                elif status >= 400:
                    try:
                        handle_binance_error_response(status, resp_text)
                    except BinanceAPIError as be:
                        last_error = be
                        if status in (400, 429, 418):
                            raise
            except BinanceAPIError as be:
                last_error = be
                if be.status_code in (400, 429, 418) or "Malformed" in str(be):
                    raise
            except Exception as e:
                logger.warning(f"Binance host {base} 24h ticker failed: {e}")
                last_error = e

        # 2. Fallback: Bybit Spot
        try:
            bybit_url = f"https://api.bybit.com/v5/market/tickers?category=spot&symbol={norm_symbol}"
            resp = await self._safe_fetch(bybit_url)
            if getattr(resp, "status", 200) == 200:
                data = json.loads(await resp.text())
                if data.get("retCode") == 0:
                    items = data.get("result", {}).get("list", [])
                    if items:
                        item = items[0]
                        last_p = float(item["lastPrice"])
                        high_p = float(item.get("highPrice24h", last_p))
                        low_p = float(item.get("lowPrice24h", last_p))
                        pcnt = float(item.get("price24hPcnt", 0.0)) * 100.0
                        prev_p = float(item.get("prevPrice24h", last_p))
                        p_change = last_p - prev_p
                        vol = float(item.get("volume24h", 0.0))
                        q_vol = float(item.get("turnover24h", 0.0))
                        return Ticker24h(
                            symbol=norm_symbol,
                            last_price=last_p,
                            price_change=p_change,
                            price_change_percent=pcnt,
                            high_price=high_p,
                            low_price=low_p,
                            volume=vol,
                            quote_volume=q_vol,
                            timestamp=now_iso,
                            source="Bybit Spot"
                        )
        except Exception as e:
            logger.warning(f"Bybit 24h ticker fallback failed: {e}")

        # 3. Fallback: OKX Spot
        try:
            base_coin, quote_coin = self._split_base_quote(norm_symbol)
            okx_inst = f"{base_coin}-{quote_coin}"
            okx_url = f"https://www.okx.com/api/v5/market/ticker?instId={okx_inst}"
            resp = await self._safe_fetch(okx_url)
            if getattr(resp, "status", 200) == 200:
                data = json.loads(await resp.text())
                if data.get("code") == "0" and data.get("data"):
                    item = data["data"][0]
                    last_p = float(item["last"])
                    open_p = float(item.get("open24h", last_p))
                    p_change = last_p - open_p
                    pcnt = (p_change / open_p * 100.0) if open_p else 0.0
                    return Ticker24h(
                        symbol=norm_symbol,
                        last_price=last_p,
                        price_change=p_change,
                        price_change_percent=pcnt,
                        high_price=float(item.get("high24h", last_p)),
                        low_price=float(item.get("low24h", last_p)),
                        volume=float(item.get("vol24h", 0.0)),
                        quote_volume=float(item.get("volCcy24h", 0.0)),
                        timestamp=now_iso,
                        source="OKX Spot"
                    )
        except Exception as e:
            logger.warning(f"OKX 24h ticker fallback failed: {e}")

        # 4. Fallback: KuCoin Spot
        try:
            base_coin, quote_coin = self._split_base_quote(norm_symbol)
            ku_sym = f"{base_coin}-{quote_coin}"
            ku_url = f"https://api.kucoin.com/api/v1/market/stats?symbol={ku_sym}"
            resp = await self._safe_fetch(ku_url)
            if getattr(resp, "status", 200) == 200:
                data = json.loads(await resp.text())
                if data.get("code") == "200000" and data.get("data"):
                    item = data["data"]
                    last_p = float(item.get("last", 0.0))
                    change_rate = float(item.get("changeRate", 0.0))
                    p_change = float(item.get("changePrice", 0.0))
                    return Ticker24h(
                        symbol=norm_symbol,
                        last_price=last_p,
                        price_change=p_change,
                        price_change_percent=change_rate * 100.0,
                        high_price=float(item.get("high", last_p)),
                        low_price=float(item.get("low", last_p)),
                        volume=float(item.get("vol", 0.0)),
                        quote_volume=float(item.get("volValue", 0.0)),
                        timestamp=now_iso,
                        source="KuCoin Spot"
                    )
        except Exception as e:
            logger.warning(f"KuCoin 24h ticker fallback failed: {e}")

        if isinstance(last_error, BinanceAPIError):
            raise last_error
        raise BinanceAPIError("Failed to retrieve 24h ticker from exchange feeds.")

    async def get_order_book_depth(self, symbol: str, limit: int = 5) -> OrderBookDepth:
        """Fetches order book depth with multi-exchange fallback."""
        norm_symbol = self.normalize_symbol(symbol)
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Special handling for USDT
        if norm_symbol == "USDT":
            return OrderBookDepth(
                symbol="USDT",
                bids=[(1.0000, 1000000.0), (0.9999, 2000000.0)],
                asks=[(1.0001, 1000000.0), (1.0002, 2000000.0)],
                best_bid=1.0000,
                best_ask=1.0001,
                spread=0.0001,
                spread_percentage=0.01,
                timestamp=now_iso,
                source="Tether USD Peg"
            )

        last_error = None

        # 1. Try Binance endpoints cluster
        for base in BINANCE_HOSTS:
            url = f"{base}/api/v3/depth?symbol={norm_symbol}&limit={limit}"
            try:
                resp = await self._safe_fetch(url)
                status = getattr(resp, "status", 200)
                resp_text = await resp.text()

                if status == 200:
                    try:
                        data = json.loads(resp_text)
                    except Exception:
                        raise BinanceAPIError("Malformed response received from Binance API.")

                    raw_bids = data.get("bids", [])
                    raw_asks = data.get("asks", [])

                    bids = [(float(b[0]), float(b[1])) for b in raw_bids[:limit]]
                    asks = [(float(a[0]), float(a[1])) for a in raw_asks[:limit]]

                    best_bid = bids[0][0] if bids else 0.0
                    best_ask = asks[0][0] if asks else 0.0
                    spread = max(0.0, best_ask - best_bid) if (best_bid and best_ask) else 0.0
                    spread_pct = (spread / best_ask * 100.0) if best_ask else 0.0

                    return OrderBookDepth(
                        symbol=norm_symbol,
                        bids=bids,
                        asks=asks,
                        best_bid=best_bid,
                        best_ask=best_ask,
                        spread=spread,
                        spread_percentage=spread_pct,
                        timestamp=now_iso,
                        source="Binance Order Book"
                    )
                elif status >= 400:
                    try:
                        handle_binance_error_response(status, resp_text)
                    except BinanceAPIError as be:
                        last_error = be
                        if status in (400, 429, 418):
                            raise
            except BinanceAPIError as be:
                last_error = be
                if be.status_code in (400, 429, 418) or "Malformed" in str(be):
                    raise
            except Exception as e:
                logger.warning(f"Binance host {base} depth failed: {e}")
                last_error = e

        # 2. Fallback: Bybit Spot
        try:
            bybit_url = f"https://api.bybit.com/v5/market/orderbook?category=spot&symbol={norm_symbol}&limit={limit}"
            resp = await self._safe_fetch(bybit_url)
            if getattr(resp, "status", 200) == 200:
                data = json.loads(await resp.text())
                if data.get("retCode") == 0 and "result" in data:
                    res = data["result"]
                    bids = [(float(b[0]), float(b[1])) for b in res.get("b", [])[:limit]]
                    asks = [(float(a[0]), float(a[1])) for a in res.get("a", [])[:limit]]
                    best_bid = bids[0][0] if bids else 0.0
                    best_ask = asks[0][0] if asks else 0.0
                    spread = max(0.0, best_ask - best_bid) if (best_bid and best_ask) else 0.0
                    spread_pct = (spread / best_ask * 100.0) if best_ask else 0.0
                    return OrderBookDepth(
                        symbol=norm_symbol,
                        bids=bids,
                        asks=asks,
                        best_bid=best_bid,
                        best_ask=best_ask,
                        spread=spread,
                        spread_percentage=spread_pct,
                        timestamp=now_iso,
                        source="Bybit Order Book"
                    )
        except Exception as e:
            logger.warning(f"Bybit depth fallback failed: {e}")

        # 3. Fallback: OKX Spot
        try:
            base_coin, quote_coin = self._split_base_quote(norm_symbol)
            okx_inst = f"{base_coin}-{quote_coin}"
            okx_url = f"https://www.okx.com/api/v5/market/books?instId={okx_inst}&sz={limit}"
            resp = await self._safe_fetch(okx_url)
            if getattr(resp, "status", 200) == 200:
                data = json.loads(await resp.text())
                if data.get("code") == "0" and data.get("data"):
                    res = data["data"][0]
                    bids = [(float(b[0]), float(b[1])) for b in res.get("bids", [])[:limit]]
                    asks = [(float(a[0]), float(a[1])) for a in res.get("asks", [])[:limit]]
                    best_bid = bids[0][0] if bids else 0.0
                    best_ask = asks[0][0] if asks else 0.0
                    spread = max(0.0, best_ask - best_bid) if (best_bid and best_ask) else 0.0
                    spread_pct = (spread / best_ask * 100.0) if best_ask else 0.0
                    return OrderBookDepth(
                        symbol=norm_symbol,
                        bids=bids,
                        asks=asks,
                        best_bid=best_bid,
                        best_ask=best_ask,
                        spread=spread,
                        spread_percentage=spread_pct,
                        timestamp=now_iso,
                        source="OKX Order Book"
                    )
        except Exception as e:
            logger.warning(f"OKX depth fallback failed: {e}")

        # 4. Fallback: KuCoin Spot
        try:
            base_coin, quote_coin = self._split_base_quote(norm_symbol)
            ku_sym = f"{base_coin}-{quote_coin}"
            ku_url = f"https://api.kucoin.com/api/v1/market/orderbook/level2_20?symbol={ku_sym}"
            resp = await self._safe_fetch(ku_url)
            if getattr(resp, "status", 200) == 200:
                data = json.loads(await resp.text())
                if data.get("code") == "200000" and data.get("data"):
                    res = data["data"]
                    bids = [(float(b[0]), float(b[1])) for b in res.get("bids", [])[:limit]]
                    asks = [(float(a[0]), float(a[1])) for a in res.get("asks", [])[:limit]]
                    best_bid = bids[0][0] if bids else 0.0
                    best_ask = asks[0][0] if asks else 0.0
                    spread = max(0.0, best_ask - best_bid) if (best_bid and best_ask) else 0.0
                    spread_pct = (spread / best_ask * 100.0) if best_ask else 0.0
                    return OrderBookDepth(
                        symbol=norm_symbol,
                        bids=bids,
                        asks=asks,
                        best_bid=best_bid,
                        best_ask=best_ask,
                        spread=spread,
                        spread_percentage=spread_pct,
                        timestamp=now_iso,
                        source="KuCoin Order Book"
                    )
        except Exception as e:
            logger.warning(f"KuCoin depth fallback failed: {e}")

        if isinstance(last_error, BinanceAPIError):
            raise last_error
        raise BinanceAPIError("Failed to retrieve order book depth from exchange feeds.")

    async def get_klines(self, symbol: str, interval: str = "1h", limit: int = 50) -> List[Candle]:
        """Fetches historical OHLCV candlestick data with multi-exchange fallback."""
        norm_symbol = self.normalize_symbol(symbol)
        valid_intervals = ("15m", "1h", "4h", "1d", "1w")
        if interval not in valid_intervals:
            interval = "1h"
        limit = max(10, min(100, limit))

        # Special handling for USDT
        if norm_symbol == "USDT":
            now_ts = int(datetime.now(timezone.utc).timestamp())
            candles = []
            for i in range(limit):
                t = now_ts - (limit - i) * 3600
                candles.append(Candle(
                    open_time=t * 1000,
                    open=1.0,
                    high=1.0005,
                    low=0.9995,
                    close=1.0,
                    volume=1000000.0,
                    close_time=(t + 3600) * 1000 - 1
                ))
            return candles

        last_error = None

        # 1. Try Binance endpoints cluster
        for base in BINANCE_HOSTS:
            url = f"{base}/api/v3/klines?symbol={norm_symbol}&interval={interval}&limit={limit}"
            try:
                resp = await self._safe_fetch(url)
                status = getattr(resp, "status", 200)
                resp_text = await resp.text()

                if status == 200:
                    try:
                        raw_data = json.loads(resp_text)
                    except Exception:
                        raise BinanceAPIError("Malformed response received from Binance klines API.")

                    if isinstance(raw_data, list) and len(raw_data) > 0:
                        candles = []
                        for k in raw_data:
                            candles.append(Candle(
                                open_time=int(k[0]),
                                open=float(k[1]),
                                high=float(k[2]),
                                low=float(k[3]),
                                close=float(k[4]),
                                volume=float(k[5]),
                                close_time=int(k[6])
                            ))
                        return candles
                elif status >= 400:
                    try:
                        handle_binance_error_response(status, resp_text)
                    except BinanceAPIError as be:
                        last_error = be
                        if status in (400, 429, 418):
                            raise
            except BinanceAPIError as be:
                last_error = be
                if be.status_code in (400, 429, 418):
                    raise
            except Exception as e:
                logger.warning(f"Binance host {base} klines failed: {e}")
                last_error = e

        # 2. Fallback: Bybit Spot Klines
        try:
            bybit_intervals = {"15m": "15", "1h": "60", "4h": "240", "1d": "D", "1w": "W"}
            b_int = bybit_intervals.get(interval, "60")
            bybit_url = f"https://api.bybit.com/v5/market/kline?category=spot&symbol={norm_symbol}&interval={b_int}&limit={limit}"
            resp = await self._safe_fetch(bybit_url)
            if getattr(resp, "status", 200) == 200:
                data = json.loads(await resp.text())
                if data.get("retCode") == 0 and "result" in data:
                    raw_list = data["result"].get("list", [])
                    if raw_list:
                        # Bybit returns newest first, so reverse to chronological order
                        candles = []
                        for k in reversed(raw_list):
                            candles.append(Candle(
                                open_time=int(k[0]),
                                open=float(k[1]),
                                high=float(k[2]),
                                low=float(k[3]),
                                close=float(k[4]),
                                volume=float(k[5]),
                                close_time=int(k[0]) + 3600000 - 1
                            ))
                        return candles
        except Exception as e:
            logger.warning(f"Bybit klines fallback failed: {e}")

        # 3. Fallback: OKX Spot Candles
        try:
            base_coin, quote_coin = self._split_base_quote(norm_symbol)
            okx_inst = f"{base_coin}-{quote_coin}"
            okx_bars = {"15m": "15m", "1h": "1H", "4h": "4H", "1d": "D", "1w": "W"}
            o_bar = okx_bars.get(interval, "1H")
            okx_url = f"https://www.okx.com/api/v5/market/candles?instId={okx_inst}&bar={o_bar}&limit={limit}"
            resp = await self._safe_fetch(okx_url)
            if getattr(resp, "status", 200) == 200:
                data = json.loads(await resp.text())
                if data.get("code") == "0" and data.get("data"):
                    raw_list = data["data"]
                    candles = []
                    for k in reversed(raw_list):
                        candles.append(Candle(
                            open_time=int(k[0]),
                            open=float(k[1]),
                            high=float(k[2]),
                            low=float(k[3]),
                            close=float(k[4]),
                            volume=float(k[5]),
                            close_time=int(k[0]) + 3600000 - 1
                        ))
                    return candles
        except Exception as e:
            logger.warning(f"OKX klines fallback failed: {e}")

        if isinstance(last_error, BinanceAPIError):
            raise last_error
        raise BinanceAPIError("Failed to retrieve candlestick data from exchange feeds.")

    async def get_technical_analysis(self, symbol: str, timeframe: str = "1h") -> TechnicalAnalysisSummary:
        """Fetches candlesticks and computes full mathematical technical indicator suite."""
        norm_symbol = self.normalize_symbol(symbol)
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        from trading.technical_analysis import evaluate_market_structure

        candles = await self.get_klines(norm_symbol, interval=timeframe, limit=50)
        if not candles:
            raise BinanceAPIError(f"No candlestick data available for {norm_symbol}.")

        source_name = "Binance Klines"
        return evaluate_market_structure(
            norm_symbol,
            timeframe,
            candles,
            now_iso,
            source=source_name
        )

    async def get_market_state(
        self,
        symbol: str,
        primary_timeframe: str = "1h",
        include_mtf: bool = True
    ) -> MarketState:
        """
        Fetches full market state including spot ticker, primary timeframe indicators,
        deterministic market structure, multi-timeframe confirmation, and trade setup evaluation.
        """
        import asyncio
        norm_symbol = self.normalize_symbol(symbol)
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        from trading.technical_analysis import (
            evaluate_market_structure,
            analyze_market_structure,
            determine_mtf_alignment,
            evaluate_deterministic_setup,
        )

        # 1. Fetch 24h ticker (graceful fallback)
        ticker_24h = None
        try:
            ticker_24h = await self.get_24h_ticker(norm_symbol)
        except Exception as e:
            logger.warning(f"Could not fetch 24h ticker for market state {norm_symbol}: {e}")

        # 2. Fetch primary timeframe klines
        candles = await self.get_klines(norm_symbol, interval=primary_timeframe, limit=50)
        if not candles:
            raise BinanceAPIError(f"No candlestick data available for {norm_symbol} ({primary_timeframe}).")

        source_name = "Binance Klines"
        primary_ta = evaluate_market_structure(
            norm_symbol,
            primary_timeframe,
            candles,
            now_iso,
            source=source_name
        )

        market_structure = analyze_market_structure(
            norm_symbol,
            primary_timeframe,
            candles,
            lookback_window=30
        )

        # 3. Multi-timeframe confirmation
        multi_timeframe = None
        if include_mtf:
            if primary_timeframe == "1h":
                aux_tfs = ["4h", "1d"]
            elif primary_timeframe == "15m":
                aux_tfs = ["1h", "4h"]
            elif primary_timeframe == "4h":
                aux_tfs = ["1d", "1w"]
            elif primary_timeframe == "1d":
                aux_tfs = ["4h", "1w"]
            elif primary_timeframe == "1w":
                aux_tfs = ["1d", "4h"]
            else:
                aux_tfs = ["4h", "1d"]

            tf_ta_map = {primary_timeframe: primary_ta}

            async def fetch_aux(tf: str):
                try:
                    c = await self.get_klines(norm_symbol, interval=tf, limit=50)
                    if c:
                        return tf, evaluate_market_structure(norm_symbol, tf, c, now_iso, source=source_name)
                except Exception as ex:
                    logger.warning(f"Could not fetch auxiliary MTF {tf} for {norm_symbol}: {ex}")
                return tf, None

            aux_tasks = [fetch_aux(tf) for tf in aux_tfs]
            aux_results = await asyncio.gather(*aux_tasks, return_exceptions=True)
            for res in aux_results:
                if isinstance(res, tuple) and len(res) == 2 and res[1] is not None:
                    tf_ta_map[res[0]] = res[1]

            multi_timeframe = determine_mtf_alignment(primary_timeframe, tf_ta_map)

        # 4. Deterministic Trade Setup Evaluation
        trade_setup = evaluate_deterministic_setup(
            norm_symbol,
            primary_timeframe,
            candles,
            primary_ta,
            market_structure,
            mtf_summary=multi_timeframe
        )

        current_price = primary_ta.current_price

        return MarketState(
            symbol=norm_symbol,
            primary_timeframe=primary_timeframe,
            current_price=current_price,
            timestamp=now_iso,
            source=source_name,
            ticker_24h=ticker_24h,
            primary_ta=primary_ta,
            market_structure=market_structure,
            multi_timeframe=multi_timeframe,
            trade_setup=trade_setup
        )
