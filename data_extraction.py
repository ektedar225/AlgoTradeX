import pandas as pd
from SmartApi import SmartConnect
import pyotp
from datetime import datetime, time
from logzero import logger
import time as t

# ================= LOGIN DETAILS =================
API_KEY = "qZd3Xgul"
CLIENT_ID = "AAAB016978"
PASSWORD = "7006"
TOTP_SECRET = "7UKAS5FEGKXE6WBRMUNROHX4BU"

# ================= DATE =================
DATE_TO_FETCH = "2026-02-06"   # MUST be past trading day

# ================= INSTRUMENTS =================
INSTRUMENTS = [
    {
        "symbol": "NIFTY10FEB2625950CE",
        "token": "42544"
    },
    {
        "symbol": "NIFTY10FEB2625950PE",
        "token": "42545"
    }
]

EXCHANGE = "NFO"
INTERVAL = "THREE_MINUTE"

# ================= LOGIN =================
smartApi = SmartConnect(API_KEY)

try:
    totp = pyotp.TOTP(TOTP_SECRET).now()
    session = smartApi.generateSession(CLIENT_ID, PASSWORD, totp)

    if not session["status"]:
        raise Exception("Login failed")

    logger.info("✅ Login successful")

except Exception as e:
    logger.error(f"❌ Login error: {e}")
    exit()

# ================= MARKET-CLOSE CHECK =================
market_close = datetime.combine(
    datetime.strptime(DATE_TO_FETCH, "%Y-%m-%d"),
    time(15, 30)
)

if datetime.now() < market_close:
    logger.error("❌ Market not closed for selected date")
    exit()

## ================= FETCH FUNCTION (FIXED) =================
def fetch_5min_candles(symbol, token, retries=3):

    params = {
        "exchange": EXCHANGE,
        "symboltoken": token,
        "interval": INTERVAL,
        "fromdate": f"{DATE_TO_FETCH} 09:15",
        "todate": f"{DATE_TO_FETCH} 15:30"
    }

    for attempt in range(retries):
        try:
            response = smartApi.getCandleData(params)

            if response.get("status") and response.get("data"):
                df = pd.DataFrame(
                    response["data"],
                    columns=["Datetime", "Open", "High", "Low", "Close", "Volume"]
                )

                # 1. Convert Datetime
                df["Datetime"] = pd.to_datetime(df["Datetime"])

                # 2. Convert Numeric Columns Safely (The Fix)
                numeric_cols = ["Open", "High", "Low", "Close", "Volume"]
                for col in numeric_cols:
                    df[col] = pd.to_numeric(df[col], errors='coerce')

                # 3. Add Symbol
                df["Symbol"] = symbol

                return df

            else:
                logger.warning(
                    f"{symbol} | Attempt {attempt+1} | "
                    f"No data | Error: {response.get('errorcode')}"
                )

        except Exception as e:
            logger.error(f"{symbol} | API error: {e}")

        t.sleep(2)

    return None

# ================= FETCH AND SAVE DATA =================
call_data = []
put_data = []

for instrument in INSTRUMENTS:
    symbol = instrument["symbol"]
    token = instrument["token"]
    
    logger.info(f"Fetching data for {symbol}")
    df = fetch_5min_candles(symbol, token)
    
    if df is not None:
        logger.info(f"✅ Fetched {len(df)} candles for {symbol}")
        
        # Separate CALL and PUT
        if "CE" in symbol:
            call_data.append(df)
        elif "PE" in symbol:
            put_data.append(df)
    else:
        logger.warning(f"⚠️ No data fetched for {symbol}")

# Save CALL data
if call_data:
    call_df = pd.concat(call_data, ignore_index=True)
    call_filename = f"NIFTY_3MIN_{DATE_TO_FETCH}_CALL.csv"
    call_df.to_csv(call_filename, index=False)
    logger.info(f"✅ CALL data saved to {call_filename} ({len(call_df)} records)")
else:
    logger.warning("⚠️ No CALL data to save")

# Save PUT data
if put_data:
    put_df = pd.concat(put_data, ignore_index=True)
    put_filename = f"NIFTY_3MIN_{DATE_TO_FETCH}_PUT.csv"
    put_df.to_csv(put_filename, index=False)
    logger.info(f"✅ PUT data saved to {put_filename} ({len(put_df)} records)")
else:
    logger.warning("⚠️ No PUT data to save")