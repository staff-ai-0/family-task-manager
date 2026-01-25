"""
Send frontend credentials email in Spanish using Resend API
"""
import requests

RESEND_API_KEY = "re_eqvK5xAB_MgfnKyn3JchQ9EemDQu7xyt3"
RECIPIENTS = ["meg@agent-ia.mx", "admin@agent-ia.mx"]

# Email content in Spanish
subject = "✨ ¡Frontend Listo! - Credenciales de Acceso Web"
html_content = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
        .header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; border-radius: 10px; text-align: center; }
        .header h1 { margin: 0; font-size: 28px; }
        .credentials { background: #f3f4f6; padding: 20px; border-radius: 8px; margin: 20px 0; }
        .user-card { background: white; border-left: 4px solid #667eea; padding: 15px; margin: 15px 0; border-radius: 5px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .user-card h3 { margin-top: 0; color: #667eea; }
        code { background: #e5e7eb; padding: 3px 8px; border-radius: 4px; font-family: 'Courier New', monospace; color: #dc2626; }
        .highlight { background: #fef3c7; border-left: 4px solid #f59e0b; padding: 15px; margin: 20px 0; border-radius: 5px; }
        .button { display: inline-block; background: #667eea; color: white; padding: 12px 30px; text-decoration: none; border-radius: 6px; font-weight: bold; margin: 10px 5px; }
        .button:hover { background: #5568d3; }
        table { width: 100%; border-collapse: collapse; margin: 20px 0; }
        table th { background: #667eea; color: white; padding: 12px; text-align: left; }
        table td { padding: 12px; border-bottom: 1px solid #e5e7eb; }
        table tr:nth-child(even) { background: #f9fafb; }
        .footer { margin-top: 40px; padding-top: 20px; border-top: 2px solid #e5e7eb; color: #666; font-size: 13px; text-align: center; }
        .success-box { background: #d1fae5; border: 2px solid #10b981; padding: 20px; border-radius: 8px; margin: 20px 0; }
        .feature-list { list-style: none; padding: 0; }
        .feature-list li { padding: 8px 0; padding-left: 30px; position: relative; }
        .feature-list li:before { content: "✓"; position: absolute; left: 0; color: #10b981; font-weight: bold; font-size: 18px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎉 ¡El Frontend está Listo!</h1>
            <p style="margin: 10px 0 0 0; font-size: 16px;">Family Task Manager - Interfaz Web Completa</p>
        </div>
        
        <div class="success-box">
            <h2 style="margin-top: 0; color: #059669;">✅ Sistema Totalmente Funcional</h2>
            <p style="margin-bottom: 0;">El frontend web está activo y funcionando con usuarios de demostración, tareas, recompensas y transacciones de puntos pre-cargadas.</p>
        </div>
        
        <h2>🌐 Acceso al Frontend</h2>
        
        <div style="text-align: center; margin: 30px 0;">
            <a href="http://localhost:8001/" class="button">🚀 Abrir Aplicación Web</a>
            <a href="http://localhost:8001/docs" class="button" style="background: #6366f1;">📚 Ver API Docs</a>
        </div>
        
        <div class="highlight">
            <strong>🔗 URL Principal:</strong> <a href="http://localhost:8001/" style="color: #2563eb;">http://localhost:8001/</a><br>
            <strong>📄 Página de Login:</strong> <a href="http://localhost:8001/login" style="color: #2563eb;">http://localhost:8001/login</a>
        </div>
        
        <h2>👥 Credenciales de Usuarios Demo</h2>
        
        <p>Hemos creado 4 usuarios de demostración con diferentes roles para que puedas probar todas las funcionalidades:</p>
        
        <div class="credentials">
            <div class="user-card">
                <h3>👩 Sarah Johnson (Madre)</h3>
                <p><strong>Email:</strong> <code>mom@demo.com</code></p>
                <p><strong>Contraseña:</strong> <code>password123</code></p>
                <p><strong>Rol:</strong> PARENT</p>
                <p><strong>Puntos:</strong> 500 ⭐</p>
                <p><strong>Permisos:</strong></p>
                <ul class="feature-list">
                    <li>Crear y asignar tareas a los hijos</li>
                    <li>Crear recompensas</li>
                    <li>Aprobar solicitudes de recompensas</li>
                    <li>Transferir puntos entre usuarios</li>
                    <li>Ajustes manuales de puntos (bonos/penalizaciones)</li>
                    <li>Ver estadísticas familiares</li>
                </ul>
            </div>
            
            <div class="user-card">
                <h3>👨 Mike Johnson (Padre)</h3>
                <p><strong>Email:</strong> <code>dad@demo.com</code></p>
                <p><strong>Contraseña:</strong> <code>password123</code></p>
                <p><strong>Rol:</strong> PARENT</p>
                <p><strong>Puntos:</strong> 300 ⭐</p>
                <p><strong>Permisos:</strong> Iguales que el otro padre</p>
            </div>
            
            <div class="user-card">
                <h3>👧 Emma Johnson (Hija)</h3>
                <p><strong>Email:</strong> <code>emma@demo.com</code></p>
                <p><strong>Contraseña:</strong> <code>password123</code></p>
                <p><strong>Rol:</strong> CHILD</p>
                <p><strong>Puntos:</strong> 150 ⭐</p>
                <p><strong>Permisos:</strong></p>
                <ul class="feature-list">
                    <li>Ver tareas asignadas</li>
                    <li>Completar tareas propias</li>
                    <li>Ver recompensas disponibles</li>
                    <li>Solicitar recompensas</li>
                    <li>Ver historial de puntos</li>
                </ul>
            </div>
            
            <div class="user-card">
                <h3>🧑 Lucas Johnson (Adolescente)</h3>
                <p><strong>Email:</strong> <code>lucas@demo.com</code></p>
                <p><strong>Contraseña:</strong> <code>password123</code></p>
                <p><strong>Rol:</strong> TEEN</p>
                <p><strong>Puntos:</strong> 280 ⭐</p>
                <p><strong>Permisos:</strong> Iguales que CHILD + puede tener mayor autonomía</p>
            </div>
        </div>
        
        <h2>🎯 Datos Pre-cargados</h2>
        
        <p>El sistema incluye datos de ejemplo para facilitar las pruebas:</p>
        
        <h3>📝 Tareas (8 tareas creadas)</h3>
        <table>
            <thead>
                <tr>
                    <th>Tarea</th>
                    <th>Puntos</th>
                    <th>Frecuencia</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>🧹 Make your bed</td>
                    <td>10</td>
                    <td>Diaria</td>
                </tr>
                <tr>
                    <td>🍽️ Clear dinner table</td>
                    <td>15</td>
                    <td>Diaria</td>
                </tr>
                <tr>
                    <td>📚 Complete homework</td>
                    <td>25</td>
                    <td>Diaria</td>
                </tr>
                <tr>
                    <td>🚮 Take out trash</td>
                    <td>20</td>
                    <td>Semanal</td>
                </tr>
                <tr>
                    <td>🧼 Clean bathroom</td>
                    <td>30</td>
                    <td>Semanal</td>
                </tr>
            </tbody>
        </table>
        
        <h3>🎁 Recompensas (5 recompensas disponibles)</h3>
        <table>
            <thead>
                <tr>
                    <th>Recompensa</th>
                    <th>Costo</th>
                    <th>Categoría</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>🎮 30 Minutes Screen Time</td>
                    <td>100 pts</td>
                    <td>Tiempo de pantalla</td>
                </tr>
                <tr>
                    <td>🍦 Ice Cream Trip</td>
                    <td>150 pts</td>
                    <td>Golosinas</td>
                </tr>
                <tr>
                    <td>🎬 Movie Night Pick</td>
                    <td>120 pts</td>
                    <td>Privilegios</td>
                </tr>
                <tr>
                    <td>🌙 Later Bedtime</td>
                    <td>200 pts</td>
                    <td>Privilegios</td>
                </tr>
                <tr>
                    <td>🎁 Small Toy/Book</td>
                    <td>500 pts</td>
                    <td>Juguetes</td>
                </tr>
            </tbody>
        </table>
        
        <h2>🎨 Características del Frontend</h2>
        
        <ul class="feature-list">
            <li><strong>Diseño Responsivo</strong> - Optimizado para móvil, tablet y desktop</li>
            <li><strong>Modo Oscuro</strong> - Toggle entre tema claro y oscuro (persiste en localStorage)</li>
            <li><strong>Componentes Modernos</strong> - Tailwind CSS + Flowbite</li>
            <li><strong>Iconos Font Awesome</strong> - Interfaz visual atractiva</li>
            <li><strong>Navegación Intuitiva</strong> - Sidebar colapsable + navbar superior</li>
            <li><strong>Autenticación Completa</strong> - Login, registro, recuperación de contraseña</li>
            <li><strong>Google OAuth</strong> - Inicio de sesión con Google (integrado)</li>
            <li><strong>Internacionalización</strong> - Sistema i18n listo (actualmente en español)</li>
            <li><strong>Mensajes Flash</strong> - Notificaciones de éxito/error</li>
            <li><strong>Sesiones Seguras</strong> - SessionMiddleware con 30min timeout</li>
        </ul>
        
        <h2>🧭 Navegación del Sistema</h2>
        
        <table>
            <thead>
                <tr>
                    <th>Página</th>
                    <th>URL</th>
                    <th>Descripción</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>🏠 Dashboard</td>
                    <td><code>/dashboard</code></td>
                    <td>Vista principal con resumen y estadísticas</td>
                </tr>
                <tr>
                    <td>📋 Tareas</td>
                    <td><code>/tasks</code></td>
                    <td>Lista de tareas, crear/completar tareas</td>
                </tr>
                <tr>
                    <td>🎁 Recompensas</td>
                    <td><code>/rewards</code></td>
                    <td>Catálogo de recompensas disponibles</td>
                </tr>
                <tr>
                    <td>⚠️ Consecuencias</td>
                    <td><code>/consequences</code></td>
                    <td>Consecuencias activas por tareas vencidas</td>
                </tr>
                <tr>
                    <td>💰 Puntos</td>
                    <td><code>/points</code></td>
                    <td>Historial de transacciones de puntos</td>
                </tr>
                <tr>
                    <td>👨‍👩‍👧‍👦 Familia</td>
                    <td><code>/family</code></td>
                    <td>Gestión de miembros y estadísticas</td>
                </tr>
                <tr>
                    <td>⚙️ Configuración</td>
                    <td><code>/settings</code></td>
                    <td>Ajustes de usuario</td>
                </tr>
            </tbody>
        </table>
        
        <h2>🚀 Flujo de Uso Recomendado</h2>
        
        <h3>Paso 1: Login como Padre</h3>
        <ol>
            <li>Ir a <a href="http://localhost:8001/login">http://localhost:8001/login</a></li>
            <li>Usar <code>mom@demo.com</code> / <code>password123</code></li>
            <li>Explorar el dashboard</li>
            <li>Ver la lista de tareas en <code>/tasks</code></li>
            <li>Ver recompensas disponibles en <code>/rewards</code></li>
            <li>Revisar estadísticas familiares en <code>/family</code></li>
        </ol>
        
        <h3>Paso 2: Login como Hijo</h3>
        <ol>
            <li>Cerrar sesión (o abrir en ventana privada)</li>
            <li>Login con <code>emma@demo.com</code> / <code>password123</code></li>
            <li>Ver tareas asignadas</li>
            <li>Intentar completar una tarea</li>
            <li>Ver cómo aumentan los puntos</li>
            <li>Explorar recompensas para canjear</li>
        </ol>
        
        <h3>Paso 3: Flujos Avanzados</h3>
        <ul class="feature-list">
            <li>Crear una nueva tarea como padre</li>
            <li>Asignar tarea a un hijo específico</li>
            <li>Completar tarea como hijo y verificar puntos</li>
            <li>Canjear una recompensa</li>
            <li>Aprobar/rechazar solicitud de recompensa (si requiere aprobación)</li>
            <li>Transferir puntos entre usuarios</li>
            <li>Aplicar bonos o penalizaciones manuales</li>
        </ul>
        
        <h2>🔧 Información Técnica</h2>
        
        <h3>Stack Tecnológico Frontend</h3>
        <ul>
            <li><strong>Template Engine:</strong> Jinja2</li>
            <li><strong>CSS Framework:</strong> Tailwind CSS v3 (CDN)</li>
            <li><strong>Component Library:</strong> Flowbite v2.2.0</li>
            <li><strong>Icons:</strong> Font Awesome v6.4.0</li>
            <li><strong>JavaScript:</strong> Vanilla JS (minimal)</li>
            <li><strong>Architecture:</strong> Server-Side Rendering (SSR)</li>
        </ul>
        
        <h3>Servicios Activos</h3>
        <table>
            <tr>
                <td><strong>Frontend + API</strong></td>
                <td>http://localhost:8001</td>
            </tr>
            <tr>
                <td><strong>PostgreSQL</strong></td>
                <td>localhost:5433</td>
            </tr>
            <tr>
                <td><strong>Redis</strong></td>
                <td>localhost:6380</td>
            </tr>
        </table>
        
        <h2>📊 Estado del Proyecto</h2>
        
        <table>
            <tr>
                <td><strong>Tests Automatizados</strong></td>
                <td>118 pruebas ✅</td>
            </tr>
            <tr>
                <td><strong>Cobertura de Código</strong></td>
                <td>71% ✅</td>
            </tr>
            <tr>
                <td><strong>Servicios Críticos</strong></td>
                <td>100% cobertura (Auth, Task, Family) ✅</td>
            </tr>
            <tr>
                <td><strong>Contenedores Docker</strong></td>
                <td>3/3 corriendo ✅</td>
            </tr>
            <tr>
                <td><strong>Frontend Funcional</strong></td>
                <td>Sí ✅</td>
            </tr>
            <tr>
                <td><strong>Datos de Demo</strong></td>
                <td>Cargados ✅</td>
            </tr>
        </table>
        
        <h2>📚 Documentación Adicional</h2>
        
        <ul>
            <li><strong>API Docs (Swagger):</strong> <a href="http://localhost:8001/docs">http://localhost:8001/docs</a></li>
            <li><strong>API Docs (ReDoc):</strong> <a href="http://localhost:8001/redoc">http://localhost:8001/redoc</a></li>
            <li><strong>Health Check:</strong> <a href="http://localhost:8001/health">http://localhost:8001/health</a></li>
        </ul>
        
        <h2>🐛 Troubleshooting</h2>
        
        <h3>¿Los contenedores no responden?</h3>
        <pre style="background: #1f2937; color: #fff; padding: 15px; border-radius: 5px;">docker-compose ps
docker-compose logs -f web</pre>
        
        <h3>¿Error de login?</h3>
        <ul>
            <li>Verificar que usas el email completo: <code>mom@demo.com</code></li>
            <li>Contraseña exacta: <code>password123</code> (minúsculas)</li>
            <li>Verificar logs del servidor para más detalles</li>
        </ul>
        
        <h3>¿Necesitas resetear los datos?</h3>
        <pre style="background: #1f2937; color: #fff; padding: 15px; border-radius: 5px;">cd /Users/jc/dev-2026/poc/family-task-manager
source venv/bin/activate
python seed_data.py</pre>
        
        <div class="footer">
            <p><strong>🎯 Family Task Manager</strong> - Sistema Completo de Gestión de Tareas Familiares</p>
            <p>Backend API + Frontend Web + Base de Datos + Tests</p>
            <p>© 2026 Todos los derechos reservados.</p>
            <p style="margin-top: 20px; color: #10b981; font-weight: bold;">✅ Todo está listo para usar. ¡Comienza a explorar!</p>
            <p style="margin-top: 10px;"><em>Última actualización: Enero 24, 2026</em></p>
        </div>
    </div>
</body>
</html>
"""

# Send via Resend API
def send_email():
    print("📧 Enviando email de credenciales frontend a:", ", ".join(RECIPIENTS))
    
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
    print("=" * 70)
    print("✨ Family Task Manager - Credenciales Frontend")
    print("=" * 70)
    print()
    
    success = send_email()
    
    print()
    print("=" * 70)
    if success:
        print("✅ Email de credenciales frontend enviado exitosamente")
        print()
        print("📋 Resumen:")
        print("   • 4 usuarios demo creados (2 padres + 2 hijos)")
        print("   • 8 tareas de ejemplo")
        print("   • 5 recompensas disponibles")
        print("   • 3 transacciones de muestra")
        print()
        print("🌐 Frontend disponible en: http://localhost:8001")
    else:
        print("❌ El proceso falló")
    print("=" * 70)
