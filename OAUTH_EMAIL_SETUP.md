# Google OAuth & Email Verification Setup Guide

## Overview

Your Family Task Manager now supports:
- **Google OAuth Login** - Users can sign in with their Google account
- **Email Verification** - New registrations receive verification emails
- **SMTP Email Sending** - Configured for Gmail

## What Was Implemented

### 1. Database Changes
- ✅ `users.email_verified` (boolean) - Tracks if email is verified
- ✅ `users.email_verified_at` (datetime) - Timestamp of verification
- ✅ `users.oauth_provider` (string) - OAuth provider name (e.g., "google")
- ✅ `users.oauth_id` (string) - OAuth provider's user ID
- ✅ `users.password_hash` - Now nullable for OAuth-only users
- ✅ `email_verification_tokens` table - Stores verification tokens

### 2. New Services Created
- **`EmailService`** (`app/services/email_service.py`)
  - Sends verification emails
  - Creates and validates tokens
  - Marks users as verified

- **`GoogleOAuthService`** (`app/services/oauth_service.py`)
  - Handles Google OAuth flow
  - Creates/links OAuth users
  - Auto-verifies email for Google users

### 3. New Routes Added
**Email Verification:**
- `GET /auth/verify-email?token=XXX` - Verify email with token
- `POST /auth/resend-verification` - Resend verification email

**Google OAuth:**
- `GET /auth/google/login` - Redirect to Google OAuth
- `GET /auth/google/callback` - Handle OAuth callback

### 4. UI Updates
- ✅ Login page now has "Continue with Google" button
- ✅ Beautiful Google logo with proper styling
- ✅ Divider between email/password and OAuth login

## Configuration Required

### Step 1: Get Google OAuth Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or select existing)
3. Enable **Google+ API**
4. Go to **Credentials** → **Create Credentials** → **OAuth 2.0 Client ID**
5. Configure OAuth consent screen
6. Add authorized redirect URI: `http://localhost:8000/auth/google/callback`
7. Copy your **Client ID** and **Client Secret**

### Step 2: Get Gmail App Password

1. Go to your [Google Account](https://myaccount.google.com/)
2. Navigate to **Security**
3. Enable **2-Step Verification** (required)
4. Go to **App Passwords**
5. Generate a new app password for "Mail"
6. Copy the 16-character password

### Step 3: Update Environment Variables

Edit your `.env` file (create from `.env.example`):

```bash
# Google OAuth
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/google/callback

# Email Configuration  
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-16-char-app-password
SMTP_FROM_EMAIL=your-email@gmail.com
SMTP_FROM_NAME=Family Task Manager
EMAIL_VERIFICATION_EXPIRE_MINUTES=1440
```

### Step 4: Restart the Application

```bash
docker compose restart web
```

## How It Works

### Email Verification Flow

1. **User Registers** (`POST /register`)
   - User fills registration form
   - System creates user account
   - System sends verification email automatically
   - User redirected to login with "Check your email" message

2. **User Clicks Email Link** (`GET /auth/verify-email?token=XXX`)
   - Token validated (not expired, not used)
   - User marked as `email_verified=true`
   - Redirected to login with success message

3. **Resend Verification** (`POST /auth/resend-verification`)
   - User can request new verification email
   - Only works if email not yet verified

### Google OAuth Flow

1. **User Clicks "Continue with Google"** (`GET /auth/google/login`)
   - Redirects to Google OAuth consent screen
   - User authorizes the app

2. **Google Redirects Back** (`GET /auth/google/callback`)
   - System receives user info from Google
   - **Existing User**: Links OAuth to existing account (by email)
   - **New User**: Currently redirects to register (future: create account automatically)
   - Email auto-verified for Google users
   - User logged in with session cookie

3. **Future OAuth Registration**:
   - When new Google user logs in, they'll need to select/create family
   - Can be enhanced to store Google info in session during registration

## Testing Without SMTP

If SMTP credentials are NOT configured, the app will:
- Print email content to console logs
- Continue working normally
- Show warning: `"WARNING: SMTP credentials not configured"`

You can test the flow by:
```bash
docker compose logs -f web | grep "Would send to"
```

## Database Migrations Applied

1. **`2025_12_12_0801-c89db4e73129_initial_schema.py`**
   - Initial database schema

2. **`2025_12_12_0803-22b45677041a_make_family_created_by_nullable.py`**
   - Made `family.created_by` nullable

3. **`2025_12_12_0811-079b00e9dddc_add_oauth_and_email_verification.py`**
   - Added OAuth and email verification fields to users table
   - Made `password_hash` nullable

4. **`2025_12_12_0811-fab16872eb7e_add_email_verification_tokens_table.py`**
   - Created `email_verification_tokens` table

## Dependencies Added

```
authlib==1.3.0         # OAuth client
itsdangerous==2.1.2    # Token generation
aiosmtplib==3.0.1      # Async SMTP client
```

## Security Considerations

✅ **Implemented:**
- Email verification tokens expire after 24 hours
- Tokens are single-use only
- OAuth emails are auto-verified
- Passwords are optional for OAuth users
- HTTP-only cookies for sessions

⚠️ **Production TODO:**
- Use HTTPS for OAuth callback
- Store OAuth tokens securely if needed
- Implement CSRF protection for OAuth
- Add rate limiting on verification email sending
- Consider adding reCAPTCHA to registration

## Testing Checklist

### Email Verification
- [ ] Register new user with valid email
- [ ] Check logs for verification email
- [ ] Click verification link
- [ ] Verify user can login
- [ ] Try using expired/invalid token
- [ ] Test resend verification

### Google OAuth
- [ ] Click "Continue with Google"
- [ ] Complete Google authorization
- [ ] Verify auto-login works
- [ ] Test with existing email (should link accounts)
- [ ] Test with new Google email

### Edge Cases
- [ ] User registers then uses Google OAuth (should link)
- [ ] OAuth user tries to set password later
- [ ] Unverified user tries to login

## Next Steps

1. **Configure OAuth Credentials** (see Step 1-3 above)
2. **Test Email Sending** with real SMTP
3. **Enhance OAuth Registration** to auto-create family for new users
4. **Add Email Templates** with proper branding
5. **Implement Password Reset** using email service
6. **Add Social Login Buttons** (Facebook, GitHub, etc.)

## Troubleshooting

**OAuth Error: "redirect_uri_mismatch"**
- Check that redirect URI in Google Console matches exactly
- Must include protocol (http/https)

**Email Not Sending:**
- Verify SMTP credentials in `.env`
- Check 2-Step Verification is enabled
- Use App Password, not regular password
- Check Docker logs: `docker compose logs web`

**"Email already exists" on OAuth:**
- This is correct behavior - linking accounts
- User should login with password first

## File Structure

```
app/
├── models/
│   ├── user.py (updated with OAuth fields)
│   └── email_verification.py (new)
├── services/
│   ├── email_service.py (new)
│   └── oauth_service.py (new)
├── api/routes/
│   └── views.py (added OAuth + email routes)
└── templates/
    └── login.html (added Google button)
```

## Support

For issues or questions:
1. Check Docker logs: `docker compose logs -f web`
2. Check database: `docker compose exec db psql -U familyapp -d familyapp`
3. Review migration status: `docker compose exec web alembic current`

---

**Status:** ✅ Fully Implemented & Ready for Configuration

**Last Updated:** December 12, 2025
