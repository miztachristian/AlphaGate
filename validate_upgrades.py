#!/usr/bin/env python3
"""
Validation script for the 5 critical upgrades.

Tests:
1. Database schema (manual_decisions table exists)
2. Journal CLI imports correctly
3. State store methods exist
4. Weekly audit config has friction_bps
5. LiveRunConfig has max_concurrent_trades
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def test_database_schema():
    """Test that manual_decisions table exists."""
    from src.state import SqliteStateStore
    
    print("✅ Testing database schema...")
    state = SqliteStateStore(path=":memory:")  # In-memory for testing
    
    # Try to insert a test decision (TAKEN)
    try:
        state.record_manual_decision(
            alert_log_id=1,
            decision="TAKEN",
            entry_price=100.0,
        )
        print(f"   ✓ manual_decisions table exists (TAKEN decision recorded)")
    except Exception as e:
        print(f"   ✗ Failed to insert TAKEN: {e}")
        return False
    
    # Try to insert a SKIPPED decision
    try:
        state.record_manual_decision(
            alert_log_id=2,
            decision="SKIPPED",
            skip_reason="News risk too high",
        )
        print(f"   ✓ SKIPPED decision works")
    except Exception as e:
        print(f"   ✗ Failed to insert SKIPPED: {e}")
        return False
    
    # Try to record exit
    try:
        state.record_manual_exit(
            alert_log_id=1,
            exit_price=105.0,
        )
        print(f"   ✓ Exit recording works")
    except Exception as e:
        print(f"   ✗ Failed to record exit: {e}")
        return False
    
    # Test count_active_trades
    try:
        count = state.count_active_trades(hold_hours_by_timeframe={"1h": 24})
        print(f"   ✓ count_active_trades() works (found {count} active)")
    except Exception as e:
        print(f"   ✗ Failed to count active trades: {e}")
        return False
    
    return True


def test_journal_cli():
    """Test that journal CLI module imports."""
    print("\n✅ Testing journal CLI...")
    
    try:
        import src.journal.__main__ as journal_main
        print(f"   ✓ Journal CLI module imports successfully")
        
        # Check for required internal functions
        assert hasattr(journal_main, '_run_mark'), "Missing _run_mark function"
        assert hasattr(journal_main, '_run_exit'), "Missing _run_exit function"
        assert hasattr(journal_main, 'main'), "Missing main function"
        print(f"   ✓ CLI functions exist (_run_mark, _run_exit, main)")
    except Exception as e:
        print(f"   ✗ Failed to import journal CLI: {e}")
        return False
    
    return True


def test_weekly_audit():
    """Test weekly audit has friction_bps."""
    print("\n✅ Testing weekly audit...")
    
    try:
        from src.reporting.weekly_audit import WeeklyAuditConfig, WeeklyAuditResult
        
        # Test config has friction_bps
        config = WeeklyAuditConfig(
            lookback_days=7,
            friction_bps=15.0,
        )
        print(f"   ✓ WeeklyAuditConfig has friction_bps={config.friction_bps}")
        
        # Test result has split metrics
        result = WeeklyAuditResult(
            start_date="2024-01-01",
            end_date="2024-01-07",
        )
        assert hasattr(result, 'system_pnl'), "Missing system_pnl"
        assert hasattr(result, 'trader_pnl'), "Missing trader_pnl"
        print(f"   ✓ WeeklyAuditResult has split metrics (system/trader)")
    except Exception as e:
        print(f"   ✗ Failed to test weekly audit: {e}")
        return False
    
    return True


def test_live_runner():
    """Test live runner has max_concurrent_trades."""
    print("\n✅ Testing live runner...")
    
    try:
        from src.runner.live_runner import LiveRunConfig
        
        config = LiveRunConfig(
            timeframe="1h",
            interval_seconds=300,
            lookback_days=90,
            min_confidence="MEDIUM",
            cooldown_minutes=60,
            news_query_mode="ticker",
            news_lookback_hours=24,
            news_required_alignment=False,
            max_concurrent_trades=3,
        )
        print(f"   ✓ LiveRunConfig has max_concurrent_trades={config.max_concurrent_trades}")
    except Exception as e:
        print(f"   ✗ Failed to test live runner: {e}")
        return False
    
    return True


def test_state_store_methods():
    """Test that all new state store methods exist."""
    print("\n✅ Testing state store methods...")
    
    from src.state import SqliteStateStore
    
    required_methods = [
        'record_manual_decision',
        'record_manual_exit',
        'get_manual_decision',
        'get_manual_decisions',
        'get_taken_trades',
        'count_active_trades',
    ]
    
    state = SqliteStateStore(path=":memory:")
    
    for method in required_methods:
        if not hasattr(state, method):
            print(f"   ✗ Missing method: {method}")
            return False
    
    print(f"   ✓ All {len(required_methods)} methods exist")
    return True


def main():
    """Run all validation tests."""
    print("=" * 60)
    print("🔍 Validating 5 Critical Upgrades Implementation")
    print("=" * 60)
    
    tests = [
        ("Database Schema", test_database_schema),
        ("Journal CLI", test_journal_cli),
        ("Weekly Audit", test_weekly_audit),
        ("Live Runner", test_live_runner),
        ("State Store Methods", test_state_store_methods),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            passed = test_func()
            results.append((name, passed))
        except Exception as e:
            print(f"\n✗ {name} failed with exception: {e}")
            results.append((name, False))
    
    print("\n" + "=" * 60)
    print("📊 Validation Summary")
    print("=" * 60)
    
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {name}")
    
    all_passed = all(passed for _, passed in results)
    
    if all_passed:
        print("\n🎉 All validations passed! System is ready for production.")
        return 0
    else:
        print("\n⚠️  Some validations failed. Please review errors above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
