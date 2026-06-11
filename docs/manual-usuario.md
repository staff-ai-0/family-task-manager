# Manual de Usuario — Family Task Manager

**URL de acceso:** https://gcp-family.agent-ia.mx  
**Idiomas disponibles:** Español · English (botón ES/EN en la barra de navegación)

---

## Índice

1. [Primeros pasos](#1-primeros-pasos)
2. [Rol Parent (Padre/Madre)](#2-rol-parent)
3. [Rol Teen (Adolescente)](#3-rol-teen)
4. [Rol Child (Niño/a)](#4-rol-child)
5. [Funciones compartidas](#5-funciones-compartidas)
6. [Glosario](#6-glosario)

---

## 1. Primeros pasos

### 1.1 Registro de familia

1. Visita la URL de la aplicación y haz clic en **Registrarse**.
2. Completa el formulario:
   - **Nombre completo** del adulto que crea la cuenta.
   - **Nombre de la familia** (aparece en el panel de gestión).
   - **Correo electrónico** y **contraseña** (mínimo 8 caracteres).
   - Repite la contraseña en el campo de confirmación.
3. Haz clic en **Registrar**. Serás redirigido al dashboard.
4. Verifica tu correo electrónico: la app muestra un banner hasta que completes este paso (no bloquea el uso, pero se recomienda hacerlo).

> **Nota:** Solo el primer usuario que registra una familia recibe el rol **Parent**. Los demás miembros se añaden por invitación desde el panel de gestión.

### 1.2 Inicio de sesión

- Correo y contraseña en `/login`.
- También puedes usar **Google Sign-In** si lo prefieres.
- Si olvidaste tu contraseña, usa el enlace **¿Olvidaste tu contraseña?** para recibir un correo de recuperación.

### 1.3 Cambio de idioma

El botón **ES / EN** en la barra de navegación inferior cambia el idioma de toda la interfaz de forma inmediata, sin necesidad de recargar.

---

## 2. Rol Parent

El Parent tiene acceso completo a la aplicación: dashboard personal, configuración de la familia, gestión de tareas, recompensas, presupuesto y herramientas de administración.

### 2.1 Panel de gestión (`/parent`)

Punto central de administración. Desde aquí accedes a todas las herramientas de gestión mediante tarjetas con iconos:

| Tarjeta | Función |
|---|---|
| **Tareas** | Crear y editar plantillas de tareas |
| **Miembros** | Invitar y gestionar miembros de la familia |
| **Recompensas** | Configurar el catálogo de recompensas |
| **Asignaciones** | Ver asignaciones semanales activas |
| **Consecuencias** | Registrar consecuencias para miembros |
| **Aprobaciones** | Revisar gigs enviados para aprobación |
| **Analytics** | Puntuación PUP y progreso familiar |
| **Jarvis** | Asistente IA para la gestión familiar |
| **Kiosk** | Pantalla de visualización para TV/muro |
| **Presupuesto** | Finanzas personales y familiares |
| **Configuración** | Datos de familia y suscripción |

---

### 2.2 Gestión de tareas (`/parent/tasks`)

#### Crear una plantilla

Las **plantillas** son modelos de tareas reutilizables. El sistema las asigna automáticamente a los miembros según el tipo de asignación configurado.

1. Completa el formulario **Crear nueva plantilla**:

   | Campo | Descripción |
   |---|---|
   | **Título (inglés / español)** | Nombre de la tarea en ambos idiomas. El campo en español es opcional pero recomendado. |
   | **Descripción** | Instrucciones detalladas (opcional). |
   | **Puntos** | Valor en puntos que gana el miembro al completarla. |
   | **Dificultad** | Multiplicador aplicado al aprobar: Fácil ×1, Medio ×1.5, Difícil ×2. |
   | **Frecuencia** | Cada cuántos días se regenera: Diaria, Cada 3 días, Semanal. |
   | **Tipo de asignación** | Ver tabla siguiente. |
   | **Quién puede hacerla** | Roles habilitados: Parent, Teen, Child. Si no se marca ninguno, todos pueden. |
   | **Tarea bonus** | Si está marcada, la tarea solo se desbloquea cuando el miembro completa todas las obligatorias del día. |
   | **Modo gig** | Cómo se resuelve cuando varios miembros son elegibles (ver sección Gigs). |
   | **Bloquea recompensas** | El niño no puede canjear recompensas mientras esta tarea esté pendiente. |
   | **Penalización tardía** | Restricción automática si la tarea no se completa a tiempo (tipo, gravedad, duración). |

2. Haz clic en **Crear plantilla**.

**Tipos de asignación:**

| Tipo | Comportamiento |
|---|---|
| **Auto (balanceo)** | El sistema elige quién recibe la tarea para equilibrar la carga de trabajo. |
| **Fijo** | Siempre se asigna a la(s) misma(s) persona(s). |
| **Rotación** | Cicla entre un grupo específico de personas semana a semana. |

#### Editar o desactivar una plantilla

En la lista **Todas las plantillas**, cada tarjeta tiene tres botones:

- **Lápiz (editar):** Abre el formulario de edición con todos los campos precargados.
- **Deactivate/Activate:** Desactiva la plantilla sin borrarla (no se asignará en futuros shuffles). Puedes reactivarla cuando quieras.
- **Papelera (eliminar):** Elimina permanentemente la plantilla.

#### Shuffle semanal

El **Shuffle** asigna automáticamente las plantillas activas a los miembros de la familia para la semana en curso.

- **Preview:** Muestra cómo quedarían las asignaciones antes de confirmar.
- **Shuffle Tasks:** Ejecuta el reparto y crea las asignaciones de la semana.

> Puedes hacer el shuffle manualmente en cualquier momento. Si ya existen asignaciones para la semana, el sistema las reemplaza con las nuevas.

---

### 2.3 Miembros de la familia (`/parent/members`)

#### Invitar a un miembro

1. En la sección de invitaciones, ingresa el **correo electrónico** del nuevo miembro.
2. Selecciona el **rol**: Child, Teen o Parent.
3. Haz clic en **Invitar**. La persona recibirá un correo con un enlace de aceptación.

> Cuando el invitado acepta, queda vinculado a tu familia. Su rol determina qué puede ver y hacer en la aplicación.

#### Gestionar miembros existentes

Cada miembro en la lista muestra:
- Nombre, rol y correo.
- **Puntos actuales.**
- Botones para **ajustar puntos** manualmente (añadir o descontar).
- Opción para **desactivar** temporalmente al miembro (útil en vacaciones).

---

### 2.4 Recompensas (`/parent/rewards`)

Define el catálogo de premios que los miembros pueden canjear con sus puntos.

#### Crear una recompensa

| Campo | Descripción |
|---|---|
| **Nombre** | Nombre visible de la recompensa. |
| **Categoría** | Tipo: Juguetes, Golosinas, Privilegios, Actividades, Pantalla, etc. |
| **Costo en puntos** | Cuántos puntos debe gastar el miembro para canjearla. |
| **Descripción** | Detalle adicional (opcional). |

Las recompensas se muestran a todos los miembros en `/rewards`. El balance de puntos se descuenta automáticamente al canjear.

---

### 2.5 Consecuencias (`/parent/consequences`)

Registra consecuencias formales para un miembro cuando no cumple con sus responsabilidades.

1. Selecciona el **miembro**.
2. Escribe el **título** y la **descripción** de la consecuencia.
3. (Opcional) Establece una **fecha límite**.
4. Haz clic en **Crear consecuencia**.

El miembro verá la consecuencia en su vista y recibirá una notificación.

---

### 2.6 Aprobaciones de gigs (`/parent/approvals`)

Cuando un miembro completa una **tarea gig** (bonus con foto de evidencia), aparece aquí para revisión.

Por cada ítem pendiente puedes:
- Ver el **nombre del miembro**, la **tarea** y la **foto de evidencia** enviada.
- **Aprobar:** El miembro recibe los puntos correspondientes.
- **Rechazar:** Los puntos no se otorgan y el miembro recibe notificación.

> El badge numérico en la tarjeta "Aprobaciones" del panel de gestión indica cuántos gigs están pendientes de revisión.

---

### 2.7 Analytics (`/parent/analytics`)

Muestra el **PUP Score** (Participación, Uso, Progreso) de la familia: una puntuación compuesta basada en el cumplimiento de tareas de los últimos 30 días.

- **Gráfico sparkline:** Evolución diaria del PUP Score.
- **Puntuación actual** y tendencia.

Útil para identificar semanas de bajo rendimiento y ajustar las plantillas o incentivos.

---

### 2.8 Presupuesto (`/budget`)

Módulo de finanzas personales y familiares. Completamente nativo en la aplicación.

#### Estructura

| Sección | Descripción |
|---|---|
| **Cuentas** | Registra cuentas bancarias, tarjetas, efectivo, etc. |
| **Transacciones** | Registra ingresos y gastos. |
| **Categorías** | Agrupa gastos (alimentación, transporte, ocio…). |
| **Presupuesto mensual** | Asigna un monto a cada categoría por mes. |
| **Reportes** | Gasto por categoría, ingresos vs egresos, patrimonio neto. |
| **Importar** | Sube archivos CSV, OFX, QIF o CAMT desde tu banco. |
| **Escanear recibo** | Usa IA (Claude Vision) para extraer datos de un recibo fotografiado. |

#### Escanear recibo

1. Ve a `/budget/scan-receipt`.
2. Toma una foto, sube una imagen (JPEG/PNG/WebP) o un PDF.
3. La IA extrae fecha, monto, comercio y categoría.
4. Revisa y confirma los datos antes de guardar la transacción.
5. Si la confianza de la IA es baja, el recibo queda en la **cola de revisión** (`/budget/receipt-drafts`) para que lo revises manualmente.

> El escaneo de recibos requiere plan **Plus** o **Pro**.

---

### 2.9 Jarvis — Asistente IA (`/parent/jarvis`)

Jarvis es un copiloto de inteligencia artificial para la gestión familiar. Puedes hacerle preguntas en lenguaje natural:

- "¿Qué tareas están pendientes esta semana?"
- "¿Quién ha ganado más puntos este mes?"
- "Sugiere nuevas tareas para los fines de semana."
- "¿Cómo está el progreso de Emma esta semana?"

El historial de conversación se guarda y puedes borrarlo con el botón **Limpiar historial**.

#### Programar a Jarvis (`/parent/jarvis-schedules`)

Crea recordatorios automáticos para que Jarvis te informe sin que tengas que preguntarle:

1. Escribe una **tarea o pregunta** para Jarvis.
2. Define la **expresión cron** (o usa los presets: diario, lunes, cada hora, etc.).
3. Guarda. Jarvis ejecutará la consulta automáticamente según el horario.

---

### 2.10 Kiosk — Pantalla mural (`/parent/kiosk`)

Crea una URL pública especial para mostrar las tareas del día en una TV o pantalla compartida, sin necesidad de iniciar sesión.

1. En `/parent/kiosk`, haz clic en **Generar token**.
2. Copia la URL que aparece (formato `/kiosk?token=XXXX`).
3. Abre esa URL en cualquier navegador o smart TV.

La pantalla kiosk muestra en tiempo real las asignaciones del día, el estado de cada tarea y los puntos acumulados por miembro.

---

### 2.11 Configuración

#### Datos de familia (`/parent/settings/family`)

- Cambiar el **nombre de la familia**.
- Ver y copiar el **código de invitación** para compartir con nuevos miembros.

#### Suscripción (`/parent/settings/subscription`)

La app tiene tres planes:

| Plan | Características principales |
|---|---|
| **Free** | Hasta 3 miembros, tareas básicas, recompensas. |
| **Plus** | Más miembros, escaneo de recibos, metas de presupuesto, importación CSV. |
| **Pro** | Sin límites, reportes avanzados, reportes personalizados, todas las funciones IA. |

El pago se gestiona mediante **PayPal**. Desde esta sección puedes ver tu plan actual, actualizar o cancelar.

---

## 3. Rol Teen

El Teen tiene un acceso **extendido** respecto al Child, con capacidades similares a un adulto en lo cotidiano, pero sin acceso al panel de gestión.

### 3.1 Dashboard (`/dashboard`)

Igual que el Parent: muestra tareas del día, progreso, puntos acumulados y acceso a todas las secciones del menú inferior.

### 3.2 Tareas del día

El Teen ve y gestiona sus tareas de la misma forma que un Child (ver sección 4.2). La diferencia es que el Teen puede recibir plantillas marcadas con el rol **Teen** o **Parent**, además de las marcadas como **Child**.

### 3.3 Acceso a funciones adicionales

El Teen puede acceder a:
- **Presupuesto** (`/budget`) — Para llevar sus propias finanzas.
- **Calendario** — Para ver y crear eventos familiares.
- **Lista de compras** — Para añadir y marcar artículos.
- **Chat familiar** — Para comunicarse con la familia.
- **Mensajes directos** — Para enviar mensajes privados a otros miembros.

> El Teen **no puede** acceder al panel `/parent` ni configurar plantillas, miembros, recompensas o consecuencias.

---

## 4. Rol Child

El Child tiene una vista simplificada enfocada en completar tareas, ganar puntos y canjear recompensas.

### 4.1 Dashboard (`/dashboard`)

Al iniciar sesión, el Child ve:

- **Saludo con su nombre** y sus **puntos actuales**.
- **Barra de progreso** de tareas obligatorias completadas / total.
- Lista de **tareas del día** divididas en:
  - **Obligatorias:** Deben completarse todas para desbloquear las bonus.
  - **Bonus:** Disponibles solo después de completar todas las obligatorias. Generalmente valen más puntos.

### 4.2 Cómo completar una tarea

#### Tarea estándar

1. Encuentra la tarea en el dashboard.
2. Haz clic en el botón **Completar** (o marca el checkbox).
3. Si la tarea tiene **aprobación automática**, los puntos se acreditan de inmediato.
4. Si requiere **revisión del Parent**, la tarea queda en estado "Pendiente de aprobación" hasta que el Parent la revise.

#### Tarea gig (con evidencia)

Algunas tareas bonus requieren enviar una foto como evidencia de que la completaste:

1. Haz clic en la tarea gig.
2. Toma una foto o selecciona una de tu galería.
3. Envía la foto. La tarea pasa a estado **"Enviado — en revisión"**.
4. El Parent aprueba o rechaza desde `/parent/approvals`.
5. Si se aprueba, los puntos se acreditan automáticamente.

#### Modo gig: competencia

Si el modo es **Competencia**, la tarea gig solo la gana el **primero** en completarla y enviar la evidencia. Los demás miembros elegibles ven la tarea disponible hasta que alguien la reclame.

### 4.3 Recompensas (`/rewards`)

1. Ve a la sección **Rewards** desde el menú inferior.
2. Explora el catálogo de premios disponibles.
3. Si tienes suficientes puntos, haz clic en **Canjear**.
4. Confirma el canje. Los puntos se descuentan de tu saldo.

> **Bloqueo de recompensas:** Si tienes una tarea pendiente marcada como "Bloquea recompensas", no podrás canjear nada hasta completarla. La pantalla mostrará cuál tarea está bloqueando el acceso.

### 4.4 Chat familiar (`/chat`)

- Escribe mensajes que todos los miembros de la familia pueden leer.
- Los mensajes nuevos generan un badge de notificación en el ícono de chat del menú inferior.

### 4.5 Mensajes directos (`/dm`)

Envía un mensaje privado a un miembro específico de la familia. Solo el remitente y el destinatario ven la conversación.

### 4.6 Notificaciones (`/notifications`)

La bandeja de entrada (ícono "Inbox" en el menú) muestra:
- Aprobaciones o rechazos de gigs.
- Nuevas tareas asignadas.
- Consecuencias registradas por el Parent.
- Otras notificaciones del sistema.

Haz clic en **Marcar todo como leído** para limpiar el contador.

### 4.7 Perfil (`/profile`)

- Ver y actualizar tu **nombre** y **foto de perfil**.
- Cambiar tu **contraseña**.
- Ver tu historial de puntos.

---

## 5. Funciones compartidas

Estas funciones están disponibles para todos los roles.

### 5.1 Calendario (`/calendar`)

- Vista **agenda** y vista **mensual**.
- Crea eventos familiares con título, fecha, hora y frecuencia de repetición (diaria, semanal, mensual o regla RRULE personalizada).
- Los eventos recurrentes se generan automáticamente en el calendario.
- **Feed iCal:** Exporta el calendario en formato `.ics` para suscribirte desde Google Calendar, Apple Calendar u otras apps.
- **Escanear evento** (`/calendar/scan`): Fotografía una invitación o flyer y la IA extrae los datos del evento automáticamente.

### 5.2 Lista de compras (`/shopping`)

Listas compartidas con toda la familia:

1. Crea una nueva lista con un nombre.
2. Añade artículos con nombre y cantidad opcional.
3. Marca los artículos como **comprados** (tachado visual) al adquirirlos.
4. Cualquier miembro de la familia puede ver y modificar las listas.

### 5.3 Mascota virtual (`/pet`)

La familia tiene una mascota virtual cuyo estado refleja la participación familiar en las tareas. Completa más tareas para mantener a la mascota feliz y con energía.

### 5.4 Menú de navegación inferior

El menú inferior es siempre visible y tiene estos accesos directos:

| Ícono | Destino | Roles |
|---|---|---|
| Tareas | `/dashboard` | Todos |
| Recompensas | `/rewards` | Todos |
| Inbox | `/notifications` | Todos |
| Chat | `/chat` | Todos |
| Perfil | `/profile` | Todos |
| Presupuesto | `/budget` | Todos |
| Gestión | `/parent` | Solo Parent |

### 5.5 Ayuda

La sección `/help` (o `/ayuda`) contiene preguntas frecuentes y guías rápidas dentro de la app.

---

## 6. Glosario

| Término | Significado |
|---|---|
| **Plantilla** | Modelo de tarea reutilizable que el sistema asigna automáticamente. |
| **Asignación** | Instancia activa de una plantilla asignada a un miembro específico para una semana. |
| **Shuffle** | Proceso automático que reparte las plantillas activas entre los miembros para la semana. |
| **Tarea obligatoria** | Tarea que debe completarse para desbloquear las tareas bonus. |
| **Tarea bonus** | Tarea adicional disponible solo después de completar todas las obligatorias. Generalmente tiene más puntos. |
| **Gig** | Tarea bonus que requiere foto de evidencia y aprobación del Parent. |
| **Modo gig** | Regla de resolución cuando varios miembros pueden hacer el mismo gig: Reclamar (primero), Competencia, Rotación, Colaboración. |
| **PUP Score** | Puntuación compuesta de Participación, Uso y Progreso de la familia en los últimos 30 días. |
| **Jarvis** | Asistente IA integrado para consultas y gestión familiar en lenguaje natural. |
| **Kiosk** | URL pública sin login para mostrar las tareas del día en una pantalla compartida. |
| **Puntos** | Moneda interna del juego. Se ganan al completar tareas y se gastan al canjear recompensas. |
| **Consecuencia** | Registro formal de una falta o incumplimiento, creado por el Parent. |
| **Cron** | Expresión de tiempo para programar tareas automáticas de Jarvis (ej. `0 8 * * 1` = cada lunes a las 8 am). |

---

*Manual generado para Family Task Manager — versión en producción en https://gcp-family.agent-ia.mx*
