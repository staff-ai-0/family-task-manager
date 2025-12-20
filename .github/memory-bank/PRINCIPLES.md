# Memory Bank - Core Security Principles

**Last Updated**: December 20, 2025  
**Purpose**: Security guidelines for memory bank documentation

---

## 🔒 Security Model

### Git-Safe Documentation (`.github/memory-bank/`)
All files in `.github/memory-bank/` are committed to git and must contain:
- ✅ Architecture and design decisions
- ✅ Deployment procedures (without credentials)
- ✅ Configuration templates
- ✅ Troubleshooting guides
- ✅ **References** to credentials (not actual values)

### Private Credentials (`CREDENTIALS.md`)
Actual sensitive values are stored in `CREDENTIALS.md` (gitignored):
- ❌ Master keys
- ❌ Service API keys
- ❌ Database passwords
- ❌ Provider API keys
- ❌ Any authentication tokens

---

## 📋 Documentation Standards

### DO: Use References
```markdown
## Quick Reference
| Item | Value |
|------|-------|
| Master Key | See `CREDENTIALS.md` |
| API Endpoint | http://10.1.0.99:4000 |
```

### DON'T: Include Actual Secrets
```markdown
❌ WRONG:
| Master Key | sk-abc123secretkey456 |

✅ CORRECT:
| Master Key | See `CREDENTIALS.md` |
```

---

## 🗂️ File Organization

### Git-Tracked Files
```
.github/
  memory-bank/
    README.md              # Overview (no secrets)
    deploymentContext.md   # Deployment guide (references only)
    techContext.md         # Technical architecture
    PRINCIPLES.md          # This file
```

### Gitignored Files (in project root)
```
CREDENTIALS.md      # ALL sensitive credentials
.env               # Environment variables
.env.production    # Production environment
.env.keys          # Service keys
service-keys.txt   # Legacy key storage
```

### .gitignore Must Include
```gitignore
# Credentials
CREDENTIALS.md
.env
.env.*
!.env.example
service-keys.txt

# Backups
*.backup
*.bak
```

---

## 🔑 Credential Storage

### CREDENTIALS.md Structure
```markdown
# Project - Credentials (GITIGNORED)

⚠️ WARNING: This file contains sensitive credentials

## Master Key
MASTER_KEY=sk-actual-secret-key

## Service Keys
SERVICE_A_KEY=sk-service-a-key
SERVICE_B_KEY=sk-service-b-key

## Database
DB_URL=postgresql://user:password@host:5432/db
```

### Access Pattern
```bash
# In documentation (git-tracked):
"See CREDENTIALS.md for master key"

# In actual usage:
export MASTER_KEY=$(grep MASTER_KEY CREDENTIALS.md | cut -d= -f2)
```

---

## ✅ Pre-Commit Checklist

Before committing any file:
1. [ ] Does it contain API keys? → Move to `CREDENTIALS.md`
2. [ ] Does it contain passwords? → Move to `CREDENTIALS.md`
3. [ ] Does it contain connection strings with passwords? → Move to `CREDENTIALS.md`
4. [ ] Does it reference `CREDENTIALS.md` instead of hardcoding? → ✅ Good!
5. [ ] Is `CREDENTIALS.md` in `.gitignore`? → Verify!

---

## 🚨 If Secrets Are Committed

### Immediate Actions
```bash
# 1. Remove from git history (if just committed)
git reset HEAD~1
git rm --cached CREDENTIALS.md
git add .gitignore
git commit -m "chore: Remove accidentally committed credentials"

# 2. Rotate ALL exposed credentials immediately
# - Generate new master key
# - Generate new service keys
# - Update database passwords
# - Update provider API keys

# 3. Update CREDENTIALS.md with new values
# 4. Update all services with new credentials
```

### Prevention
- Always review `git diff` before committing
- Use `git add -p` to review each change
- Keep `CREDENTIALS.md` open during documentation updates as reminder

---

## 📊 Examples

### Example 1: Deployment Guide
```markdown
## Step 1: Configure Environment

Create `.env` file:
```bash
DATABASE_URL=<see CREDENTIALS.md>
MASTER_KEY=<see CREDENTIALS.md>
```

✅ This references credentials without exposing them
```

### Example 2: Quick Reference
```markdown
| Component | Access |
|-----------|--------|
| Dashboard | http://10.1.0.99:4000/ui (credentials in CREDENTIALS.md) |
| API | http://10.1.0.99:4000 (use keys from CREDENTIALS.md) |
```

### Example 3: Troubleshooting
```markdown
### Authentication Errors

Check your credentials:
```bash
# Get master key
cat CREDENTIALS.md | grep MASTER_KEY

# Test authentication
curl -H "Authorization: Bearer $MASTER_KEY" http://api.example.com/test
```

✅ Shows how to access credentials without exposing them
```

---

## 🎯 Memory Bank Goals

1. **Knowledge Transfer**: Document everything needed to understand/maintain the system
2. **Security**: Never expose sensitive data in version control
3. **Reproducibility**: Anyone with `CREDENTIALS.md` can replicate the setup
4. **Maintainability**: Easy to update without security concerns

---

## 📝 Summary

### Simple Rule
**If it's secret, it goes in `CREDENTIALS.md`. If it's knowledge, it goes in `.github/memory-bank/`.**

### The Test
Ask yourself: "If this file was public on GitHub, would it be a security issue?"
- **Yes** → Gitignore it
- **No** → Safe to commit

---

**Maintained By**: jctux  
**Status**: Core principle for all StaffAI projects  
**Applies To**: All repositories with sensitive credentials
