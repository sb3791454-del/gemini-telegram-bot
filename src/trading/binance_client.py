"""Asynchronous Binance Public REST API client for Cloudflare Workers."""

import json
import logging
from datetime import datetime, timezone
from typing import Optional
from trading.models import PriceTicker, Ticker24h, OrderBookDepth

logger = logging.getLogger("worker.trading.binance")

class BinanceAPIError(Exception):
    """Custom exception for Binance API errors."""
    def __init__(self, message: str, status_code: Optional[int] = None, error_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code

class BinanceClient:
    """Free public Binance Spot REST client (zero authentication required)."""
    BASE_URL = "https://data-api.binance.vision"

    def __init__(self, http_fetch_fn):
        self.fetch_fn = http_fetch_fn

    @staticmethod
    def normalize_symbol(raw_symbol: str) -> str:
        """
        Normalizes and strictly validates cryptocurrency trading pair symbols.
        Converts to uppercase alphanumeric. Appends 'USDT' if single coin ticker (e.g. 'BTC' -> 'BTCUSDT').
        """
        cleaned = raw_symbol.strip().upper().replace("/", "").replace("-", "").replace("_", "")
        if not cleaned.isalnum():
            raise ValueError(f"Invalid symbol '{raw_symbol}': Symbol must contain only alphanumeric characters.")
        if len(cleaned) < 2 or len(cleaned) > 20:
            raise ValueError(f"Invalid symbol '{raw_symbol}': Symbol length must be between 2 and 20 characters.")
        
        # If user types single major coin name, default to USDT pair
        major_coins = ("BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT", "NEAR", "SUI", "APT", "MATIC", "LTC")
        if cleaned in major_coins:
            return f"{cleaned}USDT"
            
        return cleaned

    async def get_price(self, symbol: str) -> PriceTicker:
        """Fetches the latest spot price for a symbol."""
        norm_symbol = self.normalize_symbol(symbol)
        url = f"{self.BASE_URL}/api/v3/ticker/price?symbol={norm_symbol}"
        
        try:
            resp = await self.fetch_fn(url, method="GET")
            status = getattr(resp, "status", 200)
            resp_text = await resp.text()
            
            if status == 429:
                raise BinanceAPIError("Rate limit reached (HTTP 429). Please try again in a few moments.", status_code=429)
            if status == 418:
                raise BinanceAPIError("IP temporarily banned by Binance (HTTP 418).", status_code=418)
            if status >= 400:
                try:
                    err_json = json.loads(resp_text)
                    msg = err_json.get("msg", resp_text)
                    code = err_json.get("code")
                    raise BinanceAPIError(f"Binance API error: {msg}", status_code=status, error_code=code)
                except (json.JSONDecodeError, ValueError):
                    raise BinanceAPIError(f"Binance returned error status {status}: {resp_text}", status_code=status)

            try:
                data = json.loads(resp_text)
            except Exception:
                raise BinanceAPIError("Malformed response received from Binance API.")

            if not isinstance(data, dict) or "price" not in data:
                raise BinanceAPIError("Malformed response received from Binance API.")

            now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            return PriceTicker(
                symbol=data.get("symbol", norm_symbol),
                price=float(data["price"]),
                timestamp=now_iso
            )
        except BinanceAPIError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error fetching Binance price for {symbol}: {e}")
            raise BinanceAPIError(f"Failed to connect to Binance market feed: {str(e)}")

    async def get_24h_ticker(self, symbol: str) -> Ticker24h:
        """Fetches 24-hour rolling statistics for a symbol."""
        norm_symbol = self.normalize_symbol(symbol)
        url = f"{self.BASE_URL}/api/v3/ticker/24hr?symbol={norm_symbol}"
        
        try:
            resp = await self.fetch_fn(url, method="GET")
            status = getattr(resp, "status", 200)
            resp_text = await resp.text()
            
            if status == 429:
                raise BinanceAPIError("Rate limit reached (HTTP 429). Please try again in a few moments.", status_code=429)
            if status >= 400:
                try:
                    err_json = json.loads(resp_text)
                    msg = err_json.get("msg", resp_text)
                    code = err_json.get("code")
                    raise BinanceAPIError(f"Binance API error: {msg}", status_code=status, error_code=code)
                except (json.JSONDecodeError, ValueError):
                    raise BinanceAPIError(f"Binance returned error status {status}", status_code=status)

            try:
                data = json.loads(resp_text)
            except Exception:
                raise BinanceAPIError("Malformed response received from Binance 24hr API.")

            if not isinstance(data, dict) or "lastPrice" not in data:
                raise BinanceAPIError("Malformed response received from Binance 24hr API.")

            now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            return Ticker24h(
                symbol=data.get("symbol", norm_symbol),
                last_price=float(data["lastPrice"]),
                price_change=float(data.get("priceChange", 0.0)),
                price_change_percent=float(data.get("priceChangePercent", 0.0)),
                high_price=float(data.get("highPrice", 0.0)),
                low_price=float(data.get("lowPrice", 0.0)),
                volume=float(data.get("volume", 0.0)),
                quote_volume=float(data.get("quoteVolume", 0.0)),
                timestamp=now_iso
            )
        except BinanceAPIError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error fetching Binance 24h ticker for {symbol}: {e}")
            raise BinanceAPIError(f"Failed to connect to Binance 24hr feed: {str(e)}")

    async def get_order_book_depth(self, symbol: str, limit: int = 5) -> OrderBookDepth:
        """Fetches top bids and asks from order book depth."""
        norm_symbol = self.normalize_symbol(symbol)
        url = f"{self.BASE_URL}/api/v3/depth?symbol={norm_symbol}&limit={limit}"
        
        try:
            resp = await self.fetch_fn(url, method="GET")
            status = getattr(resp, "status", 200)
            resp_text = await resp.text()
            
            if status == 429:
                raise BinanceAPIError("Rate limit reached (HTTP 429). Please try again in a few moments.", status_code=429)
            if status >= 400:
                try:
                    err_json = json.loads(resp_text)
                    msg = err_json.get("msg", resp_text)
                    code = err_json.get("code")
                    raise BinanceAPIError(f"Binance API error: {msg}", status_code=status, error_code=code)
                except (json.JSONDecodeError, ValueError):
                    raise BinanceAPIError(f"Binance returned error status {status}", status_code=status)

            try:
                data = json.loads(resp_text)
            except Exception:
                raise BinanceAPIError("Malformed response received from Binance depth API.")

            raw_bids = data.get("bids", [])
            raw_asks = data.get("asks", [])
            
            bids = [(float(b[0]), float(b[1])) for b in raw_bids[:limit]]
            asks = [(float(a[0]), float(a[1])) for a in raw_asks[:limit]]
            
            best_bid = bids[0][0] if bids else 0.0
            best_ask = asks[0][0] if asks else 0.0
            spread = max(0.0, best_ask - best_bid) if (best_bid and best_ask) else 0.0
            spread_pct = (spread / best_ask * 100.0) if best_ask else 0.0
            
            now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            return OrderBookDepth(
                symbol=norm_symbol,
                bids=bids,
                asks=asks,
                best_bid=best_bid,
                best_ask=best_ask,
                spread=spread,
                spread_percentage=spread_pct,
                timestamp=now_iso
            )
        except BinanceAPIError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error fetching Binance depth for {symbol}: {e}")
            raise BinanceAPIError(f"Failed to connect to Binance depth feed: {str(e)}")
