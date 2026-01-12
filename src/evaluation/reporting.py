"""Reporting module for outcome analysis.

Generates summary reports by:
- Score buckets (0-40, 40-60, 60-80, 80-100)
- Regime breakdown (trend_regime x vol_regime)

Outputs CSV files to reports/ directory.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd


@dataclass
class BucketStats:
    """Statistics for a score bucket."""
    bucket: str
    count: int
    hit_rate: Dict[int, float]  # horizon -> hit rate
    median_forward_return: Dict[int, float]
    median_mfe: Dict[int, float]
    median_mae: Dict[int, float]


@dataclass
class RegimeStats:
    """Statistics for a regime combination."""
    trend_regime: str
    vol_regime: str
    count: int
    hit_rate_primary: float  # Hit rate at primary horizon
    primary_horizon: int


def _get_score_bucket(score: Optional[int]) -> str:
    """Map score to bucket label."""
    if score is None:
        return "N/A"
    if score < 40:
        return "0-40"
    elif score < 60:
        return "40-60"
    elif score < 80:
        return "60-80"
    else:
        return "80-100"


def _load_outcomes(db_path: str, status_filter: Optional[str] = None) -> List[Dict]:
    """Load outcome records from database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    query = "SELECT * FROM alert_outcomes"
    params = []
    
    if status_filter:
        query += " WHERE evaluation_status = ?"
        params.append(status_filter)
    
    query += " ORDER BY ts_utc DESC"
    
    try:
        rows = conn.execute(query, params).fetchall()
    except sqlite3.OperationalError:
        # Table doesn't exist
        return []
    finally:
        conn.close()
    
    outcomes = []
    for row in rows:
        outcome = dict(row)
        # Parse JSON fields
        for field in ["forward_returns_json", "mfe_json", "mae_json", "hit_json"]:
            if outcome.get(field):
                try:
                    # Convert string keys to int for horizon fields
                    parsed = json.loads(outcome[field])
                    outcome[field.replace("_json", "")] = {
                        int(k): v for k, v in parsed.items()
                    }
                except (json.JSONDecodeError, ValueError):
                    outcome[field.replace("_json", "")] = {}
            else:
                outcome[field.replace("_json", "")] = {}
        outcomes.append(outcome)
    
    return outcomes


def compute_bucket_stats(
    outcomes: List[Dict],
    horizons: Optional[List[int]] = None,
) -> Dict[str, BucketStats]:
    """
    Compute statistics grouped by score bucket.
    
    Args:
        outcomes: List of outcome records
        horizons: List of horizons to report (auto-detect if None)
        
    Returns:
        Dict mapping bucket label to BucketStats
    """
    if not outcomes:
        return {}
    
    # Auto-detect horizons from data
    if horizons is None:
        all_horizons = set()
        for o in outcomes:
            all_horizons.update(o.get("forward_returns", {}).keys())
        horizons = sorted(all_horizons)
    
    if not horizons:
        return {}
    
    # Group by bucket
    by_bucket = defaultdict(list)
    for o in outcomes:
        bucket = _get_score_bucket(o.get("score"))
        by_bucket[bucket].append(o)
    
    stats = {}
    for bucket, group in by_bucket.items():
        hit_rates = {}
        median_fwd = {}
        median_mfe = {}
        median_mae = {}
        
        for h in horizons:
            # Hit rate
            hits = [o["hit"].get(h) for o in group if o.get("hit", {}).get(h) is not None]
            if hits:
                hit_rates[h] = sum(1 for h in hits if h) / len(hits) * 100
            else:
                hit_rates[h] = 0.0
            
            # Forward returns
            fwd_returns = [
                o["forward_returns"].get(h) 
                for o in group 
                if o.get("forward_returns", {}).get(h) is not None
            ]
            if fwd_returns:
                median_fwd[h] = sorted(fwd_returns)[len(fwd_returns) // 2]
            else:
                median_fwd[h] = 0.0
            
            # MFE
            mfe_vals = [
                o["mfe"].get(h) 
                for o in group 
                if o.get("mfe", {}).get(h) is not None
            ]
            if mfe_vals:
                median_mfe[h] = sorted(mfe_vals)[len(mfe_vals) // 2]
            else:
                median_mfe[h] = 0.0
            
            # MAE
            mae_vals = [
                o["mae"].get(h) 
                for o in group 
                if o.get("mae", {}).get(h) is not None
            ]
            if mae_vals:
                median_mae[h] = sorted(mae_vals)[len(mae_vals) // 2]
            else:
                median_mae[h] = 0.0
        
        stats[bucket] = BucketStats(
            bucket=bucket,
            count=len(group),
            hit_rate=hit_rates,
            median_forward_return=median_fwd,
            median_mfe=median_mfe,
            median_mae=median_mae,
        )
    
    return stats


def compute_regime_stats(
    outcomes: List[Dict],
    primary_horizon: int = 24,
) -> List[RegimeStats]:
    """
    Compute statistics grouped by regime combination.
    
    Args:
        outcomes: List of outcome records
        primary_horizon: Primary horizon for hit rate calculation
        
    Returns:
        List of RegimeStats for each regime combination
    """
    if not outcomes:
        return []
    
    # Group by regime combination
    by_regime = defaultdict(list)
    for o in outcomes:
        trend = o.get("trend_regime") or "UNKNOWN"
        vol = o.get("vol_regime") or "UNKNOWN"
        key = (trend, vol)
        by_regime[key].append(o)
    
    stats = []
    for (trend, vol), group in by_regime.items():
        # Hit rate at primary horizon
        hits = [
            o["hit"].get(primary_horizon) 
            for o in group 
            if o.get("hit", {}).get(primary_horizon) is not None
        ]
        hit_rate = (sum(1 for h in hits if h) / len(hits) * 100) if hits else 0.0
        
        stats.append(RegimeStats(
            trend_regime=trend,
            vol_regime=vol,
            count=len(group),
            hit_rate_primary=hit_rate,
            primary_horizon=primary_horizon,
        ))
    
    # Sort by count descending
    stats.sort(key=lambda x: x.count, reverse=True)
    return stats


def generate_reports(
    db_path: str,
    output_dir: str = "reports",
    primary_horizon: int = 24,
    verbose: bool = True,
) -> Tuple[str, str]:
    """
    Generate summary reports and write CSVs.
    
    Args:
        db_path: Path to SQLite database
        output_dir: Directory for output CSV files
        primary_horizon: Primary horizon for regime stats
        verbose: Print reports to console
        
    Returns:
        Tuple of (bucket_csv_path, regime_csv_path)
    """
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)
    
    # Load completed outcomes
    outcomes = _load_outcomes(db_path, status_filter="COMPLETE")
    
    if verbose:
        print(f"\n{'='*70}")
        print("OUTCOME ANALYSIS REPORT")
        print(f"{'='*70}")
        print(f"Database: {db_path}")
        print(f"Complete outcomes: {len(outcomes)}")
        print(f"Report generated: {datetime.utcnow().isoformat()}")
    
    if not outcomes:
        if verbose:
            print("\nNo completed outcomes to report.")
        return "", ""
    
    # Bucket stats
    bucket_stats = compute_bucket_stats(outcomes)
    
    if verbose and bucket_stats:
        print(f"\n{'='*70}")
        print("OUTCOMES BY SCORE BUCKET")
        print(f"{'='*70}")
        
        # Get horizons for header
        first_bucket = next(iter(bucket_stats.values()))
        horizons = sorted(first_bucket.hit_rate.keys())
        
        # Header
        header = f"{'Bucket':<10} {'Count':>8}"
        for h in horizons:
            header += f" {'Hit@'+str(h):>8} {'FwdRet@'+str(h):>10} {'MFE@'+str(h):>8} {'MAE@'+str(h):>8}"
        print(header)
        print("-" * len(header))
        
        for bucket in ["0-40", "40-60", "60-80", "80-100", "N/A"]:
            if bucket not in bucket_stats:
                continue
            s = bucket_stats[bucket]
            line = f"{s.bucket:<10} {s.count:>8}"
            for h in horizons:
                hit_r = s.hit_rate.get(h, 0)
                fwd_r = s.median_forward_return.get(h, 0)
                mfe = s.median_mfe.get(h, 0)
                mae = s.median_mae.get(h, 0)
                line += f" {hit_r:>7.1f}% {fwd_r:>9.2f}% {mfe:>7.2f}% {mae:>7.2f}%"
            print(line)
    
    # Regime stats
    regime_stats = compute_regime_stats(outcomes, primary_horizon)
    
    if verbose and regime_stats:
        print(f"\n{'='*70}")
        print(f"OUTCOMES BY REGIME (Hit Rate @ {primary_horizon}h)")
        print(f"{'='*70}")
        
        header = f"{'Trend':<15} {'Vol':<10} {'Count':>8} {'Hit Rate':>10}"
        print(header)
        print("-" * len(header))
        
        for s in regime_stats:
            print(f"{s.trend_regime:<15} {s.vol_regime:<10} {s.count:>8} {s.hit_rate_primary:>9.1f}%")
    
    # Write CSVs
    bucket_csv = output_path / "outcomes_by_bucket.csv"
    regime_csv = output_path / "outcomes_by_regime.csv"
    
    # Bucket CSV
    if bucket_stats:
        rows = []
        for bucket in ["0-40", "40-60", "60-80", "80-100", "N/A"]:
            if bucket not in bucket_stats:
                continue
            s = bucket_stats[bucket]
            row = {"bucket": s.bucket, "count": s.count}
            for h in sorted(s.hit_rate.keys()):
                row[f"hit_rate_{h}h"] = round(s.hit_rate.get(h, 0), 2)
                row[f"median_fwd_return_{h}h"] = round(s.median_forward_return.get(h, 0), 4)
                row[f"median_mfe_{h}h"] = round(s.median_mfe.get(h, 0), 4)
                row[f"median_mae_{h}h"] = round(s.median_mae.get(h, 0), 4)
            rows.append(row)
        
        df = pd.DataFrame(rows)
        df.to_csv(bucket_csv, index=False)
        if verbose:
            print(f"\nWrote: {bucket_csv}")
    
    # Regime CSV
    if regime_stats:
        rows = []
        for s in regime_stats:
            rows.append({
                "trend_regime": s.trend_regime,
                "vol_regime": s.vol_regime,
                "count": s.count,
                f"hit_rate_{s.primary_horizon}h": round(s.hit_rate_primary, 2),
            })
        
        df = pd.DataFrame(rows)
        df.to_csv(regime_csv, index=False)
        if verbose:
            print(f"Wrote: {regime_csv}")
    
    return str(bucket_csv), str(regime_csv)


def main():
    """CLI entry point for reporting."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Generate outcome analysis reports",
    )
    parser.add_argument(
        "--db-path",
        default="alerts_log.db",
        help="Path to SQLite database",
    )
    parser.add_argument(
        "--output-dir",
        default="reports",
        help="Output directory for CSV files",
    )
    parser.add_argument(
        "--primary-horizon",
        type=int,
        default=24,
        help="Primary horizon for regime stats (hours)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress console output",
    )
    
    args = parser.parse_args()
    
    generate_reports(
        db_path=args.db_path,
        output_dir=args.output_dir,
        primary_horizon=args.primary_horizon,
        verbose=not args.quiet,
    )


if __name__ == "__main__":
    main()
