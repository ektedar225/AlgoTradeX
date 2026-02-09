import numpy as np
import pandas as pd
from SmartApi import SmartConnect
import pyotp
from logzero import logger
import time
from datetime import datetime, timedelta

# Trading parameters
BROKERAGE_CHARGE = 90  # Fixed ₹90 per trade
QUANTITY = 100
TRAILING_SL_OFFSET = 5  # Initial stop loss distance
SL_SHIFT_TRIGGER = 1  # Price move to start trailing SL
SL_DIFFERENCE = 0.5  # Maintain SL = Current Price - 0.5
ADX_THRESHOLD = 25  # ADX must be above this for a strong trend
ADX_PERIOD = 14  # ADX Calculation Period

# API credentials
api_key = ''
username = ''
pwd = ''
smartApi = SmartConnect(api_key)

# Initialize session
try:
    token = ""
    totp = pyotp.TOTP(token).now()
    data = smartApi.generateSession(username, pwd, totp)
    if not data['status']:
        logger.error("Authentication failed")
        exit()
except Exception as e:
    logger.error(f"Session error: {e}")
    exit()

# Trading symbol
symbol = "CRUDEOIL16APR255750CE"
symbol_token = "447574"
exchange = "MCX"

def fetch_market_data():
    """Fetch recent market data (candles)"""
    try:
        response = smartApi.getCandleData({
            "exchange": exchange,
            "symboltoken": symbol_token,
            "interval": "ONE_MINUTE",
            "fromdate": (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d %H:%M"),
            "todate": datetime.now().strftime("%Y-%m-%d %H:%M")
        })
        if 'data' in response and response['data']:
            df = pd.DataFrame(response['data'], columns=['Datetime', 'Open', 'High', 'Low', 'Close', 'Volume'])
            df[['Open', 'High', 'Low', 'Close', 'Volume']] = df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float)
            logger.info(f"✅ Market Data Fetched! Last 5 Candles:\n{df.tail(5)}")  # Compare with Angel One
            return df
        else:
            logger.error("Empty market data response")
            return None
    except Exception as e:
        logger.error(f"Data fetch error: {e}")
        return None

def calculate_adx(df, period=ADX_PERIOD):
    """Calculate ADX using Wilder’s Smoothing"""
    df['TR'] = np.maximum.reduce([
        df['High'] - df['Low'],
        abs(df['High'] - df['Close'].shift(1)),
        abs(df['Low'] - df['Close'].shift(1))
    ])
    df['+DM'] = np.where((df['High'] - df['High'].shift(1)) > (df['Low'].shift(1) - df['Low']),
                         df['High'] - df['High'].shift(1), 0)
    df['-DM'] = np.where((df['Low'].shift(1) - df['Low']) > (df['High'] - df['High'].shift(1)),
                         df['Low'].shift(1) - df['Low'], 0)

    # Wilder’s Smoothing (Rolling Mean)
    df['TR_smooth'] = df['TR'].rolling(window=period).mean()
    df['+DM_smooth'] = df['+DM'].rolling(window=period).mean()
    df['-DM_smooth'] = df['-DM'].rolling(window=period).mean()

    df['+DI'] = (df['+DM_smooth'] / df['TR_smooth']) * 100
    df['-DI'] = (df['-DM_smooth'] / df['TR_smooth']) * 100
    df['DX'] = (abs(df['+DI'] - df['-DI']) / abs(df['+DI'] + df['-DI'])) * 100
    df['ADX'] = df['DX'].rolling(window=period).mean()

    return df

def calculate_indicators(df):
    """Calculate EMA5, EMA9, and ADX"""
    df['EMA_5'] = df['Close'].ewm(span=5, adjust=False).mean()
    df['EMA_9'] = df['Close'].ewm(span=9, adjust=False).mean()
    df = calculate_adx(df)
    return df

def trade():
    """Continuously check for a bullish trend and execute one trade with trailing SL"""
    while True:
        df = fetch_market_data()
        if df is None:
            time.sleep(5)
            continue
        
        df = calculate_indicators(df)
        latest = df.iloc[-1]
        ema_5, ema_9, adx = latest['EMA_5'], latest['EMA_9'], latest['ADX']
        
        logger.info(f"📊 Checking trend - EMA5: {ema_5:.2f}, EMA9: {ema_9:.2f}, ADX: {adx:.2f}")

        if ema_5 > ema_9 and adx > ADX_THRESHOLD:
            logger.info(f"✅ Bullish Signal! EMA_5: {ema_5}, EMA_9: {ema_9}, ADX: {adx}")
            entry_price = latest['Close']
            
            # Place Buy Order
            buy_order = smartApi.placeOrder({
                "variety": "NORMAL",
                "tradingsymbol": symbol,
                "symboltoken": symbol_token,
                "transactiontype": "BUY",
                "exchange": exchange,
                "ordertype": "LIMIT",
                "producttype": "INTRADAY",
                "duration": "DAY",
                "price": str(entry_price),
                "quantity": str(QUANTITY)
            })
            logger.info(f"BUY Order Placed at {entry_price}")
            
            # Implement Trailing Stop Loss
            trailing_sl = entry_price - TRAILING_SL_OFFSET
            while True:
                df = fetch_market_data()
                if df is None:
                    time.sleep(5)
                    continue
                
                current_price = df.iloc[-1]['Close']
                if current_price >= entry_price + SL_SHIFT_TRIGGER:
                    new_sl = current_price - SL_DIFFERENCE
                    if new_sl > trailing_sl:
                        trailing_sl = new_sl
                        logger.info(f"🔄 Trailing SL updated to {trailing_sl}")

                if current_price <= trailing_sl:
                    logger.info(f"❌ SL Hit at {trailing_sl}, EXIT TRADE!")
                    smartApi.placeOrder({
                        "variety": "NORMAL",
                        "tradingsymbol": symbol,
                        "symboltoken": symbol_token,
                        "transactiontype": "SELL",
                        "exchange": exchange,
                        "ordertype": "LIMIT",
                        "producttype": "INTRADAY",
                        "duration": "DAY",
                        "price": str(trailing_sl),
                        "quantity": str(QUANTITY)
                    })
                    return  # Exit trade loop after one trade
                
                time.sleep(5)
        
        time.sleep(5)

if __name__ == "__main__":
    trade()