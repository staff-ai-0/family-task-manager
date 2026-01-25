# Family Task Manager - Frontend

Server-side rendered web interface for Family Task Manager.

## 🚀 Quick Start

### Prerequisites

- Python 3.12+
- Backend API running on http://localhost:8000

### Installation

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy environment file
cp .env.example .env

# Edit .env with your configuration
```

### Environment Variables

```bash
# Backend API URL
API_BASE_URL=http://localhost:8000

# Security
SECRET_KEY=your-secret-key-here

# Server
PORT=3000
DEBUG=true
```

### Run Development Server

```bash
# With uvicorn directly
uvicorn app.main:app --reload --host 0.0.0.0 --port 3000

# Or using Python
python -m app.main
```

### Run with Docker

```bash
# Build and run
docker-compose up -d

# View logs
docker-compose logs -f frontend

# Stop
docker-compose down
```

## 🌐 Available Pages

Once the server is running, access at http://localhost:3000:

- `/` - Home (redirects to dashboard)
- `/login` - Login page
- `/register` - Registration page
- `/dashboard` - Main dashboard
- `/tasks` - Tasks list
- `/rewards` - Rewards catalog
- `/consequences` - Consequences list
- `/points` - Points transaction history
- `/family` - Family management
- `/settings` - User settings
- `/auth/forgot-password` - Password reset request
- `/auth/reset-password` - Password reset form

## 📁 Project Structure

```
frontend/
├── app/
│   ├── templates/          # Jinja2 HTML templates
│   │   ├── base.html      # Base layout
│   │   ├── login.html
│   │   ├── dashboard.html
│   │   ├── tasks/
│   │   ├── rewards/
│   │   └── ...
│   ├── static/            # Static assets
│   │   └── js/
│   │       ├── darkmode.js
│   │       └── translations.js
│   ├── main.py            # FastAPI app
│   ├── views.py           # Route handlers
│   └── config.py          # Configuration
├── requirements.txt
├── .env.example
└── README.md
```

## 🎨 Technology Stack

- **Framework**: FastAPI
- **Templates**: Jinja2
- **CSS**: Tailwind CSS v3 (CDN)
- **Components**: Flowbite v2.2.0
- **Icons**: Font Awesome v6.4.0
- **JavaScript**: Vanilla JS (minimal)
- **HTTP Client**: httpx (for API calls)

## 🔧 Architecture

### Server-Side Rendering (SSR)

The frontend is a server-side rendered application that:

1. Renders HTML templates with Jinja2
2. Makes API calls to the backend
3. Handles user sessions
4. Manages authentication state

### Communication with Backend

```python
import httpx

# Example API call
async with httpx.AsyncClient() as client:
    response = await client.get(f"{API_BASE_URL}/api/tasks/")
    tasks = response.json()
```

## 🎨 UI Features

- ✅ **Responsive Design** - Mobile-first with Tailwind CSS
- ✅ **Dark Mode** - Toggle with persistent localStorage
- ✅ **Modern Components** - Flowbite UI components
- ✅ **Icon System** - Font Awesome icons
- ✅ **i18n Ready** - Translation system (Spanish)
- ✅ **Flash Messages** - Success/error notifications
- ✅ **Session Management** - 30-minute timeout
- ✅ **Form Validation** - Client-side validation

## 🔒 Security

- Session-based authentication
- CSRF protection (TODO)
- XSS prevention (Jinja2 auto-escaping)
- Secure cookies in production
- HTTPS recommended for production

## 📝 Development

### Adding New Pages

1. Create template in `app/templates/`
2. Add route handler in `app/views.py`
3. Make API calls to backend as needed
4. Update navigation in `app/templates/components/sidebar.html`

### Customizing Styles

The frontend uses Tailwind CSS via CDN. To customize:

1. Modify utility classes in templates
2. Or add custom CSS in `app/static/css/` (create folder)
3. Load in `app/templates/base.html`

### Calling Backend API

```python
from fastapi import APIRouter, Request
import httpx
from app.config import settings

router = APIRouter()

@router.get("/my-page")
async def my_page(request: Request):
    # Make API call
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{settings.API_BASE_URL}/api/endpoint",
            headers={"Authorization": f"Bearer {token}"}
        )
        data = response.json()
    
    # Render template
    return templates.TemplateResponse("my-page.html", {
        "request": request,
        "data": data
    })
```

## 🐛 Troubleshooting

### Frontend won't start

```bash
# Check if port 3000 is available
lsof -i :3000

# Install dependencies
pip install -r requirements.txt
```

### Can't connect to backend API

```bash
# Verify backend is running
curl http://localhost:8000/health

# Check API_BASE_URL in .env
echo $API_BASE_URL
```

### Templates not found

```bash
# Verify templates directory exists
ls -la app/templates/

# Check template paths in views.py
```

## 🚀 Deployment

### Production Considerations

1. Set `DEBUG=false` in environment
2. Use production-grade WSGI server (Gunicorn)
3. Enable HTTPS
4. Set secure session cookies
5. Configure proper CORS on backend
6. Use CDN for static assets (optional)

### Example Production Command

```bash
gunicorn app.main:app \
    --workers 4 \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:3000 \
    --access-logfile - \
    --error-logfile -
```

## 📞 Support

For issues and questions:

- Check backend API is running: http://localhost:8000/health
- Check frontend health: http://localhost:3000/health

## 📄 License

Private project - All rights reserved
