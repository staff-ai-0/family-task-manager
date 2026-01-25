#!/usr/bin/env python3
"""Quick startup test for the Family Task Manager application"""

import asyncio
import sys
from app.core.database import engine
from app.main import app
from sqlalchemy import text


async def test_database_connection():
    """Test database connection"""
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            result.fetchone()
        print("✓ Database connection successful")
        return True
    except Exception as e:
        print(f"✗ Database connection failed: {e}")
        return False


async def test_tables_exist():
    """Test that all tables were created"""
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text("""
                SELECT table_name FROM information_schema.tables 
                WHERE table_schema = 'public'
                ORDER BY table_name
            """)
            )
            tables = [row[0] for row in result.fetchall()]

        print(f"✓ Found {len(tables)} tables:")
        for table in tables:
            print(f"  - {table}")

        # Expected tables
        expected = [
            "users",
            "families",
            "tasks",
            "rewards",
            "consequences",
            "point_transactions",
            "email_verification_tokens",
            "password_reset_tokens",
        ]
        missing = [t for t in expected if t not in tables]

        if missing:
            print(f"✗ Missing tables: {missing}")
            return False

        print("✓ All expected tables exist")
        return True
    except Exception as e:
        print(f"✗ Table check failed: {e}")
        return False

        print("✓ All expected tables exist")
        return True
    except Exception as e:
        print(f"✗ Table check failed: {e}")
        return False


async def main():
    """Run all tests"""
    print("=" * 60)
    print("Family Task Manager - Startup Test")
    print("=" * 60)
    print()

    # Test 1: App imports
    print("Test 1: Application Import")
    print(f"✓ App version: {app.version}")
    print(f"✓ App title: {app.title}")
    print()

    # Test 2: Database connection
    print("Test 2: Database Connection")
    db_ok = await test_database_connection()
    print()

    # Test 3: Tables exist
    print("Test 3: Database Schema")
    tables_ok = await test_tables_exist()
    print()

    # Summary
    print("=" * 60)
    if db_ok and tables_ok:
        print("✓ ALL TESTS PASSED - Application is ready!")
        print()
        print("You can now start the server with:")
        print("  source venv/bin/activate")
        print("  uvicorn app.main:app --reload")
        print()
        print("Then visit: http://localhost:8000/docs")
        return 0
    else:
        print("✗ SOME TESTS FAILED - Check errors above")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
