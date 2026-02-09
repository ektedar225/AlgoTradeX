import pandas as pd
import numpy as np
from logzero import logger
from datetime import datetime

# ================= STRATEGY PARAMETERS =================
BROKERAGE_CHARGE = 90  # Fixed ₹90 per trade
QUANTITY = 100
TRAILING_SL_OFFSET = 5  # Initial stop loss distance
SL_SHIFT_TRIGGER = 1  # Price move to start trailing SL
SL_DIFFERENCE = 0.5  # Maintain SL = Current Price - 0.5
ADX_THRESHOLD = 25  # ADX must be above this for a strong trend
ADX_PERIOD = 14  # ADX Calculation Period

def calculate_adx(df, period=ADX_PERIOD):
    """Calculate ADX using Wilder's Smoothing"""
    df['TR'] = np.maximum.reduce([
        df['High'] - df['Low'],
        abs(df['High'] - df['Close'].shift(1)),
        abs(df['Low'] - df['Close'].shift(1))
    ])
    df['+DM'] = np.where((df['High'] - df['High'].shift(1)) > (df['Low'].shift(1) - df['Low']),
                         df['High'] - df['High'].shift(1), 0)
    df['-DM'] = np.where((df['Low'].shift(1) - df['Low']) > (df['High'] - df['High'].shift(1)),
                         df['Low'].shift(1) - df['Low'], 0)

    # Wilder's Smoothing (Rolling Mean)
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

def backtest_strategy(df, symbol_type="UNKNOWN"):
    """
    Backtest the strategy on historical data
    Returns list of trades executed
    """
    df = calculate_indicators(df)
    trades = []
    in_trade = False
    entry_price = 0
    trailing_sl = 0
    entry_index = 0
    
    for i in range(len(df)):
        row = df.iloc[i]
        current_price = row['Close']
        ema_5 = row['EMA_5']
        ema_9 = row['EMA_9']
        adx = row['ADX']
        
        # Entry Signal
        if not in_trade and ema_5 > ema_9 and adx > ADX_THRESHOLD:
            entry_price = current_price
            trailing_sl = entry_price - TRAILING_SL_OFFSET
            in_trade = True
            entry_index = i
            logger.info(f"🟢 ENTRY at {row['Datetime']} | Price: {entry_price:.2f} | EMA5: {ema_5:.2f}, EMA9: {ema_9:.2f}, ADX: {adx:.2f}")
        
        # Trailing Stop Loss Logic
        if in_trade:
            # Update trailing SL
            if current_price >= entry_price + SL_SHIFT_TRIGGER:
                new_sl = current_price - SL_DIFFERENCE
                if new_sl > trailing_sl:
                    trailing_sl = new_sl
            
            # Exit Condition
            if current_price <= trailing_sl:
                exit_price = trailing_sl
                profit_loss = (exit_price - entry_price) * QUANTITY - (2 * BROKERAGE_CHARGE)
                profit_loss_percent = ((exit_price - entry_price) / entry_price) * 100
                
                trade_data = {
                    'Entry_Time': df.iloc[entry_index]['Datetime'],
                    'Exit_Time': row['Datetime'],
                    'Entry_Price': entry_price,
                    'Exit_Price': exit_price,
                    'P&L': profit_loss,
                    'P&L%': profit_loss_percent,
                    'Candles': i - entry_index
                }
                trades.append(trade_data)
                
                logger.info(f"🔴 EXIT at {row['Datetime']} | Price: {exit_price:.2f} | P&L: ₹{profit_loss:.2f} ({profit_loss_percent:.2f}%)")
                in_trade = False
    
    # If still in trade at end of data, close it
    if in_trade:
        final_price = df.iloc[-1]['Close']
        profit_loss = (final_price - entry_price) * QUANTITY - (2 * BROKERAGE_CHARGE)
        profit_loss_percent = ((final_price - entry_price) / entry_price) * 100
        
        trade_data = {
            'Entry_Time': df.iloc[entry_index]['Datetime'],
            'Exit_Time': df.iloc[-1]['Datetime'],
            'Entry_Price': entry_price,
            'Exit_Price': final_price,
            'P&L': profit_loss,
            'P&L%': profit_loss_percent,
            'Candles': len(df) - entry_index
        }
        trades.append(trade_data)
        
        logger.info(f"🟡 END OF DATA - Closing at {final_price:.2f} | P&L: ₹{profit_loss:.2f} ({profit_loss_percent:.2f}%)")
    
    return trades

def print_backtest_summary(trades, symbol_type):
    """Print summary statistics of backtesting"""
    logger.info("\n" + "="*70)
    logger.info(f"BACKTEST SUMMARY - {symbol_type}")
    logger.info("="*70)
    
    if not trades:
        logger.warning("No trades executed")
        return
    
    trades_df = pd.DataFrame(trades)
    
    total_trades = len(trades)
    winning_trades = len(trades_df[trades_df['P&L'] > 0])
    losing_trades = len(trades_df[trades_df['P&L'] < 0])
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
    
    total_pnl = trades_df['P&L'].sum()
    avg_pnl = trades_df['P&L'].mean()
    max_profit = trades_df['P&L'].max()
    max_loss = trades_df['P&L'].min()
    
    logger.info(f"Total Trades: {total_trades}")
    logger.info(f"Winning Trades: {winning_trades}")
    logger.info(f"Losing Trades: {losing_trades}")
    logger.info(f"Win Rate: {win_rate:.2f}%")
    logger.info(f"\nTotal P&L: ₹{total_pnl:.2f}")
    logger.info(f"Average P&L: ₹{avg_pnl:.2f}")
    logger.info(f"Max Profit: ₹{max_profit:.2f}")
    logger.info(f"Max Loss: ₹{max_loss:.2f}")
    logger.info("="*70 + "\n")
    
    # Print detailed trades
    logger.info("Detailed Trades:")
    for idx, trade in enumerate(trades, 1):
        logger.info(f"\nTrade {idx}:")
        logger.info(f"  Entry: {trade['Entry_Time']} @ ₹{trade['Entry_Price']:.2f}")
        logger.info(f"  Exit:  {trade['Exit_Time']} @ ₹{trade['Exit_Price']:.2f}")
        logger.info(f"  P&L:   ₹{trade['P&L']:.2f} ({trade['P&L%']:.2f}%)")
        logger.info(f"  Duration: {trade['Candles']} candles")

# ================= MAIN BACKTESTING =================
if __name__ == "__main__":
    import glob
    import os
    
    logger.info("🚀 Starting Comprehensive Strategy Backtest...\n")
    
    # Find all CSV files
    all_files = glob.glob("NIFTY_*MIN_*_*.csv")
    
    if not all_files:
        logger.error("❌ No CSV files found. Make sure data files exist.")
        exit()
    
    logger.info(f"✅ Found {len(all_files)} CSV files for backtesting\n")
    
    # Group files by interval (3MIN, 5MIN)
    files_3min = sorted([f for f in all_files if "3MIN" in f])
    files_5min = sorted([f for f in all_files if "5MIN" in f])
    
    all_results = []
    
    # ================= BACKTEST 3MIN DATA =================
    if files_3min:
        logger.info("="*70)
        logger.info("BACKTESTING 3-MINUTE CANDLES")
        logger.info("="*70 + "\n")
        
        interval_results = {"3MIN_CALL": [], "3MIN_PUT": []}
        
        for file in files_3min:
            try:
                df = pd.read_csv(file)
                df['Datetime'] = pd.to_datetime(df['Datetime'])
                
                if "CALL" in file:
                    label = f"3MIN {os.path.basename(file)[:-4]}"
                    trades = backtest_strategy(df.copy(), label)
                    interval_results["3MIN_CALL"].extend(trades)
                    print_backtest_summary(trades, label)
                    
                elif "PUT" in file:
                    label = f"3MIN {os.path.basename(file)[:-4]}"
                    trades = backtest_strategy(df.copy(), label)
                    interval_results["3MIN_PUT"].extend(trades)
                    print_backtest_summary(trades, label)
                    
            except Exception as e:
                logger.error(f"❌ Error processing {file}: {e}")
        
        all_results.append(interval_results)
    
    # ================= BACKTEST 5MIN DATA =================
    if files_5min:
        logger.info("="*70)
        logger.info("BACKTESTING 5-MINUTE CANDLES")
        logger.info("="*70 + "\n")
        
        interval_results = {"5MIN_CALL": [], "5MIN_PUT": []}
        
        for file in files_5min:
            try:
                df = pd.read_csv(file)
                df['Datetime'] = pd.to_datetime(df['Datetime'])
                
                if "CALL" in file:
                    label = f"5MIN {os.path.basename(file)[:-4]}"
                    trades = backtest_strategy(df.copy(), label)
                    interval_results["5MIN_CALL"].extend(trades)
                    print_backtest_summary(trades, label)
                    
                elif "PUT" in file:
                    label = f"5MIN {os.path.basename(file)[:-4]}"
                    trades = backtest_strategy(df.copy(), label)
                    interval_results["5MIN_PUT"].extend(trades)
                    print_backtest_summary(trades, label)
                    
            except Exception as e:
                logger.error(f"❌ Error processing {file}: {e}")
        
        all_results.append(interval_results)
    
    # ================= GRAND SUMMARY =================
    logger.info("\n" + "="*70)
    logger.info("GRAND SUMMARY - ALL DATASETS")
    logger.info("="*70)
    
    total_all_trades = 0
    total_all_pnl = 0
    
    for interval_results in all_results:
        for interval_type, trades in interval_results.items():
            if trades:
                interval_total = len(trades)
                interval_pnl = sum([t['P&L'] for t in trades])
                total_all_trades += interval_total
                total_all_pnl += interval_pnl
                
                trades_df = pd.DataFrame(trades)
                win_rate = (len(trades_df[trades_df['P&L'] > 0]) / len(trades) * 100) if len(trades) > 0 else 0
                
                logger.info(f"\n{interval_type}:")
                logger.info(f"  Total Trades: {interval_total}")
                logger.info(f"  Win Rate: {win_rate:.2f}%")
                logger.info(f"  Total P&L: ₹{interval_pnl:.2f}")
                logger.info(f"  Avg P&L per Trade: ₹{interval_pnl/interval_total:.2f}")
    
    logger.info("\n" + "-"*70)
    logger.info(f"📊 OVERALL RESULTS:")
    logger.info(f"   Total Trades Across All Datasets: {total_all_trades}")
    logger.info(f"   Overall P&L: ₹{total_all_pnl:.2f}")
    logger.info(f"   Avg P&L per Trade: ₹{total_all_pnl/total_all_trades:.2f}" if total_all_trades > 0 else "   No trades executed")
    logger.info("="*70)
