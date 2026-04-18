# ========================================v.6==
# Stage 2A Scanner (RUN ONCE - CRON MODE)
# ==========================================
import os
import asyncio
import math
import logging
import pandas as pd
import yfinance as yf
from telegram import Bot

# ==========================================
# CONFIG (แนะนำใช้ ENV)
# ==========================================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

bot = Bot(token=BOT_TOKEN)

# ==========================================
# SYMBOLS
# ==========================================
def get_symbols_from_google_sheet():
    url = "https://docs.google.com/spreadsheets/d/1r9Zh_7bS94NYI6XKA7Lm7YWK5WQWYw0wopcve4DJuHw/export?format=csv"
    df = pd.read_csv(url)

    col = df.columns[0]

    symbols = (
        df[col]
        .dropna()
        .astype(str)
        .str.strip()
        .str.upper()
        .str.replace(".", "-", regex=False)
        .unique()
        .tolist()
    )

    print(f"[INFO] Google Sheet symbols: {len(symbols)}")
    return symbols


def get_sp500():
    url = "https://datahub.io/core/s-and-p-500-companies/r/constituents.csv"
    df = pd.read_csv(url)

    col = "Symbol" if "Symbol" in df.columns else df.columns[0]

    symbols = (
        df[col]
        .dropna()
        .astype(str)
        .str.strip()
        .str.replace(".", "-", regex=False)
        .unique()
        .tolist()
    )

    print(f"[INFO] S&P500 symbols: {len(symbols)}")
    return symbols


def get_nasdaq100():
    url = "https://raw.githubusercontent.com/Gary-Strauss/NASDAQ100_Constituents/master/data/nasdaq100_constituents.csv"
    df = pd.read_csv(url)

    col = "Ticker" if "Ticker" in df.columns else df.columns[0]

    symbols = (
        df[col]
        .dropna()
        .astype(str)
        .str.strip()
        .str.replace(".", "-", regex=False)
        .unique()
        .tolist()
    )

    print(f"[INFO] NASDAQ100 symbols: {len(symbols)}")
    return symbols


def get_all_symbols():
    sp500 = set(get_sp500())
    nasdaq100 = set(get_nasdaq100())
    google = set(get_symbols_from_google_sheet())

    symbols = list(sp500 | nasdaq100 | google)

    #blacklist = {"BF-B"}
    #symbols = [s for s in symbols if s not in blacklist]

    symbols.sort()
    print(f"[INFO] Total symbols: {len(symbols)}")

    return symbols


# ==========================================
# SATA
# ==========================================
def calculate_sata(symbol):
    try:
        stock = yf.Ticker(symbol).history(period="3y", interval="1wk")
        index = yf.Ticker("^GSPC").history(period="3y", interval="1wk")

        df = pd.DataFrame({
            "Close": stock["Close"],
            "High": stock["High"],
            "Low": stock["Low"],
            "Volume": stock["Volume"],
            "Index": index["Close"]
        }).dropna()

        if len(df) < 60:
            return None, None, None

        df["ma10"] = df["Close"].rolling(10).mean()
        df["ma30"] = df["Close"].rolling(30).mean()
        df["ma40"] = df["Close"].rolling(40).mean()

        df["ma10_slope"] = df["ma10"].diff()
        df["ma30_slope"] = df["ma30"].diff()
        df["ma40_slope"] = df["ma40"].diff()

        rs = df["Close"] / df["Index"]
        rs_ma = rs.rolling(52).mean()
        mansfield = ((rs / rs_ma) - 1) * 100
        rs_slope = mansfield.diff()

        df["vol_ma"] = df["Volume"].rolling(10).mean()

        sata = pd.DataFrame(index=df.index)

        sata["a1"] = (df["Close"] > df["ma30"]).astype(int)
        sata["a2"] = (df["ma30_slope"] > 0).astype(int)
        sata["a3"] = (df["Close"] > df["ma40"]).astype(int)
        sata["a4"] = (df["ma40_slope"] > 0).astype(int)
        sata["a5"] = (df["ma10"] > df["ma30"]).astype(int)
        sata["a6"] = (df["ma10_slope"] > 0).astype(int)
        sata["a7"] = (mansfield > 0).astype(int)
        sata["a8"] = (rs_slope > 0).astype(int)
        sata["a9"] = (df["High"] > df["High"].shift(1)).astype(int)
        sata["a10"] = (df["Volume"] > df["vol_ma"]).astype(int)

        sata["score"] = sata.sum(axis=1)

        return df, sata, rs

    except Exception as e:
        print(f"[ERROR] {symbol}: {e}")
        return None, None, None


# ==========================================
# LOGIC
# ==========================================
def detect_stage2A(df):
    close = df["Close"]
    ma40 = close.rolling(40).mean()

    price = close.iloc[-1]
    ma40_now = ma40.iloc[-1]
    ma40_prev = ma40.iloc[-5]

    slope40 = ma40_now - ma40_prev

    if price > ma40_now and slope40 > 0:
        base_high = df["High"].rolling(30).max().iloc[-2]
        if price > base_high:
            return True

    return False


def detect_rs_new_high(rs, lookback=60):
    return rs.iloc[-1] >= rs.tail(lookback).max()


# ==========================================
# SCAN
# ==========================================
def scan(symbols):
    results = []

    for i, symbol in enumerate(symbols, 1):
        print(f"[SCAN] {i}/{len(symbols)} {symbol}")

        df, sata, rs = calculate_sata(symbol)

        if df is None:
            continue

        score = int(sata["score"].iloc[-1])

        if (
            detect_stage2A(df)
            and detect_rs_new_high(rs)
            and score >= 7
        ):
            results.append({
                "symbol": symbol,
                "score": score,
                "price": df["Close"].iloc[-1]
            })

    return sorted(results, key=lambda x: x["score"], reverse=True)


# ==========================================
# TELEGRAM
# ==========================================
async def send(results):
    if not results:
        await bot.send_message(chat_id=CHAT_ID, text="❌ No Stage 2A")
        return

    chunk = 20
    pages = math.ceil(len(results) / chunk)

    for i in range(pages):
        text = f"🚀 Stage 2A Scan ({i+1}/{pages})\n"

        if i == 0:
            text += f"พบทั้งหมด {len(results)} หุ้น\n"

        for r in results[i*chunk:(i+1)*chunk]:
            text += f"🟢 {r['symbol']} | SATA {r['score']}/10 | ${r['price']:.2f}\n"

        await bot.send_message(chat_id=CHAT_ID, text=text)


# ==========================================
# MAIN (RUN ONCE)
# ==========================================
async def main():
    print("=== START SCAN ===")

    symbols = get_all_symbols()
    results = scan(symbols)

    print(f"[INFO] Found {len(results)} candidates")

    await send(results)

    print("=== FINISHED ===")


# ==========================================
# START
# ==========================================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    try:
        asyncio.run(main())
    except Exception as e:
        print("[FATAL ERROR]", e)
