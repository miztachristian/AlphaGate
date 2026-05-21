"""
Manual Trade Journal CLI

Usage:
    # Mark an alert as taken
    python -m src.journal mark --alert-id 123 --taken --entry 187.62 --stop 184.90
    
    # Mark an alert as skipped
    python -m src.journal mark --alert-id 123 --skipped --reason NEWS_RISK
    
    # Log an exit for a taken trade
    python -m src.journal exit --alert-id 123 --exit-price 192.50
"""

from __future__ import annotations

import argparse
from datetime import datetime
from typing import Optional

from ..state import SqliteStateStore


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.journal",
        description="Manual trade journal - mark alerts as TAKEN/SKIPPED and log exits.",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # ===== MARK command =====
    mark = sub.add_parser("mark", help="Mark an alert as TAKEN or SKIPPED")
    mark.add_argument(
        "--db",
        default="state.db",
        help="Path to SQLite DB (default: state.db)",
    )
    mark.add_argument(
        "--alert-id",
        type=int,
        required=True,
        help="alerts_log.id from the Telegram message",
    )

    g = mark.add_mutually_exclusive_group(required=True)
    g.add_argument("--taken", action="store_true", help="Mark alert as taken")
    g.add_argument("--skipped", action="store_true", help="Mark alert as skipped")

    mark.add_argument(
        "--entry",
        type=float,
        help="Actual entry fill price (required if --taken)",
    )
    mark.add_argument("--stop", type=float, help="Your stop price (optional)")
    mark.add_argument(
        "--size-usd",
        type=float,
        help="Position size in USD (optional)",
    )
    mark.add_argument(
        "--reason",
        help="Skip reason tag (required if --skipped). Examples: NEWS_RISK, SPREAD_WIDE, LOW_LIQUIDITY, NO_SETUP_CONFIRM",
    )
    mark.add_argument("--note", help="Freeform note (optional)")

    # ===== EXIT command =====
    exit_cmd = sub.add_parser("exit", help="Log exit price/time for a taken trade")
    exit_cmd.add_argument(
        "--db",
        default="state.db",
        help="Path to SQLite DB (default: state.db)",
    )
    exit_cmd.add_argument(
        "--alert-id",
        type=int,
        required=True,
        help="alerts_log.id of the trade to close",
    )
    exit_cmd.add_argument(
        "--exit-price",
        type=float,
        required=True,
        help="Actual exit fill price",
    )

    return parser


def _run_mark(ns: argparse.Namespace) -> int:
    """Handle 'mark' command."""
    decision_ts = datetime.utcnow().isoformat()
    state = SqliteStateStore(path=ns.db)

    if ns.taken:
        if ns.entry is None:
            raise SystemExit("--entry is required when using --taken")
        
        state.record_manual_decision(
            alert_log_id=ns.alert_id,
            decision="TAKEN",
            decision_ts_utc=decision_ts,
            entry_ts_utc=decision_ts,
            entry_price=float(ns.entry),
            stop_price=float(ns.stop) if ns.stop is not None else None,
            size_usd=float(ns.size_usd) if ns.size_usd is not None else None,
            skip_reason=None,
            note=ns.note,
        )
        print(f"✅ Marked alert_id={ns.alert_id} as TAKEN (entry=${ns.entry:.2f})")
        return 0

    # skipped
    if not (ns.reason or "").strip():
        raise SystemExit("--reason is required when using --skipped")

    state.record_manual_decision(
        alert_log_id=ns.alert_id,
        decision="SKIPPED",
        decision_ts_utc=decision_ts,
        entry_ts_utc=None,
        entry_price=None,
        stop_price=None,
        size_usd=None,
        skip_reason=ns.reason.strip().upper(),
        note=ns.note,
    )
    print(f"✅ Marked alert_id={ns.alert_id} as SKIPPED ({ns.reason.strip().upper()})")
    return 0


def _run_exit(ns: argparse.Namespace) -> int:
    """Handle 'exit' command."""
    state = SqliteStateStore(path=ns.db)
    
    # Verify the trade exists and was taken
    decision = state.get_manual_decision(ns.alert_id)
    if not decision:
        raise SystemExit(f"❌ No manual decision found for alert_id={ns.alert_id}")
    
    if decision["decision"] != "TAKEN":
        raise SystemExit(f"❌ Alert {ns.alert_id} was not marked as TAKEN (decision={decision['decision']})")
    
    if decision["exit_price"] is not None:
        print(f"⚠️  Alert {ns.alert_id} already has exit_price=${decision['exit_price']:.2f}. Overwriting.")
    
    state.record_manual_exit(
        alert_log_id=ns.alert_id,
        exit_price=float(ns.exit_price),
        exit_ts_utc=datetime.utcnow().isoformat(),
    )
    
    # Calculate quick P&L
    entry_price = decision["entry_price"]
    pnl_pct = ((ns.exit_price - entry_price) / entry_price) * 100
    emoji = "🟢" if pnl_pct > 0 else "🔴" if pnl_pct < 0 else "⚪"
    
    print(f"✅ Logged exit for alert_id={ns.alert_id}")
    print(f"   Entry: ${entry_price:.2f} → Exit: ${ns.exit_price:.2f}")
    print(f"   {emoji} P&L: {pnl_pct:+.2f}%")
    return 0


def main() -> int:
    parser = _build_parser()
    ns = parser.parse_args()

    try:
        if ns.command == "mark":
            return _run_mark(ns)
        elif ns.command == "exit":
            return _run_exit(ns)
        else:
            raise SystemExit(f"Unknown command: {ns.command}")
    except Exception as e:
        print(f"❌ Error: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
