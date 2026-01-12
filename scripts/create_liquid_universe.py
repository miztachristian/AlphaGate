"""
Create a liquid universe CSV by verifying tickers against Polygon.io API.
Only includes tickers that return valid data.
"""

import os
import time
import csv
from dotenv import load_dotenv
import requests

load_dotenv()

POLYGON_API_KEY = os.getenv("POLYGON_API_KEY")

# Major liquid US stocks - S&P 500 components and popular stocks
CANDIDATE_TICKERS = [
    # Mega-cap Tech (FAANG+)
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSLA", "NFLX",
    # Semiconductors
    "AMD", "INTC", "AVGO", "QCOM", "TXN", "MU", "AMAT", "LRCX", "KLAC", "MRVL", "ON", "SWKS", "MCHP", "ADI",
    # Software/Cloud
    "CRM", "ORCL", "ADBE", "NOW", "INTU", "SNOW", "PLTR", "PANW", "CRWD", "ZS", "DDOG", "NET", "MDB", "TEAM", "WDAY", "SPLK", "HUBS", "VEEV", "CDNS", "SNPS", "ANSS",
    # Internet/E-commerce
    "SHOP", "SQ", "PYPL", "COIN", "HOOD", "AFRM", "EBAY", "ETSY", "BKNG", "ABNB", "EXPE", "UBER", "LYFT", "DASH", "GRAB",
    # Social/Media/Gaming
    "DIS", "CMCSA", "WBD", "PARA", "NWSA", "EA", "TTWO", "RBLX", "U", "MTCH",
    # Financials - Banks
    "JPM", "BAC", "WFC", "C", "GS", "MS", "USB", "PNC", "TFC", "COF", "AXP", "SCHW", "BK", "STT",
    # Financials - Insurance/Asset Mgmt
    "BRK.B", "BLK", "SPGI", "MCO", "ICE", "CME", "MSCI", "TROW", "AMP", "MET", "PRU", "AIG", "ALL", "TRV", "CB", "PGR", "AFL",
    # Financials - Fintech
    "V", "MA", "FIS", "FISV", "GPN", "ADP", "PAYX",
    # Healthcare - Pharma
    "JNJ", "PFE", "MRK", "LLY", "ABBV", "BMY", "AMGN", "GILD", "BIIB", "REGN", "VRTX", "MRNA", "AZN", "NVO", "SNY",
    # Healthcare - Devices/Services
    "UNH", "CVS", "CI", "ELV", "HCA", "HUM", "CNC", "MCK", "ABC", "CAH", "MDT", "ABT", "SYK", "BSX", "EW", "ZBH", "ISRG", "DXCM", "IDXX", "IQV",
    # Consumer - Retail
    "WMT", "COST", "TGT", "HD", "LOW", "TJX", "ROST", "DG", "DLTR", "BBY", "ORLY", "AZO", "AAP",
    # Consumer - Staples
    "PG", "KO", "PEP", "PM", "MO", "MDLZ", "KHC", "GIS", "K", "CAG", "SJM", "HSY", "HRL", "CPB", "MKC", "CL", "EL", "KMB", "CHD",
    # Consumer - Discretionary
    "NKE", "SBUX", "MCD", "YUM", "DPZ", "CMG", "LULU", "GPS", "ANF", "RL", "TPR", "VFC",
    # Consumer - Auto
    "F", "GM", "TM", "HMC", "RIVN", "LCID", "NIO", "XPEV", "LI",
    # Industrials - Aerospace/Defense
    "BA", "LMT", "RTX", "NOC", "GD", "LHX", "TDG", "HWM", "TXT", "HII",
    # Industrials - Diversified
    "GE", "HON", "MMM", "CAT", "DE", "EMR", "ETN", "ROK", "PH", "ITW", "CMI", "PCAR", "FAST", "GWW", "SWK",
    # Industrials - Transport
    "UPS", "FDX", "UNP", "CSX", "NSC", "DAL", "UAL", "AAL", "LUV", "JBLU",
    # Energy
    "XOM", "CVX", "COP", "EOG", "SLB", "OXY", "PSX", "VLO", "MPC", "PXD", "DVN", "HES", "FANG", "HAL", "BKR", "KMI", "WMB", "OKE", "ET",
    # Materials
    "LIN", "APD", "SHW", "ECL", "DD", "DOW", "NEM", "FCX", "CTVA", "NUE", "STLD", "VMC", "MLM", "ALB", "PPG",
    # REITs
    "AMT", "PLD", "CCI", "EQIX", "PSA", "SPG", "O", "WELL", "DLR", "AVB", "EQR", "VTR", "ARE", "MAA", "UDR",
    # Utilities
    "NEE", "DUK", "SO", "D", "AEP", "SRE", "EXC", "XEL", "WEC", "ES", "ED", "DTE", "AEE", "FE", "PPL", "CEG",
    # Telecom
    "T", "VZ", "TMUS",
    # Other popular/meme stocks
    "GME", "AMC", "BBBY", "BB", "SOFI", "CHPT", "PLUG", "FCEL", "SPCE", "DKNG", "PENN", "WYNN", "LVS", "MGM",
    # Chinese ADRs (popular)
    "BABA", "JD", "PDD", "BIDU", "TCEHY", "TME", "BILI", "IQ", "TAL", "EDU",
    # ETF-like / Popular
    "SPY", "QQQ", "IWM", "DIA", "VTI", "VOO",
]

def verify_ticker(ticker: str) -> dict | None:
    """Check if ticker exists and has recent data on Polygon."""
    url = f"https://api.polygon.io/v3/reference/tickers/{ticker}"
    params = {"apiKey": POLYGON_API_KEY}
    
    try:
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "OK" and data.get("results"):
                result = data["results"]
                return {
                    "ticker": result.get("ticker", ticker),
                    "name": result.get("name", ""),
                    "type": result.get("type", "CS"),
                    "exchange": result.get("primary_exchange", ""),
                }
    except Exception as e:
        print(f"Error checking {ticker}: {e}")
    
    return None


def main():
    print(f"Verifying {len(CANDIDATE_TICKERS)} candidate tickers against Polygon.io...")
    print(f"API Key: {POLYGON_API_KEY[:8]}...")
    
    valid_tickers = []
    failed_tickers = []
    
    for i, ticker in enumerate(CANDIDATE_TICKERS):
        result = verify_ticker(ticker)
        if result:
            valid_tickers.append(result)
            print(f"[{i+1}/{len(CANDIDATE_TICKERS)}] ✓ {ticker}")
        else:
            failed_tickers.append(ticker)
            print(f"[{i+1}/{len(CANDIDATE_TICKERS)}] ✗ {ticker} - not found")
        
        # Rate limit: Polygon free tier is 5 req/min, paid is much higher
        # Using 0.3s delay for paid tier
        time.sleep(0.3)
    
    # Write to CSV
    output_path = "data/universe_liquid.csv"
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["ticker", "name", "type", "exchange"])
        writer.writeheader()
        writer.writerows(valid_tickers)
    
    print(f"\n{'='*60}")
    print(f"Results:")
    print(f"  Valid tickers: {len(valid_tickers)}")
    print(f"  Failed tickers: {len(failed_tickers)}")
    print(f"  Output: {output_path}")
    
    if failed_tickers:
        print(f"\nFailed tickers: {', '.join(failed_tickers)}")


if __name__ == "__main__":
    main()
