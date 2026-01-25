"""
Tests for Task Management
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime


class TestTaskCreation:
    """Test task creation"""

    @pytest.mark.asyncio
    async def test_parent_create_task(
        self, client: AsyncClient, test_parent_user, test_child_user
    ):
        """Test parent can create a task"""
        # Login as parent
        login_response = await client.post(
            "/api/auth/login",
            json={"email": test_parent_user.email, "password": "password123"},
        )
        token = login_response.json()["access_token"]

        # Create task
        response = await client.post(
            "/api/tasks/",
            json={
                "title": "Do Homework",
                "description": "Complete math assignment",
                "points": 50,
                "is_default": True,
                "assigned_to": str(test_child_user.id),
                "frequency": "daily",
                "due_date": datetime.now().isoformat(),
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        if response.status_code != 201:
            print(f"Response: {response.json()}")
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "Do Homework"
        assert data["points"] == 50
        assert data["is_default"] is True

    @pytest.mark.asyncio
    async def test_child_cannot_create_task(self, client: AsyncClient, test_child_user):
        """Test child cannot create tasks"""
        # Login as child
        login_response = await client.post(
            "/api/auth/login",
            json={"email": test_child_user.email, "password": "password123"},
        )
        token = login_response.json()["access_token"]

        # Try to create task
        response = await client.post(
            "/api/tasks/",
            json={
                "title": "My Task",
                "description": "Test",
                "points": 10,
                "is_default": False,
                "assigned_to": str(test_child_user.id),
                "frequency": "daily",
                "due_date": datetime.now().isoformat(),
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 403


class TestTaskCompletion:
    """Test task completion flow"""

    @pytest.mark.asyncio
    async def test_complete_task_awards_points(
        self, client: AsyncClient, test_child_user, test_task, db_session: AsyncSession
    ):
        """Test completing a task awards points to the user"""
        initial_points = test_child_user.points

        # Login as child
        login_response = await client.post(
            "/api/auth/login",
            json={"email": test_child_user.email, "password": "password123"},
        )
        token = login_response.json()["access_token"]

        # Complete task
        response = await client.patch(
            f"/api/tasks/{test_task.id}/complete",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["completed_at"] is not None

        # Refresh user to check points
        await db_session.refresh(test_child_user)
        assert test_child_user.points == initial_points + test_task.points

    @pytest.mark.asyncio
    async def test_cannot_complete_others_task(
        self, client: AsyncClient, test_parent_user, test_task
    ):
        """Test user cannot complete tasks assigned to others"""
        # Login as parent (task is assigned to child)
        login_response = await client.post(
            "/api/auth/login",
            json={"email": test_parent_user.email, "password": "password123"},
        )
        token = login_response.json()["access_token"]

        # Try to complete child's task
        response = await client.patch(
            f"/api/tasks/{test_task.id}/complete",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 403


class TestTaskListing:
    """Test task listing and filtering"""

    @pytest.mark.asyncio
    async def test_list_own_tasks(
        self, client: AsyncClient, test_child_user, test_task
    ):
        """Test user can list their own tasks"""
        # Login
        login_response = await client.post(
            "/api/auth/login",
            json={"email": test_child_user.email, "password": "password123"},
        )
        token = login_response.json()["access_token"]

        # Get tasks
        response = await client.get(
            "/api/tasks/", headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        tasks = response.json()
        assert len(tasks) >= 1
        assert any(task["id"] == str(test_task.id) for task in tasks)

    @pytest.mark.asyncio
    async def test_filter_tasks_by_status(self, client: AsyncClient, test_child_user):
        """Test filtering tasks by status"""
        # Login
        login_response = await client.post(
            "/api/auth/login",
            json={"email": test_child_user.email, "password": "password123"},
        )
        token = login_response.json()["access_token"]

        # Get pending tasks
        response = await client.get(
            "/api/tasks/?status=pending", headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        tasks = response.json()
        assert all(task["status"] == "pending" for task in tasks)
