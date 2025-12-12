# 🚀 Guía Rápida - Family Task Manager

**¡Bienvenido al proyecto Family Task Manager!**

Esta es una aplicación web de gestión de tareas familiares con gamificación, inspirada en **OurHome**.

---

## 📁 ¿Qué hay en .github?

La carpeta `.github` contiene toda la documentación que **GitHub Copilot** necesita para ayudarte a desarrollar el proyecto de manera eficiente.

### Documentos Principales

| Archivo | Descripción | Cuándo Leerlo |
|---------|-------------|---------------|
| **README.md** | Índice de navegación | Primer paso - comienza aquí |
| **copilot-instructions.md** | Instrucciones completas de Copilot | Siempre - Copilot lo lee automáticamente |
| **SETUP_COMPLETE.md** | Resumen de lo que se creó | Para entender la estructura |

### Carpetas

| Carpeta | Contenido | Para Qué Sirve |
|---------|-----------|----------------|
| **instructions/** | Reglas de código específicas | Copilot las aplica automáticamente según el archivo |
| **prompts/** | Plantillas para crear componentes | Guías paso a paso para crear features |
| **memory-bank/** | Contexto del proyecto | Información del negocio y decisiones técnicas |

---

## 🎯 ¿Qué Hace Esta Aplicación?

### Concepto Principal

Ayuda a las familias a organizar tareas diarias usando **gamificación**:

1. **Tareas Obligatorias** (por defecto):
   - Deben completarse (ej: tarea escolar, limpiar cuarto)
   - No completarlas → **consecuencias** (restricciones)

2. **Tareas Extras** (opcionales):
   - Solo disponibles si completaste las obligatorias
   - Dan **más puntos** para recompensas

3. **Sistema de Puntos**:
   - Completar tareas → ganar puntos
   - Canjear puntos → obtener recompensas

4. **Consecuencias**:
   - No completar tareas obligatorias → restricciones temporales
   - Ejemplo: sin acceso a recompensas, sin tareas extras

### Ejemplo de Flujo

```
👧 María (niña de 10 años):
1. Ve sus tareas del día:
   ✅ Hacer tarea escolar (20 puntos) - OBLIGATORIA
   ✅ Limpiar cuarto (15 puntos) - OBLIGATORIA
   ⭐ Ayudar a lavar platos (30 puntos) - EXTRA

2. Completa las obligatorias → gana 35 puntos
3. Ahora puede hacer la extra → gana 30 puntos más (total: 65)
4. Va al catálogo de recompensas:
   🎮 30 min de videojuegos (50 puntos)
   🍦 Helado especial (100 puntos)
5. Canjea 50 puntos por videojuegos → le quedan 15 puntos

❌ Si NO hubiera completado las obligatorias:
   - No podría acceder a tareas extras
   - Tendría una consecuencia activa
   - No podría canjear recompensas
```

---

## 🛠️ Stack Tecnológico

### Backend (Servidor)
- **FastAPI** (Python 3.12+): Framework web moderno
- **PostgreSQL**: Base de datos relacional
- **SQLAlchemy**: ORM para trabajar con la BD
- **JWT**: Autenticación segura

### Frontend (Interfaz)
- **Jinja2**: Templates HTML del lado del servidor
- **Flowbite**: Componentes UI bonitos (basado en Tailwind)
- **HTMX**: Actualizaciones dinámicas sin mucho JavaScript
- **Alpine.js**: Interactividad ligera

### Deployment
- **Render**: Plataforma en la nube (gratis para empezar)

---

## 📖 Cómo Empezar a Desarrollar

### Paso 1: Lee la Documentación Base

```bash
# En orden:
1. .github/README.md                    # Este archivo
2. .github/memory-bank/projectbrief.md  # Entender el negocio
3. .github/copilot-instructions.md      # Instrucciones completas
```

### Paso 2: Configura el Entorno Local

```bash
# Clonar repositorio
git clone https://github.com/tuusuario/family-app.git
cd family-app

# Crear entorno virtual
python -m venv venv
source venv/bin/activate  # En Windows: venv\Scripts\activate

# Instalar dependencias
pip install -r requirements.txt

# Configurar base de datos
cp .env.example .env
# Editar .env con tus credenciales

# Ejecutar migraciones
alembic upgrade head

# Iniciar servidor
uvicorn app.main:app --reload
```

### Paso 3: Accede a la Aplicación

- **Web**: http://localhost:8000
- **Docs API (Swagger)**: http://localhost:8000/docs
- **Docs API (ReDoc)**: http://localhost:8000/redoc

---

## 🎨 Crear Nuevas Features

### Crear un Endpoint de API

```bash
# 1. Lee la plantilla
.github/prompts/new-api-endpoint.md

# 2. Sigue estos pasos:
# a) Crear schemas en app/schemas/
# b) Implementar lógica en app/services/
# c) Crear route en app/api/routes/
# d) Escribir tests en tests/

# 3. Copilot te ayudará automáticamente siguiendo las instrucciones
```

### Crear un Modelo de Base de Datos

```bash
# 1. Lee la plantilla
.github/prompts/new-model.md

# 2. Pasos:
# a) Crear modelo en app/models/
# b) Generar migración: alembic revision --autogenerate -m "mensaje"
# c) Revisar migración en migrations/versions/
# d) Aplicar: alembic upgrade head
# e) Actualizar relaciones en modelos relacionados
```

### Crear un Componente UI

```bash
# 1. Lee las instrucciones
.github/instructions/02-frontend-ui.instructions.md

# 2. Usa Flowbite components
# https://flowbite.com/docs/components/

# 3. Integra con HTMX para dinamismo
# 4. Añade Alpine.js si necesitas interactividad
```

---

## 🔐 Seguridad Importante

### ⚠️ NUNCA HAGAS ESTO:

❌ Hardcodear passwords o API keys en el código  
❌ Commitear archivos `.env` con secretos  
❌ Usar contraseñas en texto plano  
❌ Permitir acceso cross-family a datos  
❌ Olvidar validar inputs del usuario

### ✅ SIEMPRE HAZ ESTO:

✅ Usar variables de entorno para secretos  
✅ Hashear passwords con bcrypt  
✅ Validar con Pydantic schemas  
✅ Verificar permisos (roles: PARENT, CHILD, TEEN)  
✅ Aislar datos por familia (family_id)

---

## 🧪 Testing

### Ejecutar Tests

```bash
# Todos los tests
pytest

# Con cobertura
pytest --cov=app --cov-report=html

# Test específico
pytest tests/test_tasks.py

# Test con output verbose
pytest -v
```

### Escribir Tests

```python
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_complete_task(client: AsyncClient, auth_headers):
    # Setup
    payload = {"task_id": "..."}
    
    # Execute
    response = await client.patch(
        "/api/tasks/123/complete",
        headers=auth_headers
    )
    
    # Assert
    assert response.status_code == 200
    assert response.json()["success"] is True
```

---

## 📊 Estructura del Proyecto

```
family-app/
├── app/
│   ├── main.py              # Entrada de la aplicación
│   ├── api/
│   │   └── routes/          # Endpoints (tasks.py, rewards.py, etc.)
│   ├── core/
│   │   ├── config.py        # Configuración
│   │   ├── security.py      # JWT, passwords
│   │   └── database.py      # Conexión a BD
│   ├── models/              # Modelos SQLAlchemy
│   ├── schemas/             # Schemas Pydantic
│   ├── services/            # Lógica de negocio
│   ├── templates/           # HTML Jinja2
│   └── static/              # CSS, JS, imágenes
├── tests/                   # Tests
├── migrations/              # Migraciones Alembic
├── .env                     # Variables de entorno (NO COMMITEAR)
├── requirements.txt         # Dependencias Python
└── .github/                 # 📚 DOCUMENTACIÓN (esta carpeta)
```

---

## 🤖 Trabajar con GitHub Copilot

### Cómo Aprovecharlo al Máximo

1. **Copilot Lee Automáticamente**:
   - `.github/copilot-instructions.md`
   - Archivos en `.github/instructions/` según el archivo que edites

2. **Usa Prompts Específicos**:
   ```
   # Ejemplo:
   "Crea un endpoint POST /api/tasks siguiendo el template en .github/prompts/new-api-endpoint.md"
   ```

3. **Pide Que Siga las Reglas**:
   ```
   "Implementa TaskService siguiendo las instrucciones de backend en .github/instructions/"
   ```

4. **Consulta Templates**:
   ```
   "Muéstrame cómo crear un modelo de Task basándote en .github/prompts/new-model.md"
   ```

---

## 🆘 Problemas Comunes

### Base de Datos No Conecta

```bash
# Verificar PostgreSQL corriendo
# Revisar DATABASE_URL en .env
# Ejecutar migraciones
alembic upgrade head
```

### JWT Token Inválido

```bash
# Verificar SECRET_KEY en .env
# El token expira en 30 minutos
# Hacer login nuevamente
```

### HTMX No Funciona

```bash
# El endpoint debe devolver HTML, no JSON
# Verificar hx-target apunta al elemento correcto
# Ver Network tab en DevTools del browser
```

---

## 📚 Recursos Útiles

### Documentación Oficial

- **FastAPI**: https://fastapi.tiangolo.com/
- **Flowbite**: https://flowbite.com/docs/
- **HTMX**: https://htmx.org/docs/
- **Alpine.js**: https://alpinejs.dev/
- **SQLAlchemy**: https://docs.sqlalchemy.org/en/20/

### Tutoriales

- FastAPI + PostgreSQL: https://fastapi.tiangolo.com/tutorial/sql-databases/
- HTMX + FastAPI: https://github.com/tataraba/fastapi-htmx-tailwind
- Flowbite Components: https://flowbite.com/docs/getting-started/quickstart/

---

## 🎯 Tareas Iniciales Sugeridas

### Para Familiarizarte con el Proyecto

1. **Leer Documentación** (2 horas):
   - [ ] README.md de .github
   - [ ] copilot-instructions.md
   - [ ] projectbrief.md

2. **Configurar Entorno** (1 hora):
   - [ ] Instalar dependencias
   - [ ] Configurar base de datos
   - [ ] Ejecutar migraciones
   - [ ] Iniciar servidor

3. **Explorar API** (30 min):
   - [ ] Abrir Swagger UI
   - [ ] Probar endpoints de ejemplo
   - [ ] Revisar schemas

4. **Primera Feature** (2-3 horas):
   - [ ] Crear modelo simple (ej: Task)
   - [ ] Implementar service layer
   - [ ] Crear endpoint básico
   - [ ] Escribir tests

---

## 💡 Tips de Desarrollo

1. **Usa el Swagger UI** (`/docs`) para probar endpoints rápidamente
2. **Lee los templates** antes de crear componentes nuevos
3. **Sigue las convenciones** de nombres y estructura
4. **Escribe tests** mientras desarrollas, no después
5. **Commitea frecuentemente** con mensajes claros
6. **Pregunta a Copilot** usando los templates de `.github/prompts/`

---

## 🎉 ¡Listo para Empezar!

Tienes todo lo necesario para comenzar a desarrollar. La estructura de `.github` te guiará en cada paso.

**Siguiente Paso**: Lee `.github/memory-bank/projectbrief.md` para entender completamente el proyecto.

---

**¿Preguntas?** Consulta `.github/README.md` para el índice completo de documentación.

**¡Feliz Coding! 🚀**
