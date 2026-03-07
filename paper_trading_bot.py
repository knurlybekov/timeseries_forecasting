"""
FVG Paper Trading Bot - Alpaca API
Runs your 1-minute FVG strategy in real-time
"""

import os
import time
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging
import requests
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Setup logging
LOG_DIR = os.getenv("LOG_DIR", "logs")
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, 'trading_bot.log')),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

try:
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce, OrderType
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
except ImportError:
    import subprocess
    subprocess.check_call(['pip', 'install', 'alpaca-py', '-q'])
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce, OrderType
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

# =============================================================================
# CONFIGURATION
# =============================================================================

# Alpaca API Keys (Paper Trading)
# Get yours at: https://app.alpaca.markets/paper/dashboard/overview
# Set via environment variables or .env file
API_KEY = os.getenv("ALPACA_API_KEY", "")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
PAPER = True  # Always True for paper trading

# Strategy Settings
SYMBOLS = ['SPY', 'MSFT', 'TSLA', 'META']  # Best performers from backtest
RISK_REWARD = 3.0
FVG_SIZE = 0.25
ENGULF_TIMEOUT = 10
POSITION_SIZE = 500  # Dollars per trade (~1 share per trade)
MAX_DAILY_TRADES = 5

# Telegram Notifications (optional)
# Create bot via @BotFather, get chat ID via @userinfobot
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def send_telegram(message):
    """Send notification to Telegram"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }
        requests.post(url, json=payload, timeout=10)
        return True
    except Exception as e:
        logger.error(f"Telegram error: {e}")
        return False

# =============================================================================
# ALPACA CLIENT SETUP
# =============================================================================

trading_client = TradingClient(API_KEY, SECRET_KEY, paper=PAPER)
data_client = StockHistoricalDataClient(API_KEY, SECRET_KEY)

# =============================================================================
# STRATEGY FUNCTIONS (Same as backtest)
# =============================================================================

def get_opening_range(symbol):
    """Get today's opening range (9:30-9:35 candle)"""
    now = datetime.now()
    market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)

    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Minute,
        start=market_open,
        end=market_open + timedelta(minutes=5)
    )

    bars = data_client.get_stock_bars(request)

    if symbol in bars and len(bars[symbol]) > 0:
        # Aggregate first 5 minutes into OR
        highs = [bar.high for bar in bars[symbol]]
        lows = [bar.low for bar in bars[symbol]]
        return {
            'high': max(highs),
            'low': min(lows)
        }
    return None


def get_recent_candles(symbol, minutes=60):
    """Get recent 1-minute candles"""
    now = datetime.now()
    start = now - timedelta(minutes=minutes)

    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Minute,
        start=start,
        end=now
    )

    bars = data_client.get_stock_bars(request)

    if symbol in bars:
        df = pd.DataFrame([{
            'timestamp': bar.timestamp,
            'Open': bar.open,
            'High': bar.high,
            'Low': bar.low,
            'Close': bar.close,
            'Volume': bar.volume
        } for bar in bars[symbol]])

        if len(df) > 0:
            df.set_index('timestamp', inplace=True)
            return df
    return pd.DataFrame()


def detect_fvg(candles, direction, min_size=0.25):
    """Detect Fair Value Gap"""
    if len(candles) < 3:
        return None

    c1 = candles.iloc[-3]
    c3 = candles.iloc[-1]

    if direction == 'long':
        if c1['High'] < c3['Low']:
            gap_size = c3['Low'] - c1['High']
            if gap_size >= min_size:
                return {'top': c3['Low'], 'bottom': c1['High'], 'size': gap_size}
    else:
        if c1['Low'] > c3['High']:
            gap_size = c1['Low'] - c3['High']
            if gap_size >= min_size:
                return {'top': c1['Low'], 'bottom': c3['High'], 'size': gap_size}
    return None


def is_fvg_retested(candle, fvg, direction):
    """Check if candle retests FVG"""
    if fvg is None:
        return False
    if direction == 'long':
        return candle['Low'] <= fvg['top']
    else:
        return candle['High'] >= fvg['bottom']


def is_engulfing(prev_candle, curr_candle, direction):
    """Check for engulfing pattern"""
    prev_body_high = max(prev_candle['Open'], prev_candle['Close'])
    prev_body_low = min(prev_candle['Open'], prev_candle['Close'])
    curr_body_high = max(curr_candle['Open'], curr_candle['Close'])
    curr_body_low = min(curr_candle['Open'], curr_candle['Close'])

    engulfs = curr_body_low <= prev_body_low and curr_body_high >= prev_body_high

    if direction == 'long':
        return engulfs and curr_candle['Close'] > curr_candle['Open']
    else:
        return engulfs and curr_candle['Close'] < curr_candle['Open']


# =============================================================================
# TRADING FUNCTIONS
# =============================================================================

def get_account():
    """Get account info"""
    return trading_client.get_account()


def get_positions():
    """Get current positions"""
    return trading_client.get_all_positions()


def get_position(symbol):
    """Get position for specific symbol"""
    try:
        return trading_client.get_open_position(symbol)
    except:
        return None


def place_order(symbol, side, qty, order_type='market'):
    """Place an order"""
    try:
        order_request = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY if side == 'buy' else OrderSide.SELL,
            time_in_force=TimeInForce.DAY
        )

        order = trading_client.submit_order(order_request)
        logger.info(f"ORDER PLACED: {side.upper()} {qty} {symbol}")
        return order
    except Exception as e:
        logger.error(f"Order failed: {e}")
        return None


def close_position(symbol):
    """Close position for symbol"""
    try:
        trading_client.close_position(symbol)
        logger.info(f"POSITION CLOSED: {symbol}")
        return True
    except Exception as e:
        logger.error(f"Close failed: {e}")
        return False


# =============================================================================
# MAIN STRATEGY LOGIC
# =============================================================================

class FVGStrategy:
    def __init__(self, symbol):
        self.symbol = symbol
        self.state = 'waiting_for_breakout'
        self.or_high = None
        self.or_low = None
        self.breakout_direction = None
        self.active_fvg = None
        self.retest_candle = None
        self.retest_index = 0
        self.candle_count = 0
        self.position = None
        self.entry_price = None
        self.stop_price = None
        self.target_price = None

    def reset(self):
        """Reset for new day"""
        self.state = 'waiting_for_breakout'
        self.breakout_direction = None
        self.active_fvg = None
        self.retest_candle = None
        self.retest_index = 0
        self.candle_count = 0

    def set_opening_range(self, or_high, or_low):
        """Set today's opening range"""
        self.or_high = or_high
        self.or_low = or_low
        logger.info(f"{self.symbol} OR set: High={or_high:.2f}, Low={or_low:.2f}")

    def process_candle(self, candles):
        """Process new candle data"""
        if len(candles) < 3:
            return None

        candle = candles.iloc[-1]
        self.candle_count += 1

        # Check if we have a position to manage
        if self.position:
            return self.manage_position(candle)

        # STATE 1: Waiting for breakout
        if self.state == 'waiting_for_breakout':
            if candle['Close'] > self.or_high:
                self.breakout_direction = 'long'
                self.state = 'waiting_for_fvg'
                logger.info(f"{self.symbol} BREAKOUT LONG at {candle['Close']:.2f}")
            elif candle['Close'] < self.or_low:
                self.breakout_direction = 'short'
                self.state = 'waiting_for_fvg'
                logger.info(f"{self.symbol} BREAKOUT SHORT at {candle['Close']:.2f}")
            return None

        # STATE 2: Waiting for FVG
        if self.state == 'waiting_for_fvg':
            fvg = detect_fvg(candles, self.breakout_direction, FVG_SIZE)
            if fvg:
                self.active_fvg = fvg
                self.state = 'waiting_for_retest'
                logger.info(f"{self.symbol} FVG detected: {fvg}")
            return None

        # STATE 3: Waiting for retest
        if self.state == 'waiting_for_retest':
            if is_fvg_retested(candle, self.active_fvg, self.breakout_direction):
                self.retest_candle = candle.copy()
                self.retest_index = self.candle_count
                self.state = 'waiting_for_engulfing'
                logger.info(f"{self.symbol} FVG RETESTED")
            return None

        # STATE 4: Waiting for engulfing
        if self.state == 'waiting_for_engulfing':
            # Timeout check
            if self.candle_count - self.retest_index > ENGULF_TIMEOUT:
                self.state = 'waiting_for_fvg'
                self.retest_candle = None
                logger.info(f"{self.symbol} Engulfing timeout, looking for new FVG")
                return None

            prev_candle = candles.iloc[-2]
            if is_engulfing(self.retest_candle, candle, self.breakout_direction):
                # ENTRY SIGNAL!
                return self.generate_entry_signal(candle)

        return None

    def generate_entry_signal(self, candle):
        """Generate entry signal with stop and target"""
        if self.breakout_direction == 'long':
            entry = candle['Close']
            stop = min(candle['Low'], self.active_fvg['bottom']) - 0.01
            risk = entry - stop
            target = entry + (risk * RISK_REWARD)

            return {
                'action': 'BUY',
                'symbol': self.symbol,
                'entry': entry,
                'stop': stop,
                'target': target,
                'risk': risk
            }
        else:
            entry = candle['Close']
            stop = max(candle['High'], self.active_fvg['top']) + 0.01
            risk = stop - entry
            target = entry - (risk * RISK_REWARD)

            return {
                'action': 'SELL',
                'symbol': self.symbol,
                'entry': entry,
                'stop': stop,
                'target': target,
                'risk': risk
            }

    def manage_position(self, candle):
        """Manage open position - check stop/target"""
        if self.breakout_direction == 'long':
            if candle['Low'] <= self.stop_price:
                return {'action': 'CLOSE', 'reason': 'STOP_HIT'}
            if candle['High'] >= self.target_price:
                return {'action': 'CLOSE', 'reason': 'TARGET_HIT'}
        else:
            if candle['High'] >= self.stop_price:
                return {'action': 'CLOSE', 'reason': 'STOP_HIT'}
            if candle['Low'] <= self.target_price:
                return {'action': 'CLOSE', 'reason': 'TARGET_HIT'}
        return None


# =============================================================================
# MAIN BOT LOOP
# =============================================================================

def is_market_open():
    """Check if market is open (simplified)"""
    now = datetime.now()
    # Market hours: 9:30 AM - 4:00 PM ET, Monday-Friday
    if now.weekday() >= 5:  # Weekend
        return False
    market_open = now.replace(hour=9, minute=30, second=0)
    market_close = now.replace(hour=16, minute=0, second=0)
    return market_open <= now <= market_close


def run_bot():
    """Main bot loop"""
    logger.info("=" * 60)
    logger.info("FVG PAPER TRADING BOT STARTED")
    logger.info("=" * 60)

    send_telegram("🤖 <b>FVG Trading Bot Started</b>\n\nWatching: " + ", ".join(SYMBOLS))

    # Initialize strategies for each symbol
    strategies = {symbol: FVGStrategy(symbol) for symbol in SYMBOLS}
    daily_trades = 0
    last_date = None
    or_set = False

    while True:
        try:
            now = datetime.now()
            current_date = now.date()

            # Reset at start of new day
            if last_date != current_date:
                last_date = current_date
                daily_trades = 0
                or_set = False
                for strategy in strategies.values():
                    strategy.reset()
                logger.info(f"New trading day: {current_date}")

            # Wait for market to open
            if not is_market_open():
                logger.info("Market closed. Waiting...")
                time.sleep(60)
                continue

            # Set opening range after 9:35
            if not or_set and now.hour == 9 and now.minute >= 35:
                for symbol, strategy in strategies.items():
                    or_data = get_opening_range(symbol)
                    if or_data:
                        strategy.set_opening_range(or_data['high'], or_data['low'])
                or_set = True
                logger.info("Opening ranges set for all symbols")

            # Skip if OR not set yet
            if not or_set:
                time.sleep(30)
                continue

            # Process each symbol
            for symbol, strategy in strategies.items():
                # Skip if max daily trades reached
                if daily_trades >= MAX_DAILY_TRADES:
                    continue

                # Get recent candles
                candles = get_recent_candles(symbol, minutes=60)
                if len(candles) < 5:
                    continue

                # Process candle and get signal
                signal = strategy.process_candle(candles)

                if signal:
                    if signal['action'] in ['BUY', 'SELL']:
                        # Calculate position size (fractional shares supported)
                        qty = round(POSITION_SIZE / signal['entry'], 2)
                        if qty >= 0.01:
                            side = 'buy' if signal['action'] == 'BUY' else 'sell'
                            order = place_order(symbol, side, qty)

                            if order:
                                strategy.position = order
                                strategy.entry_price = signal['entry']
                                strategy.stop_price = signal['stop']
                                strategy.target_price = signal['target']
                                daily_trades += 1

                                logger.info(f"TRADE ENTERED: {signal}")
                                send_telegram(
                                    f"🔔 <b>TRADE OPENED</b>\n\n"
                                    f"Symbol: <b>{symbol}</b>\n"
                                    f"Side: {signal['action']}\n"
                                    f"Entry: ${signal['entry']:.2f}\n"
                                    f"Stop: ${signal['stop']:.2f}\n"
                                    f"Target: ${signal['target']:.2f}\n"
                                    f"Risk: ${signal['risk']:.2f}"
                                )

                    elif signal['action'] == 'CLOSE':
                        close_position(symbol)
                        result_emoji = "✅" if signal['reason'] == 'TARGET_HIT' else "❌"
                        send_telegram(
                            f"{result_emoji} <b>TRADE CLOSED</b>\n\n"
                            f"Symbol: <b>{symbol}</b>\n"
                            f"Reason: {signal['reason']}\n"
                            f"Entry: ${strategy.entry_price:.2f}\n"
                            f"Exit: {'Target' if signal['reason'] == 'TARGET_HIT' else 'Stop'}"
                        )
                        strategy.position = None
                        strategy.reset()
                        logger.info(f"TRADE CLOSED: {symbol} - {signal['reason']}")

            # Sleep until next minute
            time.sleep(60)

        except KeyboardInterrupt:
            logger.info("Bot stopped by user")
            break
        except Exception as e:
            logger.error(f"Error: {e}")
            time.sleep(60)


# =============================================================================
# RUN
# =============================================================================

if __name__ == "__main__":
    print("""
    ╔══════════════════════════════════════════════════════════════╗
    ║           FVG PAPER TRADING BOT - ALPACA                     ║
    ╠══════════════════════════════════════════════════════════════╣
    ║  1. Go to https://app.alpaca.markets                         ║
    ║  2. Sign up for free account                                 ║
    ║  3. Go to Paper Trading dashboard                            ║
    ║  4. Get your API Key and Secret Key                          ║
    ║  5. Paste them in this file (lines 42-43)                    ║
    ║  6. Run this script during market hours                      ║
    ╚══════════════════════════════════════════════════════════════╝
    """)

    if not API_KEY or not SECRET_KEY:
        print("ERROR: Please set your Alpaca API keys!")
        print("Set environment variables: ALPACA_API_KEY and ALPACA_SECRET_KEY")
        print("Or create a .env file with these values.")
    else:
        # Show account info
        try:
            account = get_account()
            print(f"\nAccount Status: {account.status}")
            print(f"Buying Power: ${float(account.buying_power):,.2f}")
            print(f"Cash: ${float(account.cash):,.2f}")
            print(f"\nStarting bot for: {SYMBOLS}")
            print("Press Ctrl+C to stop\n")

            run_bot()
        except Exception as e:
            print(f"Error connecting to Alpaca: {e}")
            print("Make sure your API keys are correct and you have paper trading enabled.")
