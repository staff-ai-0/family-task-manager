# Google OAuth & PayPal Payment Integration Guide

This guide explains how to set up Google OAuth sign-in and PayPal payment processing for the Family Task Manager application.

## Table of Contents
1. [Google OAuth Setup](#google-oauth-setup)
2. [PayPal API Setup](#paypal-api-setup)
3. [Environment Configuration](#environment-configuration)
4. [Testing](#testing)
5. [Production Deployment](#production-deployment)

---

## Google OAuth Setup

### 1. Create Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Enable the Google+ API:
   - Navigate to "APIs & Services" > "Library"
   - Search for "Google+ API"
   - Click "Enable"

### 2. Configure OAuth Consent Screen

1. Go to "APIs & Services" > "OAuth consent screen"
2. Choose "External" user type
3. Fill in the required fields:
   - App name: `Family Task Manager`
   - User support email: Your email
   - Developer contact information: Your email
4. Add scopes:
   - `./auth/userinfo.email`
   - `./auth/userinfo.profile`
   - `openid`
5. Add test users (for development)
6. Save and continue

### 3. Create OAuth 2.0 Credentials

1. Go to "APIs & Services" > "Credentials"
2. Click "Create Credentials" > "OAuth client ID"
3. Application type: "Web application"
4. Name: `Family Task Manager Web Client`
5. Authorized JavaScript origins:
   - `http://localhost:3003` (development)
   - `https://your-production-domain.com` (production)
6. Authorized redirect URIs:
   - `http://localhost:3003/login` (development)
   - `https://your-production-domain.com/login` (production)
7. Click "Create"
8. **Save** the Client ID and Client Secret

### 4. Update Environment Variables

Add to `backend/.env`:
```bash
GOOGLE_CLIENT_ID=your-google-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-google-client-secret
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/google/callback
```

### 5. Update Frontend Configuration

In `frontend/src/pages/login.astro`, replace `YOUR_GOOGLE_CLIENT_ID` with your actual Google Client ID:

```html
<div 
    id="g_id_onload"
    data-client_id="YOUR_ACTUAL_GOOGLE_CLIENT_ID"
    data-callback="handleGoogleLogin"
    data-auto_prompt="false">
</div>
```

---

## PayPal API Setup

### 1. Create PayPal Developer Account

1. Go to [PayPal Developer](https://developer.paypal.com/)
2. Sign up or log in with your PayPal account
3. Go to "Dashboard"

### 2. Create Sandbox App (Development)

1. Navigate to "Apps & Credentials"
2. Select "Sandbox" tab
3. Click "Create App"
4. App Name: `Family Task Manager Sandbox`
5. Click "Create App"
6. **Save** the Client ID and Secret

### 3. Create Live App (Production)

1. Navigate to "Apps & Credentials"
2. Select "Live" tab
3. Click "Create App"
4. App Name: `Family Task Manager`
5. Click "Create App"
6. **Save** the Client ID and Secret

### 4. Configure Webhooks (Optional, for subscriptions)

1. In your app settings, scroll to "Webhooks"
2. Click "Add Webhook"
3. Webhook URL: `https://your-domain.com/api/payment/webhook`
4. Select events to listen for:
   - `PAYMENT.SALE.COMPLETED`
   - `PAYMENT.SALE.REFUNDED`
   - `BILLING.SUBSCRIPTION.CREATED`
   - `BILLING.SUBSCRIPTION.CANCELLED`
5. Save and copy the Webhook ID

### 5. Update Environment Variables

Add to `backend/.env`:

**Development (Sandbox):**
```bash
PAYPAL_CLIENT_ID=your-sandbox-client-id
PAYPAL_CLIENT_SECRET=your-sandbox-client-secret
PAYPAL_MODE=sandbox
PAYPAL_WEBHOOK_ID=your-webhook-id
```

**Production (Live):**
```bash
PAYPAL_CLIENT_ID=your-live-client-id
PAYPAL_CLIENT_SECRET=your-live-client-secret
PAYPAL_MODE=live
PAYPAL_WEBHOOK_ID=your-webhook-id
```

---

## Environment Configuration

### Backend `.env` File

Complete example of `backend/.env`:

```bash
# Database Configuration
DATABASE_URL=postgresql://familyapp:familyapp123@db:5432/familyapp

# Application Configuration
DEBUG=True
BASE_URL=http://localhost:8000
ALLOWED_ORIGINS=http://localhost:3003,http://localhost:8000

# Security
SECRET_KEY=your-super-secret-key-change-this-in-production
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# Google OAuth Configuration
GOOGLE_CLIENT_ID=123456789-abcdefghijklmnop.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-abc123def456
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/google/callback

# PayPal Configuration
PAYPAL_CLIENT_ID=AaBbCcDdEeFfGgHhIiJjKkLlMmNnOoPp
PAYPAL_CLIENT_SECRET=EE1234567890abcdefghijklmnopqrstuv
PAYPAL_MODE=sandbox
PAYPAL_WEBHOOK_ID=WH-1A2B3C4D5E6F7G8H9I0J
```

### Store Credentials in Vault

For production, store these credentials in HashiCorp Vault:

```bash
# Google OAuth
vault kv put secret/family-task-manager/oauth \
  google_client_id="your-google-client-id" \
  google_client_secret="your-google-client-secret"

# PayPal
vault kv put secret/family-task-manager/payment \
  paypal_client_id="your-paypal-client-id" \
  paypal_client_secret="your-paypal-client-secret" \
  paypal_mode="live" \
  paypal_webhook_id="your-webhook-id"
```

---

## Testing

### Test Google OAuth

1. Start the backend and frontend:
   ```bash
   docker-compose up -d
   ```

2. Navigate to `http://localhost:3003/login`

3. Click "Sign in with Google"

4. You should see Google's OAuth consent screen

5. After authorization, you'll be redirected back and logged in

### Test PayPal Payments

1. Navigate to `http://localhost:3003/payment`

2. Click "Subscribe with PayPal" on any plan

3. You'll be redirected to PayPal Sandbox

4. Use sandbox test credentials to complete payment

5. After approval, you'll be redirected to `/payment/success`

### PayPal Sandbox Test Accounts

1. Go to [PayPal Sandbox Accounts](https://developer.paypal.com/dashboard/accounts)
2. Use the provided test accounts or create new ones
3. Use these credentials when testing payments

---

## Production Deployment

### Checklist

- [ ] Update `GOOGLE_CLIENT_ID` in frontend code
- [ ] Set `PAYPAL_MODE=live` in production environment
- [ ] Use production Google OAuth credentials
- [ ] Use production PayPal credentials
- [ ] Store all secrets in Vault (not in `.env` files)
- [ ] Add production domains to Google OAuth authorized origins
- [ ] Add production webhook URL to PayPal
- [ ] Enable HTTPS for all endpoints
- [ ] Test payment flow thoroughly
- [ ] Set up webhook monitoring and error handling

### Security Best Practices

1. **Never commit secrets to version control**
   - Use `.env` for local development only
   - Use Vault or environment variables for production

2. **Validate webhook signatures**
   - The PayPal webhook handler includes signature verification
   - Ensure `PAYPAL_WEBHOOK_ID` is correctly configured

3. **Use HTTPS in production**
   - PayPal requires HTTPS for live mode
   - Google OAuth recommends HTTPS for security

4. **Implement rate limiting**
   - Add rate limiting to payment endpoints
   - Prevent abuse of OAuth endpoints

5. **Log all payment events**
   - Monitor successful and failed payments
   - Set up alerts for payment errors

---

## API Endpoints

### OAuth Endpoints

- `POST /api/oauth/google` - Authenticate with Google
- `POST /api/oauth/google/verify` - Verify Google token without creating account

### Payment Endpoints

- `POST /api/payment/create` - Create a PayPal payment
- `POST /api/payment/execute` - Execute/confirm a payment
- `GET /api/payment/details/{payment_id}` - Get payment details
- `POST /api/payment/webhook` - Handle PayPal webhook events

### Frontend Pages

- `/login` - Login page with Google OAuth button
- `/payment` - Payment plans selection
- `/payment/success` - Payment success page
- `/payment/cancel` - Payment cancellation page

---

## Troubleshooting

### Google OAuth Issues

**Error: "redirect_uri_mismatch"**
- Ensure the redirect URI in Google Console matches exactly
- Check both JavaScript origins and redirect URIs

**Error: "Invalid token"**
- Verify `GOOGLE_CLIENT_ID` is correct in both backend and frontend
- Check token expiration (Google tokens expire after 1 hour)

### PayPal Issues

**Error: "Payment creation failed"**
- Verify `PAYPAL_CLIENT_ID` and `PAYPAL_CLIENT_SECRET`
- Check `PAYPAL_MODE` is set correctly (sandbox/live)
- Ensure amount is greater than 0

**Webhook not receiving events**
- Verify webhook URL is accessible from internet
- Check webhook ID matches PayPal dashboard
- Verify signature validation is working

---

## Support

For issues or questions:
- Check the [FastAPI documentation](https://fastapi.tiangolo.com/)
- Review [Google OAuth documentation](https://developers.google.com/identity/protocols/oauth2)
- Review [PayPal REST API documentation](https://developer.paypal.com/docs/api/overview/)
- Open an issue in the project repository

---

**Last Updated:** 2026-02-27
