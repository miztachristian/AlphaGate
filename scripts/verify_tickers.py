import csv
import requests
import time
import os
import sys

# Path to the universe file
UNIVERSE_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'universe_liquid.csv')
API_KEY = "wDO2pBtdK1VStFX0rmJ4lmHpqfNVOjPa"

def verify_tickers():
    print(f"Reading tickers from {UNIVERSE_FILE}...")
    
    tickers = []
    try:
        with open(UNIVERSE_FILE, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if 'ticker' in row and row['ticker']:
                    tickers.append(row['ticker'])
    except FileNotFoundError:
        print(f"Error: File not found at {UNIVERSE_FILE}")
        return

    print(f"Found {len(tickers)} tickers to verify.")
    
    valid_tickers = []
    invalid_tickers = []
    errors = []

    print("-" * 60)
    print(f"{'Ticker':<10} | {'Status':<10} | {'Name'}")
    print("-" * 60)

    session = requests.Session()

    for i, ticker in enumerate(tickers):
        # clean ticker
        ticker = ticker.strip().upper()
        
        url = f"https://api.polygon.io/v3/reference/tickers/{ticker}?apiKey={API_KEY}"
        
        try:
            response = session.get(url)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'OK' and data.get('results'):
                    res = data['results']
                    if res.get('active'):
                        print(f"{ticker:<10} | {'OK':<10} | {res.get('name')}")
                        valid_tickers.append(ticker)
                    else:
                        print(f"{ticker:<10} | {'INACTIVE':<10} | {res.get('name')}")
                        invalid_tickers.append(f"{ticker} (Inactive)")
                else:
                    print(f"{ticker:<10} | {'NOT FOUND':<10} | -")
                    invalid_tickers.append(f"{ticker} (Not Found)")
            elif response.status_code == 429:
                print(f"{ticker:<10} | {'RATE LMT':<10} | Pausing...")
                time.sleep(1) # Simple backoff
                # Retry once
                response = session.get(url)
                if response.status_code == 200:
                    data = response.json()
                    res = data.get('results', {})
                    if res.get('active'):
                        print(f"{ticker:<10} | {'OK':<10} | {res.get('name')} (After Retry)")
                        valid_tickers.append(ticker)
                    else:
                        print(f"{ticker:<10} | {'INACTIVE':<10} | {res.get('name')}")
                        invalid_tickers.append(f"{ticker} (Inactive)")
                else:
                    print(f"{ticker:<10} | {'FAILED':<10} | Rate limit persist")
                    errors.append(f"{ticker} (Rate Limit)")
            else:
                print(f"{ticker:<10} | {'ERROR':<10} | HTTP {response.status_code}")
                errors.append(f"{ticker} (HTTP {response.status_code})")

        except Exception as e:
            print(f"{ticker:<10} | {'EXCEPT':<10} | {e}")
            errors.append(f"{ticker} (Exception)")
            
        # Polite delay to avoid hammering if not on paid plan
        # time.sleep(0.1) 

    print("-" * 60)
    print(f"Summary:")
    print(f"Total Checked: {len(tickers)}")
    print(f"Valid/Active:  {len(valid_tickers)}")
    print(f"Invalid:       {len(invalid_tickers)}")
    print(f"Errors:        {len(errors)}")
    
    if invalid_tickers:
        print("\nInvalid Tickers:")
        for t in invalid_tickers:
            print(f" - {t}")
            
    if errors:
        print("\nErrors:")
        for e in errors:
            print(f" - {e}")

if __name__ == "__main__":
    verify_tickers()
