#!/bin/bash
# Test monitoring script for Family Task Manager
# This will show relevant logs during testing

echo "========================================="
echo "Family Task Manager - Test Monitor"
echo "========================================="
echo ""
echo "Monitoring logs for:"
echo "  - OAuth events"
echo "  - Email sending"
echo "  - User registration"
echo "  - Password reset"
echo "  - Email verification"
echo ""
echo "Press Ctrl+C to stop"
echo "========================================="
echo ""

docker compose logs -f web 2>&1 | grep --line-buffered -E "(OAuth|oauth|google|Google|email|Email|password|Password|verification|Verification|register|Register|Family created|User created|SMTP|smtp)" --color=always
