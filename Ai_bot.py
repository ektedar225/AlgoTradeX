import time
import math
import numpy as np
import pandas as pd
import pyotp
from SmartApi import SmartConnect
import google.generativeai as genai
from config import GEMINI_API_KEY, api_key, client_id, password, totp_key

genai.configure(api_key=GEMINI_API_KEY)

gemini_model = genai.GenerativeModel("gemini-1.5-flash")

# =========================
# SMART API LOGIN
# =========================

obj = SmartConnect(api_key=api_key)
totp = pyotp.TOTP(totp_key).now()
data = obj.generateSession(client_id, password, totp)
feedToken = obj.getfeedToken()

print("[login] SmartAPI login successful")

# =========================
# TRADEABLE OPTIONS
# =========================

options = [
    {"symbol": "BANKNIFTY27MAR2551700PE", "token": "59542", "strike": 51700, "type": "PUT"},
    {"symbol": "BANKNIFTY27MAR2551600CE", "token": "59523", "strike": 51600, "type": "CALL"},
]

lot_size = 30  # BANKNIFTY lot size

# =========================
# STRATEGY PARAMETERS
# =========================

RSI_PERIOD = 14
ATR_PERIOD = 14
ADX_PERIOD = 14
EMA_SHORT = 12
EMA_LONG = 26
MACD_SHORT = 12
MACD_LONG = 26
MACD_SIGNAL = 9

MACD_NEAR_ZERO_THRESHOLD = 0.5
ATR_SL_MULTIPLIER = 1.5
TP_SL_RATIO = 1.8
MIN_SL_POINTS = 10
ADX_THRESHOLD = 18
SLEEP_LOOP = 5
VWAP_LOOKBACK = 60

# =========================
# INDICATOR FUNCTIONS
# =========================

def fetch_candles(symbol, token, interval="ONE_MINUTE"):
    try:
        params = {
            "exchange": "NFO",
            "symboltoken": token,
            "interval": interval,
            "fromdate": (pd.Timestamp.now() - pd.Timedelta(days=1)).strftime("%Y-%m-%d 09:15"),
            "todate": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
        }
        candles = obj.getCandleData(params)
        if not candles or "data" not in candles or len(candles["data"]) == 0:
            return None

        df = pd.DataFrame(
            candles["data"],
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )
        df[["open", "high", "low", "close", "volume"]] = df[
            ["open", "high", "low", "close", "volume"]
        ].astype(float)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        return df.set_index("timestamp")

    except Exception as e:
        print(f"[fetch_candles] {symbol} error: {e}")
        return None


def calculate_vwap(df):
    if df is None or df.empty:
        return None
    df = df.iloc[-VWAP_LOOKBACK:]
    tp = (df["close"] * df["volume"]).cumsum()
    vol = df["volume"].cumsum()
    return tp.iloc[-1] / vol.iloc[-1] if vol.iloc[-1] > 0 else None


def calculate_rsi(df, period=RSI_PERIOD):
    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = -delta.clip(upper=0).rolling(period).mean()
    rs = gain / loss
    return (100 - (100 / (1 + rs))).iloc[-1]


def calculate_macd(df):
    ema_short = df["close"].ewm(span=MACD_SHORT).mean()
    ema_long = df["close"].ewm(span=MACD_LONG).mean()
    macd = ema_short - ema_long
    signal = macd.ewm(span=MACD_SIGNAL).mean()
    return macd.iloc[-1], signal.iloc[-1], ema_short.iloc[-1], ema_long.iloc[-1]


def calculate_atr(df):
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(ATR_PERIOD).mean().iloc[-1]


def calculate_adx(df):
    high, low, close = df["high"], df["low"], df["close"]
    plus_dm = high.diff()
    minus_dm = low.diff().abs()

    plus_dm = np.where((plus_dm > minus_dm) & (plus_dm > 0), plus_dm, 0)
    minus_dm = np.where((minus_dm > plus_dm) & (minus_dm > 0), minus_dm, 0)

    tr = pd.concat(
        [(high - low), (high - close.shift()).abs(), (low - close.shift()).abs()],
        axis=1,
    ).max(axis=1)

    atr = tr.rolling(ADX_PERIOD).mean()
    plus_di = 100 * pd.Series(plus_dm).rolling(ADX_PERIOD).mean() / atr
    minus_di = 100 * pd.Series(minus_dm).rolling(ADX_PERIOD).mean() / atr
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    return dx.rolling(ADX_PERIOD).mean().iloc[-1]


def get_ltp(symbol, token):
    try:
        ltp_data = obj.ltpData("NFO", symbol, token)
        return float(ltp_data["data"]["ltp"])
    except:
        return None


# =========================
# SENTIMENT PLACEHOLDER
# =========================

def get_gemini_sentiment_for_symbol(symbol):
    """
    Gemini-based short-term sentiment classifier
    Returns: POS / NEG / NEU
    """

    prompt = f"""
    You are an intraday options trader.
    Classify short-term sentiment for {symbol}.
    Reply with only one word: POS, NEG, or NEU.
    """

    try:
        response = gemini_model.generate_content(prompt)
        sentiment = response.text.strip().upper()

        if sentiment in ["POS", "NEG", "NEU"]:
            return sentiment
        return "NEU"

    except Exception as e:
        print("[Gemini Error]", e)
        return "NEU"


# =========================
# ORDER FUNCTIONS
# =========================

def place_order(symbol, token, qty, action):
    params = {
        "variety": "NORMAL",
        "tradingsymbol": symbol,
        "symboltoken": token,
        "transactiontype": action,
        "exchange": "NFO",
        "ordertype": "MARKET",
        "producttype": "INTRADAY",
        "duration": "DAY",
        "quantity": qty,
    }
    return obj.placeOrder(params)


# =========================
# POSITION MANAGEMENT
# =========================

positions = {}


def enter_position(opt, side, ltp, atr):
    sl_points = max(MIN_SL_POINTS, atr * ATR_SL_MULTIPLIER)
    sl = ltp - sl_points if side == "BUY" else ltp + sl_points
    tp = ltp + sl_points * TP_SL_RATIO if side == "BUY" else ltp - sl_points * TP_SL_RATIO

    place_order(opt["symbol"], opt["token"], lot_size, side)

    positions[opt["symbol"]] = {
        "side": side,
        "sl": sl,
        "tp": tp,
    }
    print(f"[ENTRY] {opt['symbol']} {side} @ {ltp}")


def exit_position(symbol, opt, side):
    place_order(opt["symbol"], opt["token"], lot_size, side)
    del positions[symbol]
    print(f"[EXIT] {symbol}")


# =========================
# MAIN LOOP
# =========================

def expiry_day_scalp_loop():
    print("[START] Expiry scalping started")

    while True:
        try:
            for opt in options:
                symbol, token = opt["symbol"], opt["token"]
                ltp = get_ltp(symbol, token)
                df = fetch_candles(symbol, token)

                if ltp is None or df is None or len(df) < 50:
                    continue

                vwap = calculate_vwap(df)
                rsi = calculate_rsi(df)
                macd, signal, ema_s, ema_l = calculate_macd(df)
                atr = calculate_atr(df)
                adx = calculate_adx(df)

                buy_cond = (
                    macd > signal
                    and abs(macd) < MACD_NEAR_ZERO_THRESHOLD
                    and ema_s > ema_l
                    and ltp > vwap
                    and rsi > 50
                    and adx > ADX_THRESHOLD
                )

                sell_cond = (
                    macd < signal
                    and abs(macd) < MACD_NEAR_ZERO_THRESHOLD
                    and ema_s < ema_l
                    and ltp < vwap
                    and rsi < 50
                    and adx > ADX_THRESHOLD
                )

                if symbol not in positions:
                    if buy_cond:
                        enter_position(opt, "BUY", ltp, atr)
                    elif sell_cond:
                        enter_position(opt, "SELL", ltp, atr)

                else:
                    pos = positions[symbol]
                    if pos["side"] == "BUY" and (ltp <= pos["sl"] or ltp >= pos["tp"]):
                        exit_position(symbol, opt, "SELL")
                    elif pos["side"] == "SELL" and (ltp >= pos["sl"] or ltp <= pos["tp"]):
                        exit_position(symbol, opt, "BUY")

            time.sleep(SLEEP_LOOP)

        except Exception as e:
            print("[ERROR]", e)
            time.sleep(2)


# =========================
# RUN
# =========================

if __name__ == "__main__":
    expiry_day_scalp_loop()
