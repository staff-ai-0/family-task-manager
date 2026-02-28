# Bug Fix: Backend HTTP Method Mismatches

**Date**: Feb 25, 2026  
**Issue**: Frontend was using incorrect HTTP methods for backend API calls  
**Status**: ✅ Fixed and Deployed

## Problem Summary

The frontend code in `members.astro` was calling backend endpoints with incorrect HTTP methods, causing "Method Not Allowed" errors when trying to:
1. Activate/deactivate users
2. Adjust user points

## Root Causes

### Issue 1: Activate/Deactivate Users
- **Frontend**: Using `POST` method
- **Backend**: Requires `PUT` method
- **Affected endpoints**:
  - `/api/users/{user_id}/activate`
  - `/api/users/{user_id}/deactivate`

### Issue 2: Adjust Points
- **Frontend**: Using wrong endpoint `/api/users/{user_id}/points` (GET only)
- **Backend**: Requires `/api/users/points/adjust` with `POST`
- **Missing**: `user_id` in request body
- **Missing validation**: `reason` field is required but wasn't validated

## Changes Made

### File: `frontend/src/pages/parent/members.astro`

#### Change 1: Fixed activate/deactivate method (Line 30)
```diff
const { ok, error } = await apiFetch(`/api/users/${memberId}/${endpoint}`, {
-  method: "POST",
+  method: "PUT",
   token,
});
```

#### Change 2: Fixed adjust points endpoint and payload (Lines 35-49)
```diff
- const { ok, error } = await apiFetch(`/api/users/${memberId}/points`, {
+ const { ok, error } = await apiFetch(`/api/users/points/adjust`, {
    method: "POST",
    token,
-   body: JSON.stringify({ points, reason }),
+   body: JSON.stringify({ 
+     user_id: memberId, 
+     points, 
+     reason 
+   }),
  });
```

Added validation for required `reason` field:
```diff
+ if (!reason || reason.trim() === "") {
+   errorMsg = "Reason is required for point adjustment";
+ } else {
    const { ok, error } = await apiFetch(...);
+ }
```

#### Change 3: Made reason field required in HTML form (Line 189)
```diff
<input
  name="reason"
  placeholder={t(lang, "pm_reason_placeholder")}
+ required
  class="flex-1 px-2 py-1.5 rounded-lg border border-slate-300 text-xs focus:ring-1 focus:ring-violet-500 outline-none"
/>
```

## Backend API Reference

### Correct endpoints and methods:

| Action | Method | Endpoint | Request Body |
|--------|--------|----------|--------------|
| Activate user | `PUT` | `/api/users/{user_id}/activate` | None |
| Deactivate user | `PUT` | `/api/users/{user_id}/deactivate` | None |
| Adjust points | `POST` | `/api/users/points/adjust` | `{user_id, points, reason}` |

### Schema: `ParentAdjustment`
```json
{
  "user_id": "uuid (required)",
  "points": "integer [-1000 to 1000] (required)",
  "reason": "string [1-500 chars] (required)"
}
```

## Testing

### How to Test
1. Login as parent: http://localhost:3003/login
   - Email: `mom@demo.com`
   - Password: `password123`

2. Navigate to Members page: http://localhost:3003/parent/members

3. **Test Activate/Deactivate**:
   - Click "Deactivate" on any active member
   - Should work without "Method Not Allowed" error
   - Member should show as inactive
   - Click "Activate" to reactivate

4. **Test Adjust Points**:
   - Enter points value (e.g., `50` or `-20`)
   - Enter reason (e.g., "Bonus for good behavior")
   - Click "Apply"
   - Should see success message
   - Member's points should update

### Expected Results
✅ No "Method Not Allowed" errors  
✅ Activate/deactivate works correctly  
✅ Point adjustments work correctly  
✅ Validation error if reason is empty  

## Deployment

```bash
# Rebuild and restart frontend
docker-compose up -d --build frontend

# Verify services are running
docker-compose ps
```

## Related Files

- `frontend/src/pages/parent/members.astro` - Fixed HTTP methods and endpoints
- Backend schemas: `backend/app/schemas/user.py` - ParentAdjustment schema
- Backend routes: `backend/app/api/routes/users.py` - User management endpoints

## Lessons Learned

1. **Always verify backend API methods** before implementing frontend calls
2. **Use OpenAPI/Swagger docs** (`http://localhost:8002/docs`) to verify endpoints
3. **Validate required fields** on both frontend and backend
4. **Test all CRUD operations** after API integration

## Status

✅ Fixed  
✅ Tested  
✅ Deployed to local Docker environment  
✅ Ready for production
