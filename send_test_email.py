"""
Send test user credentials email in Spanish using Resend API
"""
import requests

RESEND_API_KEY = "re_eqvK5xAB_MgfnKyn3JchQ9EemDQu7xyt3"
RECIPIENTS = ["meg@agent-ia.mx", "admin@agent-ia.mx"]

# Email content in Spanish
subject = "🎯 Usuarios de Prueba - Family Task Manager"
html_content = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
        .header { background: #3b82f6; color: white; padding: 20px; border-radius: 5px; }
        .credentials { background: #f3f4f6; padding: 15px; border-radius: 5px; margin: 20px 0; }
        .user-box { background: white; border-left: 4px solid #3b82f6; padding: 15px; margin: 10px 0; }
        code { background: #e5e7eb; padding: 2px 6px; border-radius: 3px; font-family: monospace; }
        .note { background: #fef3c7; border-left: 4px solid #f59e0b; padding: 15px; margin: 15px 0; }
        pre { background: #1f2937; color: #fff; padding: 15px; border-radius: 5px; overflow-x: auto; font-size: 13px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎯 Family Task Manager - Usuarios de Prueba</h1>
        </div>
        
        <h2>Bienvenido al Sistema de Gestión de Tareas Familiares</h2>
        
        <p>Este sistema permite a las familias gestionar tareas, asignar puntos, y canjear recompensas de manera organizada.</p>
        
        <div class="note">
            <strong>⚠️ Nota Importante:</strong> Los usuarios de prueba solo existen durante la ejecución de tests automatizados. Para crear usuarios reales, usa los endpoints de registro o crea usuarios manualmente en la base de datos.
        </div>
        
        <h2>👥 Usuarios de Prueba (durante tests)</h2>
        
        <div class="credentials">
            <div class="user-box">
                <h3>👨‍👩‍👧‍👦 Usuario Padre (Parent)</h3>
                <p><strong>Email:</strong> <code>parent@test.com</code></p>
                <p><strong>Contraseña:</strong> <code>password123</code></p>
                <p><strong>Rol:</strong> Parent</p>
                <p><strong>Puntos iniciales:</strong> 0</p>
                <p><strong>Permisos:</strong> Crear tareas, asignar a hijos, aprobar recompensas, transferir puntos</p>
            </div>
            
            <div class="user-box">
                <h3>👶 Usuario Hijo (Child)</h3>
                <p><strong>Email:</strong> <code>child@test.com</code></p>
                <p><strong>Contraseña:</strong> <code>password123</code></p>
                <p><strong>Rol:</strong> Child</p>
                <p><strong>Puntos iniciales:</strong> 100</p>
                <p><strong>Permisos:</strong> Completar tareas asignadas, solicitar recompensas</p>
            </div>
        </div>
        
        <h2>📍 URLs de Acceso</h2>
        <ul>
            <li><strong>API Docs (Swagger):</strong> <a href="http://localhost:8001/docs">http://localhost:8001/docs</a></li>
            <li><strong>API Docs (ReDoc):</strong> <a href="http://localhost:8001/redoc">http://localhost:8001/redoc</a></li>
            <li><strong>Health Check:</strong> <a href="http://localhost:8001/health">http://localhost:8001/health</a></li>
        </ul>
        
        <h2>🚀 Guía de Inicio Rápido</h2>
        
        <h3>1. Verificar que los servicios estén activos</h3>
        <pre>docker-compose ps

# Deberías ver:
# family_app_db     - PostgreSQL (puerto 5433)
# family_app_redis  - Redis (puerto 6380)
# family_app_web    - API Server (puerto 8001)</pre>
        
        <h3>2. Crear un usuario de prueba (Padre)</h3>
        <pre>POST http://localhost:8001/api/auth/register
Content-Type: application/json

{
  "email": "padre.prueba@example.com",
  "password": "MiPassword123!",
  "full_name": "Padre de Prueba",
  "role": "parent",
  "family_id": 1
}

# Respuesta:
{
  "id": 1,
  "email": "padre.prueba@example.com",
  "full_name": "Padre de Prueba",
  "role": "parent",
  "family_id": 1,
  "is_active": true
}</pre>
        
        <h3>3. Autenticarse</h3>
        <pre>POST http://localhost:8001/api/auth/login
Content-Type: application/json

{
  "email": "padre.prueba@example.com",
  "password": "MiPassword123!"
}

# Respuesta:
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}</pre>
        
        <h3>4. Usar el Token en peticiones</h3>
        <p>Incluye el token en el header Authorization de todas las peticiones protegidas:</p>
        <pre>Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...</pre>
        
        <h2>💡 Casos de Uso Principales</h2>
        
        <h3>Caso 1: Crear una tarea para un hijo</h3>
        <pre>POST http://localhost:8001/api/tasks/
Authorization: Bearer {token_padre}
Content-Type: application/json

{
  "title": "Hacer la tarea de matemáticas",
  "description": "Completar ejercicios de la página 42",
  "points": 50,
  "assigned_to": 2,
  "is_default": true,
  "frequency": "daily",
  "due_date": "2026-01-25T18:00:00"
}</pre>
        
        <h3>Caso 2: Hijo completa una tarea</h3>
        <pre>POST http://localhost:8001/api/tasks/{task_id}/complete
Authorization: Bearer {token_hijo}

# El hijo gana los puntos automáticamente</pre>
        
        <h3>Caso 3: Crear una recompensa</h3>
        <pre>POST http://localhost:8001/api/rewards/
Authorization: Bearer {token_padre}
Content-Type: application/json

{
  "title": "1 hora de videojuegos",
  "description": "Tiempo extra para jugar",
  "points_cost": 100,
  "requires_approval": true,
  "is_active": true
}</pre>
        
        <h3>Caso 4: Hijo canjea una recompensa</h3>
        <pre>POST http://localhost:8001/api/rewards/{reward_id}/redeem
Authorization: Bearer {token_hijo}

# Si requires_approval=true, el padre debe aprobar:
PUT http://localhost:8001/api/redemptions/{redemption_id}/approve
Authorization: Bearer {token_padre}</pre>
        
        <h3>Caso 5: Transferir puntos entre usuarios</h3>
        <pre>POST http://localhost:8001/api/points/transfer
Authorization: Bearer {token_padre}
Content-Type: application/json

{
  "from_user_id": 1,
  "to_user_id": 2,
  "points": 50,
  "reason": "Buen comportamiento esta semana"
}</pre>
        
        <h2>🏗️ Arquitectura del Sistema</h2>
        
        <h3>Stack Tecnológico</h3>
        <ul>
            <li><strong>Backend:</strong> FastAPI (Python 3.12)</li>
            <li><strong>Base de Datos:</strong> PostgreSQL 15</li>
            <li><strong>Cache:</strong> Redis 7</li>
            <li><strong>ORM:</strong> SQLAlchemy 2.0</li>
            <li><strong>Autenticación:</strong> JWT (JSON Web Tokens)</li>
            <li><strong>Contenedores:</strong> Docker & Docker Compose</li>
        </ul>
        
        <h3>Entidades Principales</h3>
        <ul>
            <li><strong>Family:</strong> Grupo familiar al que pertenecen los usuarios</li>
            <li><strong>User:</strong> Usuarios (parent/child) con balance de puntos</li>
            <li><strong>Task:</strong> Tareas asignables con puntos de recompensa</li>
            <li><strong>Reward:</strong> Recompensas canjeables por puntos</li>
            <li><strong>Consequence:</strong> Consecuencias automáticas por tareas vencidas</li>
            <li><strong>Transaction:</strong> Historial de movimientos de puntos</li>
        </ul>
        
        <h2>📊 Cobertura de Pruebas</h2>
        
        <p>El sistema cuenta con <strong>118 pruebas automatizadas</strong> y <strong>71% de cobertura de código</strong>:</p>
        
        <table style="width: 100%; border-collapse: collapse; margin: 20px 0;">
            <thead>
                <tr style="background: #3b82f6; color: white;">
                    <th style="padding: 10px; text-align: left;">Servicio</th>
                    <th style="padding: 10px; text-align: center;">Cobertura</th>
                    <th style="padding: 10px; text-align: center;">Tests</th>
                </tr>
            </thead>
            <tbody>
                <tr style="background: #f9fafb;">
                    <td style="padding: 10px;">AuthService</td>
                    <td style="padding: 10px; text-align: center;"><strong>100%</strong></td>
                    <td style="padding: 10px; text-align: center;">18</td>
                </tr>
                <tr>
                    <td style="padding: 10px;">FamilyService</td>
                    <td style="padding: 10px; text-align: center;"><strong>100%</strong></td>
                    <td style="padding: 10px; text-align: center;">18</td>
                </tr>
                <tr style="background: #f9fafb;">
                    <td style="padding: 10px;">TaskService</td>
                    <td style="padding: 10px; text-align: center;"><strong>100%</strong></td>
                    <td style="padding: 10px; text-align: center;">27</td>
                </tr>
                <tr>
                    <td style="padding: 10px;">PointsService</td>
                    <td style="padding: 10px; text-align: center;"><strong>84%</strong></td>
                    <td style="padding: 10px; text-align: center;">31</td>
                </tr>
                <tr style="background: #f9fafb;">
                    <td style="padding: 10px;">RewardService</td>
                    <td style="padding: 10px; text-align: center;">75%</td>
                    <td style="padding: 10px; text-align: center;">24</td>
                </tr>
            </tbody>
        </table>
        
        <h3>Ejecutar las pruebas</h3>
        <pre>cd /Users/jc/dev-2026/poc/family-task-manager

# Todas las pruebas
pytest

# Con cobertura
pytest --cov=app --cov-report=html

# Tests específicos
pytest tests/test_task_service.py -v</pre>
        
        <h2>🔧 Servicios y Puertos</h2>
        
        <table style="width: 100%; border-collapse: collapse; margin: 20px 0;">
            <thead>
                <tr style="background: #3b82f6; color: white;">
                    <th style="padding: 10px; text-align: left;">Servicio</th>
                    <th style="padding: 10px; text-align: left;">Puerto</th>
                    <th style="padding: 10px; text-align: left;">Credenciales</th>
                </tr>
            </thead>
            <tbody>
                <tr style="background: #f9fafb;">
                    <td style="padding: 10px;"><strong>API Server</strong></td>
                    <td style="padding: 10px;"><code>localhost:8001</code></td>
                    <td style="padding: 10px;">-</td>
                </tr>
                <tr>
                    <td style="padding: 10px;"><strong>PostgreSQL</strong></td>
                    <td style="padding: 10px;"><code>localhost:5433</code></td>
                    <td style="padding: 10px;">User: <code>familyapp</code> / Pass: <code>familyapp123</code></td>
                </tr>
                <tr style="background: #f9fafb;">
                    <td style="padding: 10px;"><strong>Redis</strong></td>
                    <td style="padding: 10px;"><code>localhost:6380</code></td>
                    <td style="padding: 10px;">Sin contraseña</td>
                </tr>
            </tbody>
        </table>
        
        <h2>📂 Estructura del Proyecto</h2>
        
        <pre>family-task-manager/
├── app/
│   ├── api/              # Endpoints REST
│   │   ├── auth.py
│   │   ├── tasks.py
│   │   ├── rewards.py
│   │   └── ...
│   ├── services/         # Lógica de negocio
│   │   ├── auth_service.py
│   │   ├── task_service.py
│   │   ├── points_service.py
│   │   └── ...
│   ├── models/           # Modelos SQLAlchemy
│   │   ├── user.py
│   │   ├── task.py
│   │   └── ...
│   └── schemas/          # Validación Pydantic
│       └── ...
├── tests/                # Suite de pruebas
│   ├── conftest.py       # Fixtures compartidos
│   ├── test_auth_service.py
│   ├── test_task_service.py
│   └── ...
├── docker-compose.yml    # Orquestación de contenedores
├── requirements.txt      # Dependencias Python
└── .env                  # Variables de entorno</pre>
        
        <h2>🐛 Troubleshooting</h2>
        
        <h3>Los contenedores no inician</h3>
        <pre>docker-compose down
docker-compose up -d
docker-compose logs -f</pre>
        
        <h3>Error de conexión a la base de datos</h3>
        <pre># Verificar que PostgreSQL esté corriendo
docker-compose ps

# Ver logs del contenedor
docker-compose logs family_app_db</pre>
        
        <h3>Resetear la base de datos</h3>
        <pre>docker-compose down -v  # Elimina volúmenes
docker-compose up -d</pre>
        
        <h3>Acceder a la base de datos</h3>
        <pre>docker exec -it family_app_db psql -U familyapp -d familyapp

# Comandos útiles:
\\dt           # Listar tablas
\\d users      # Describir tabla users
SELECT * FROM users;</pre>
        
        <h2>📞 Recursos Adicionales</h2>
        
        <ul>
            <li><strong>Documentación FastAPI:</strong> <a href="https://fastapi.tiangolo.com/">https://fastapi.tiangolo.com/</a></li>
            <li><strong>Documentación SQLAlchemy:</strong> <a href="https://docs.sqlalchemy.org/">https://docs.sqlalchemy.org/</a></li>
            <li><strong>Documentación Docker:</strong> <a href="https://docs.docker.com/">https://docs.docker.com/</a></li>
        </ul>
        
        <h2>✅ Checklist de Primeros Pasos</h2>
        
        <ol style="line-height: 2;">
            <li>✅ Verificar que los contenedores estén corriendo (<code>docker-compose ps</code>)</li>
            <li>✅ Acceder a la documentación Swagger (<a href="http://localhost:8001/docs">http://localhost:8001/docs</a>)</li>
            <li>⬜ Crear una familia de prueba</li>
            <li>⬜ Registrar un usuario padre</li>
            <li>⬜ Registrar un usuario hijo</li>
            <li>⬜ Crear una tarea y asignarla</li>
            <li>⬜ Completar la tarea y verificar puntos</li>
            <li>⬜ Crear una recompensa y canjearla</li>
            <li>⬜ Ejecutar las pruebas (<code>pytest</code>)</li>
        </ol>
        
        <div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #e5e7eb; color: #666; font-size: 12px;">
            <p><strong>🎯 Family Task Manager</strong> - Sistema de Gestión de Tareas Familiares</p>
            <p>© 2026 Todos los derechos reservados.</p>
            <p>Este es un correo automático. Por favor no responder directamente.</p>
            <p><em>Última actualización: Enero 24, 2026</em></p>
        </div>
    </div>
</body>
</html>
"""

# Send via Resend API
def send_email():
    print("📧 Enviando email a:", ", ".join(RECIPIENTS))
    
    response = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "from": "Family Task Manager <notificaciones@icegg.mx>",
            "to": RECIPIENTS,
            "subject": subject,
            "html": html_content
        }
    )
    
    if response.status_code == 200:
        result = response.json()
        print(f"✅ Email enviado exitosamente!")
        print(f"📨 ID del mensaje: {result.get('id')}")
        print(f"👥 Destinatarios: {', '.join(RECIPIENTS)}")
        return True
    else:
        print(f"❌ Error enviando email: {response.status_code}")
        print(f"📄 Response: {response.text}")
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("🎯 Family Task Manager - Envío de Credenciales de Prueba")
    print("=" * 60)
    print()
    
    success = send_email()
    
    print()
    print("=" * 60)
    if success:
        print("✅ Proceso completado exitosamente")
    else:
        print("❌ El proceso falló")
    print("=" * 60)
