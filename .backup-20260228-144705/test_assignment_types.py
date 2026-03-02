#!/usr/bin/env python3
"""
Quick test script to verify assignment type functionality.
Tests FIXED, ROTATE, and AUTO assignment patterns.
"""

import asyncio
import sys
from uuid import UUID
from datetime import datetime, timedelta

# Add the backend to path
sys.path.insert(0, '/Users/jc/dev-2026/AgentIA/family-task-manager/backend')

from app.core.database import get_session_local
from app.models.task_template import AssignmentType
from app.services.task_assignment_service import TaskAssignmentService
from sqlalchemy import text


async def main():
    """Test the assignment types"""
    
    # Family and user IDs from Juan's family
    family_id = UUID("5c373348-f8a4-4638-8b0a-5a312b78131c")
    juan_id = UUID("7fb36848-afa7-4075-bb9b-772a9bc13076")
    mayra_id = UUID("ca13b526-1cb1-4d14-99cf-38a92142385a")
    
    # Test task template IDs
    trastes_id = UUID("d9c6bbc7-7ba7-4bf8-a21b-3ffc8d8f7e1f")  # Lavar los trastes
    barrer_id = UUID("2b85fd8a-ffe1-4039-bb6a-e9baa9b2878d")  # Barrer y trapear
    
    print("=" * 70)
    print("Testing Task Assignment Types")
    print("=" * 70)
    print()
    
    # Create DB session
    async for session in get_session_local():
        try:
            # Update "Lavar los trastes" to ROTATE between Juan and Mayra
            print("1. Setting 'Lavar los trastes' to ROTATE between Juan and Mayra...")
            await session.execute(
                text("""
                    UPDATE task_templates 
                    SET assignment_type = :type,
                        assigned_user_ids = :user_ids
                    WHERE id = :id
                """),
                {
                    "type": AssignmentType.ROTATE.value,
                    "user_ids": f'["{juan_id}", "{mayra_id}"]',
                    "id": trastes_id
                }
            )
            
            # Update "Barrer y trapear" to FIXED to Juan only
            print("2. Setting 'Barrer y trapear' to FIXED (Juan only)...")
            await session.execute(
                text("""
                    UPDATE task_templates 
                    SET assignment_type = :type,
                        assigned_user_ids = :user_ids
                    WHERE id = :id
                """),
                {
                    "type": AssignmentType.FIXED.value,
                    "user_ids": f'["{juan_id}"]',
                    "id": barrer_id
                }
            )
            
            await session.commit()
            print("✓ Task templates updated successfully!")
            print()
            
            # Now test the shuffle algorithm
            print("3. Testing shuffle algorithm...")
            service = TaskAssignmentService(session)
            
            # Get week start (Monday)
            today = datetime.now().date()
            days_since_monday = today.weekday()
            week_start = today - timedelta(days=days_since_monday)
            
            print(f"   Week start: {week_start}")
            print()
            
            # Call shuffle
            result = await service.shuffle_tasks(family_id, week_start)
            
            print("=" * 70)
            print("Shuffle Results:")
            print("=" * 70)
            print(f"Total assignments created: {result['total_assignments']}")
            print(f"Week start: {result['week_start']}")
            print()
            
            # Query the assignments to see the results
            assignments_query = await session.execute(
                text("""
                    SELECT 
                        tt.title,
                        tt.assignment_type,
                        u.name as assigned_to,
                        ta.due_date
                    FROM task_assignments ta
                    JOIN task_templates tt ON ta.template_id = tt.id
                    JOIN users u ON ta.user_id = u.id
                    WHERE ta.week_start = :week_start
                        AND tt.family_id = :family_id
                    ORDER BY tt.title, ta.due_date
                """),
                {"week_start": week_start, "family_id": family_id}
            )
            
            rows = assignments_query.fetchall()
            
            if rows:
                print(f"{'Task':<30} {'Type':<10} {'Assigned To':<20} {'Due Date'}")
                print("-" * 70)
                for row in rows:
                    print(f"{row[0]:<30} {row[1]:<10} {row[2]:<20} {row[3]}")
            else:
                print("No assignments found!")
            
            print()
            print("=" * 70)
            print("Test completed successfully!")
            print("=" * 70)
            
        except Exception as e:
            print(f"ERROR: {e}")
            import traceback
            traceback.print_exc()
            await session.rollback()
        finally:
            await session.close()
            break


if __name__ == "__main__":
    asyncio.run(main())
