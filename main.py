"""
Trading Application - Main Entry Point

A Python-based trading application that analyzes technical indicators
and generates high-probability long/short trading signals for stocks.
"""

import argparse
import sys
from colorama import init, Fore, Style
from datetime import datetime
from dotenv import load_dotenv

from src.strategy.engine import StrategyEngine
from src.marketdata.stocks import fetch_stock_ohlcv

# Load environment variables
load_dotenv()

# Initialize colorama for colored terminal output
init(autoreset=True)


def print_banner():
    """Print application banner."""
    print(Fore.CYAN + "=" * 70)
    print(Fore.CYAN + "  📊 STOCK TRADING ANALYZER")
    print(Fore.CYAN + "  Multi-Indicator Trading Signal Generator")
    print(Fore.CYAN + "=" * 70)
    print()


def main():
    """Main application entry point."""
    parser = argparse.ArgumentParser(
        description='Stock Trading Analyzer - Generate high-probability trade signals'
    )
    
    parser.add_argument(
        '--symbol',
        type=str,
        default='AAPL',
        help='Stock ticker symbol (default: AAPL)'
    )
    
    parser.add_argument(
        '--timeframe',
        type=str,
        default='1h',
        choices=['15m', '1h', '4h', '1d'],
        help='Chart timeframe (default: 1h)'
    )
    
    parser.add_argument(
        '--days',
        type=int,
        default=60,
        help='Number of days of historical data (default: 60)'
    )
    
    parser.add_argument(
        '--save',
        action='store_true',
        help='Save fetched data to CSV file'
    )
    
    parser.add_argument(
        '--config',
        type=str,
        default='config.yaml',
        help='Path to configuration file (default: config.yaml)'
    )
    
    parser.add_argument(
        '--live',
        action='store_true',
        help='Run in live mode (continuous monitoring)'
    )
    
    args = parser.parse_args()
    
    try:
        # Print banner
        print_banner()
        
        # Initialize strategy engine
        print(f"{Fore.YELLOW}⚙️  Initializing strategy engine...")
        engine = StrategyEngine(args.config)
        
        # Fetch market data
        print(f"{Fore.YELLOW}📡 Fetching stock data...")
        print(f"   Symbol: {args.symbol}")
        print(f"   Timeframe: {args.timeframe}")
        print(f"   Days: {args.days}")
        print()
        
        df = fetch_stock_ohlcv(
            ticker=args.symbol,
            interval=args.timeframe,
            lookback_days=args.days
        )
        
        if df is None or len(df) == 0:
            print(f"{Fore.RED}❌ Failed to fetch stock data for {args.symbol}")
            sys.exit(1)
        
        print(f"{Fore.GREEN}✅ Data fetched successfully ({len(df)} candles)")
        print(f"   Date range: {df.index[0]} to {df.index[-1]}")
        print()
        
        # Save data if requested
        if args.save:
            filename = f"data/{args.symbol}_{args.timeframe}.csv"
            df.to_csv(filename)
            print(f"{Fore.GREEN}💾 Data saved to {filename}")
        
        # Analyze market
        print(f"{Fore.YELLOW}🔍 Analyzing market conditions...")
        print()
        
        analysis = engine.analyze_current_market(df)
        
        # Print analysis report
        report = engine.format_analysis_report(analysis)
        
        # Color code the signal
        signal = analysis['signal']['final_signal']
        if signal == 'LONG':
            print(Fore.GREEN + report)
        elif signal == 'SHORT':
            print(Fore.RED + report)
        else:
            print(Fore.YELLOW + report)
        
        # Live mode
        if args.live:
            print(f"\n{Fore.CYAN}🔄 Live mode enabled. Monitoring every 60 seconds...")
            print(f"{Fore.CYAN}Press Ctrl+C to stop.\n")
            
            import time
            while True:
                try:
                    time.sleep(60)  # Wait 60 seconds
                    
                    # Fetch fresh data
                    df = fetch_stock_ohlcv(
                        ticker=args.symbol,
                        interval=args.timeframe,
                        lookback_days=args.days
                    )
                    
                    # Analyze
                    analysis = engine.analyze_current_market(df)
                    
                    # Print timestamp and signal
                    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    signal = analysis['signal']['final_signal']
                    confidence = analysis['signal']['confidence']
                    price = df['close'].iloc[-1]
                    
                    if signal == 'LONG':
                        print(f"{Fore.GREEN}[{timestamp}] {args.symbol} ${price:.2f} - LONG ({confidence})")
                    elif signal == 'SHORT':
                        print(f"{Fore.RED}[{timestamp}] {args.symbol} ${price:.2f} - SHORT ({confidence})")
                    else:
                        print(f"{Fore.YELLOW}[{timestamp}] {args.symbol} ${price:.2f} - NEUTRAL")
                
                except KeyboardInterrupt:
                    print(f"\n{Fore.CYAN}👋 Stopping live monitoring...")
                    break
        
        print(f"\n{Fore.CYAN}✨ Analysis complete!")
        
    except FileNotFoundError as e:
        print(f"{Fore.RED}❌ Configuration file not found: {e}")
        sys.exit(1)
    
    except Exception as e:
        print(f"{Fore.RED}❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
