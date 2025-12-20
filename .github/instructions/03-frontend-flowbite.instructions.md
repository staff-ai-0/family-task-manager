---
applyTo: "app/templates/**/*.html,app/static/**/*.js,app/static/**/*.css"
---

# Frontend Instructions - Flowbite & UI

This instruction file applies to: `app/templates/**/*.html`, `app/static/**/*.js`, `app/static/**/*.css`

## Overview

Family Task Manager uses a **Server-Side Rendering (SSR)** architecture with Flowbite components for the frontend. This document outlines the rules and patterns for building the UI.

## Tech Stack

**Frontend**:
- **Flowbite 2.2.0**: UI component library
- **Tailwind CSS**: Utility-first CSS framework
- **Jinja2**: Server-side templating engine
- **Font Awesome 6.4**: Icon library (optional)

**Multi-language Support**:
- Spanish (es) - Primary
- English (en) - Secondary

**Dark Mode**: Full support with Flowbite's dark mode utilities

---

## Core Principles

### 1. SSR-First Architecture

**ALL pages are rendered server-side using Jinja2 templates.**

```python
# ✅ CORRECT - Server-side rendering
from app.core.templates import templates

@router.get("/tasks", response_class=HTMLResponse)
async def list_tasks(request: Request, session: Session = Depends(get_db)):
    tasks = session.exec(select(Task)).all()
    return templates.TemplateResponse("tasks/list.html", {
        "request": request,
        "tasks": tasks
    })

# ❌ WRONG - JSON endpoint for pages
@router.get("/tasks")
async def get_tasks():
    return {"tasks": [...]}  # Don't do this for pages
```

### 2. No Custom JavaScript

**NEVER write custom JavaScript code. Use ONLY Flowbite components.**

```html
<!-- ✅ CORRECT - Flowbite data attributes -->
<button 
    data-modal-target="create-modal" 
    data-modal-toggle="create-modal" 
    type="button"
    class="text-white bg-blue-700 hover:bg-blue-800">
    Create Task
</button>

<!-- ❌ WRONG - Custom JavaScript -->
<button onclick="openModal()">Create</button>
<script>
function openModal() { ... }  // DON'T DO THIS
</script>
```

**Only allowed script**: `flowbite.min.js` from CDN

### 3. Post-Redirect-Get (PRG) Pattern

**ALL form submissions must follow PRG pattern.**

```python
# ✅ CORRECT - PRG Pattern
@router.post("/tasks/new")
async def create_task(
    session: Session = Depends(get_db),
    form_data: TaskCreate = Depends(TaskCreate.as_form)
):
    new_task = Task.model_validate(form_data)
    session.add(new_task)
    session.commit()
    # ✅ Always redirect after POST
    return RedirectResponse(url="/tasks/", status_code=303)

# ❌ WRONG - Render template after POST
@router.post("/tasks/new")
async def create_task(...):
    # Create task
    return templates.TemplateResponse("tasks/list.html", ...)  # DON'T
```

---

## Template Structure

### Base Template (`app/templates/base.html`)

```html
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}Family Task Manager{% endblock %}</title>
    
    <!-- Tailwind CSS CDN -->
    <script src="https://cdn.tailwindcss.com"></script>
    
    <!-- Flowbite CSS -->
    <link href="https://cdnjs.cloudflare.com/ajax/libs/flowbite/2.2.0/flowbite.min.css" rel="stylesheet" />
    
    <!-- Font Awesome (optional) -->
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" />
    
    {% block extra_head %}{% endblock %}
</head>
<body class="bg-gray-50 dark:bg-gray-900">
    <!-- Navigation -->
    {% include "components/navbar.html" %}
    
    <!-- Main Content -->
    <main class="p-4 md:ml-64 h-auto pt-20">
        {% block content %}{% endblock %}
    </main>
    
    <!-- Flowbite JS (ONLY allowed script) -->
    <script src="https://cdnjs.cloudflare.com/ajax/libs/flowbite/2.2.0/flowbite.min.js"></script>
    
    <!-- Translation system -->
    <script src="/static/js/translations.js"></script>
    
    {% block extra_js %}{% endblock %}
</body>
</html>
```

### Child Template Pattern

```html
{% extends "base.html" %}

{% block title %}Task List - Family Task Manager{% endblock %}

{% block content %}
<div class="max-w-7xl mx-auto">
    <h1 class="text-3xl font-bold text-gray-900 dark:text-white mb-6" data-i18n="tasks.title">
        Tareas
    </h1>
    
    <!-- Content here -->
</div>
{% endblock %}
```

---

## Flowbite Components

### 1. Modals

```html
<!-- Trigger Button -->
<button 
    data-modal-target="task-modal" 
    data-modal-toggle="task-modal" 
    type="button"
    class="text-white bg-blue-700 hover:bg-blue-800 focus:ring-4 focus:outline-none focus:ring-blue-300 font-medium rounded-lg text-sm px-5 py-2.5 text-center dark:bg-blue-600 dark:hover:bg-blue-700 dark:focus:ring-blue-800">
    <i class="fas fa-plus mr-2"></i>
    <span data-i18n="tasks.new">Nueva Tarea</span>
</button>

<!-- Modal Structure -->
<div id="task-modal" tabindex="-1" aria-hidden="true" class="hidden overflow-y-auto overflow-x-hidden fixed top-0 right-0 left-0 z-50 justify-center items-center w-full md:inset-0 h-[calc(100%-1rem)] max-h-full">
    <div class="relative p-4 w-full max-w-2xl max-h-full">
        <div class="relative bg-white rounded-lg shadow dark:bg-gray-700">
            <!-- Modal header -->
            <div class="flex items-center justify-between p-4 md:p-5 border-b rounded-t dark:border-gray-600">
                <h3 class="text-xl font-semibold text-gray-900 dark:text-white" data-i18n="tasks.create_title">
                    Crear Nueva Tarea
                </h3>
                <button type="button" class="text-gray-400 bg-transparent hover:bg-gray-200 hover:text-gray-900 rounded-lg text-sm w-8 h-8 ms-auto inline-flex justify-center items-center dark:hover:bg-gray-600 dark:hover:text-white" data-modal-hide="task-modal">
                    <svg class="w-3 h-3" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 14 14">
                        <path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="m1 1 6 6m0 0 6 6M7 7l6-6M7 7l-6 6"/>
                    </svg>
                    <span class="sr-only">Close modal</span>
                </button>
            </div>
            <!-- Modal body -->
            <form method="post" action="/tasks/new" class="p-4 md:p-5">
                <div class="grid gap-4 mb-4 grid-cols-2">
                    <div class="col-span-2">
                        <label for="title" class="block mb-2 text-sm font-medium text-gray-900 dark:text-white" data-i18n="tasks.field_title">
                            Título
                        </label>
                        <input 
                            type="text" 
                            name="title" 
                            id="title" 
                            class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-primary-600 focus:border-primary-600 block w-full p-2.5 dark:bg-gray-600 dark:border-gray-500 dark:placeholder-gray-400 dark:text-white dark:focus:ring-primary-500 dark:focus:border-primary-500" 
                            required>
                    </div>
                </div>
                <button type="submit" class="text-white inline-flex items-center bg-blue-700 hover:bg-blue-800 focus:ring-4 focus:outline-none focus:ring-blue-300 font-medium rounded-lg text-sm px-5 py-2.5 text-center dark:bg-blue-600 dark:hover:bg-blue-700 dark:focus:ring-blue-800">
                    <i class="fas fa-save mr-2"></i>
                    <span data-i18n="common.save">Guardar</span>
                </button>
            </form>
        </div>
    </div>
</div>
```

### 2. Cards with Stats

```html
<div class="bg-white dark:bg-gray-800 rounded-lg shadow p-6 border-l-4 border-indigo-500">
    <div class="flex items-center justify-between">
        <div>
            <p class="text-sm font-medium text-gray-600 dark:text-gray-400" data-i18n="dashboard.completed_tasks">
                Tareas Completadas
            </p>
            <p class="text-3xl font-bold text-gray-900 dark:text-white">
                {{ completed_count }}
            </p>
        </div>
        <div class="text-4xl">✅</div>
    </div>
</div>
```

### 3. Dropdown Menus

```html
<button 
    id="dropdownDefaultButton" 
    data-dropdown-toggle="dropdown" 
    class="text-white bg-blue-700 hover:bg-blue-800 focus:ring-4 focus:outline-none focus:ring-blue-300 font-medium rounded-lg text-sm px-5 py-2.5 text-center inline-flex items-center dark:bg-blue-600 dark:hover:bg-blue-700 dark:focus:ring-blue-800" 
    type="button">
    <span data-i18n="common.actions">Acciones</span>
    <svg class="w-2.5 h-2.5 ms-3" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 10 6">
        <path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="m1 1 4 4 4-4"/>
    </svg>
</button>

<div id="dropdown" class="z-10 hidden bg-white divide-y divide-gray-100 rounded-lg shadow w-44 dark:bg-gray-700">
    <ul class="py-2 text-sm text-gray-700 dark:text-gray-200" aria-labelledby="dropdownDefaultButton">
        <li>
            <a href="#" class="block px-4 py-2 hover:bg-gray-100 dark:hover:bg-gray-600 dark:hover:text-white" data-i18n="common.edit">
                Editar
            </a>
        </li>
        <li>
            <a href="#" class="block px-4 py-2 hover:bg-gray-100 dark:hover:bg-gray-600 dark:hover:text-white" data-i18n="common.delete">
                Eliminar
            </a>
        </li>
    </ul>
</div>
```

### 4. Sidebar Navigation

```html
<aside id="sidebar" class="fixed top-0 left-0 z-40 w-64 h-screen pt-20 transition-transform -translate-x-full bg-white border-r border-gray-200 sm:translate-x-0 dark:bg-gray-800 dark:border-gray-700" aria-label="Sidebar">
    <div class="h-full px-3 pb-4 overflow-y-auto bg-white dark:bg-gray-800">
        <ul class="space-y-2 font-medium">
            <li>
                <a href="/dashboard" class="flex items-center p-2 text-gray-900 rounded-lg dark:text-white hover:bg-gray-100 dark:hover:bg-gray-700 group">
                    <i class="fas fa-home"></i>
                    <span class="ms-3" data-i18n="nav.dashboard">Dashboard</span>
                </a>
            </li>
            <li>
                <a href="/tasks" class="flex items-center p-2 text-gray-900 rounded-lg dark:text-white hover:bg-gray-100 dark:hover:bg-gray-700 group">
                    <i class="fas fa-tasks"></i>
                    <span class="ms-3" data-i18n="nav.tasks">Tareas</span>
                </a>
            </li>
        </ul>
    </div>
</aside>
```

### 5. Alerts

```html
<div class="flex items-center p-4 mb-4 text-sm text-blue-800 rounded-lg bg-blue-50 dark:bg-gray-800 dark:text-blue-400" role="alert">
    <i class="fas fa-info-circle flex-shrink-0 inline w-4 h-4 me-3"></i>
    <span class="sr-only">Info</span>
    <div>
        <span class="font-medium" data-i18n="alerts.info_title">Info alert!</span>
        <span data-i18n="alerts.info_message">Change a few things up and try again.</span>
    </div>
</div>
```

---

## Dark Mode

### Toggle Implementation

```html
<!-- Dark mode toggle button -->
<button 
    id="theme-toggle" 
    type="button" 
    class="text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 focus:outline-none focus:ring-4 focus:ring-gray-200 dark:focus:ring-gray-700 rounded-lg text-sm p-2.5">
    <svg id="theme-toggle-dark-icon" class="hidden w-5 h-5" fill="currentColor" viewBox="0 0 20 20" xmlns="http://www.w3.org/2000/svg">
        <path d="M17.293 13.293A8 8 0 016.707 2.707a8.001 8.001 0 1010.586 10.586z"></path>
    </svg>
    <svg id="theme-toggle-light-icon" class="hidden w-5 h-5" fill="currentColor" viewBox="0 0 20 20" xmlns="http://www.w3.org/2000/svg">
        <path d="M10 2a1 1 0 011 1v1a1 1 0 11-2 0V3a1 1 0 011-1zm4 8a4 4 0 11-8 0 4 4 0 018 0zm-.464 4.95l.707.707a1 1 0 001.414-1.414l-.707-.707a1 1 0 00-1.414 1.414zm2.12-10.607a1 1 0 010 1.414l-.706.707a1 1 0 11-1.414-1.414l.707-.707a1 1 0 011.414 0zM17 11a1 1 0 100-2h-1a1 1 0 100 2h1zm-7 4a1 1 0 011 1v1a1 1 0 11-2 0v-1a1 1 0 011-1zM5.05 6.464A1 1 0 106.465 5.05l-.708-.707a1 1 0 00-1.414 1.414l.707.707zm1.414 8.486l-.707.707a1 1 0 01-1.414-1.414l.707-.707a1 1 0 011.414 1.414zM4 11a1 1 0 100-2H3a1 1 0 000 2h1z" fill-rule="evenodd" clip-rule="evenodd"></path>
    </svg>
</button>
```

### Dark Mode Script (app/static/js/darkmode.js)

```javascript
// Dark mode toggle - ONLY allowed custom JS
const themeToggleBtn = document.getElementById('theme-toggle');
const themeToggleDarkIcon = document.getElementById('theme-toggle-dark-icon');
const themeToggleLightIcon = document.getElementById('theme-toggle-light-icon');

// Change the icons inside the button based on previous settings
if (localStorage.getItem('color-theme') === 'dark' || (!('color-theme' in localStorage) && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
    themeToggleLightIcon.classList.remove('hidden');
    document.documentElement.classList.add('dark');
} else {
    themeToggleDarkIcon.classList.remove('hidden');
}

themeToggleBtn.addEventListener('click', function() {
    // toggle icons
    themeToggleDarkIcon.classList.toggle('hidden');
    themeToggleLightIcon.classList.toggle('hidden');

    // if set via local storage previously
    if (localStorage.getItem('color-theme')) {
        if (localStorage.getItem('color-theme') === 'light') {
            document.documentElement.classList.add('dark');
            localStorage.setItem('color-theme', 'dark');
        } else {
            document.documentElement.classList.remove('dark');
            localStorage.setItem('color-theme', 'light');
        }
    } else {
        if (document.documentElement.classList.contains('dark')) {
            document.documentElement.classList.remove('dark');
            localStorage.setItem('color-theme', 'light');
        } else {
            document.documentElement.classList.add('dark');
            localStorage.setItem('color-theme', 'dark');
        }
    }
});
```

---

## Internationalization (i18n)

### Translation System (app/static/js/translations.js)

```javascript
const translations = {
    es: {
        // Navigation
        "nav.dashboard": "Tablero",
        "nav.tasks": "Tareas",
        "nav.rewards": "Recompensas",
        "nav.consequences": "Consecuencias",
        
        // Common
        "common.save": "Guardar",
        "common.cancel": "Cancelar",
        "common.edit": "Editar",
        "common.delete": "Eliminar",
        "common.actions": "Acciones",
        
        // Tasks
        "tasks.title": "Tareas",
        "tasks.new": "Nueva Tarea",
        "tasks.create_title": "Crear Nueva Tarea",
        "tasks.field_title": "Título",
        "tasks.completed": "Completadas",
        "tasks.pending": "Pendientes",
        
        // Dashboard
        "dashboard.welcome": "Bienvenido",
        "dashboard.completed_tasks": "Tareas Completadas",
        "dashboard.pending_tasks": "Tareas Pendientes",
        "dashboard.total_points": "Puntos Totales"
    },
    en: {
        // Navigation
        "nav.dashboard": "Dashboard",
        "nav.tasks": "Tasks",
        "nav.rewards": "Rewards",
        "nav.consequences": "Consequences",
        
        // Common
        "common.save": "Save",
        "common.cancel": "Cancel",
        "common.edit": "Edit",
        "common.delete": "Delete",
        "common.actions": "Actions",
        
        // Tasks
        "tasks.title": "Tasks",
        "tasks.new": "New Task",
        "tasks.create_title": "Create New Task",
        "tasks.field_title": "Title",
        "tasks.completed": "Completed",
        "tasks.pending": "Pending",
        
        // Dashboard
        "dashboard.welcome": "Welcome",
        "dashboard.completed_tasks": "Completed Tasks",
        "dashboard.pending_tasks": "Pending Tasks",
        "dashboard.total_points": "Total Points"
    }
};

// Get current language from localStorage or default to Spanish
let currentLang = localStorage.getItem('language') || 'es';

// Translate page
function translatePage() {
    document.querySelectorAll('[data-i18n]').forEach(element => {
        const key = element.getAttribute('data-i18n');
        if (translations[currentLang][key]) {
            element.textContent = translations[currentLang][key];
        }
    });
}

// Language toggle
function setLanguage(lang) {
    currentLang = lang;
    localStorage.setItem('language', lang);
    translatePage();
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', translatePage);
```

### Usage in Templates

```html
<!-- Add data-i18n attribute to ALL user-facing text -->
<h1 class="text-3xl font-bold" data-i18n="tasks.title">Tareas</h1>
<button data-i18n="common.save">Guardar</button>
<p data-i18n="dashboard.welcome">Bienvenido</p>

<!-- Language switcher -->
<button onclick="setLanguage('es')" class="px-3 py-2">🇪🇸 ES</button>
<button onclick="setLanguage('en')" class="px-3 py-2">🇺🇸 EN</button>
```

---

## Forms

### Form Structure

```html
<form method="post" action="/tasks/new" class="space-y-4">
    <!-- Text Input -->
    <div>
        <label for="title" class="block mb-2 text-sm font-medium text-gray-900 dark:text-white" data-i18n="tasks.field_title">
            Título
        </label>
        <input 
            type="text" 
            name="title" 
            id="title" 
            class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-blue-500 focus:border-blue-500 block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white dark:focus:ring-blue-500 dark:focus:border-blue-500"
            required>
    </div>
    
    <!-- Select -->
    <div>
        <label for="frequency" class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">
            Frecuencia
        </label>
        <select 
            id="frequency" 
            name="frequency"
            class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-blue-500 focus:border-blue-500 block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white dark:focus:ring-blue-500 dark:focus:border-blue-500">
            <option selected>Seleccionar</option>
            <option value="once">Una vez</option>
            <option value="daily">Diario</option>
            <option value="weekly">Semanal</option>
        </select>
    </div>
    
    <!-- Textarea -->
    <div>
        <label for="description" class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">
            Descripción
        </label>
        <textarea 
            id="description" 
            name="description" 
            rows="4" 
            class="block p-2.5 w-full text-sm text-gray-900 bg-gray-50 rounded-lg border border-gray-300 focus:ring-blue-500 focus:border-blue-500 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white dark:focus:ring-blue-500 dark:focus:border-blue-500"></textarea>
    </div>
    
    <!-- Submit Button -->
    <button 
        type="submit" 
        class="text-white bg-blue-700 hover:bg-blue-800 focus:ring-4 focus:outline-none focus:ring-blue-300 font-medium rounded-lg text-sm w-full sm:w-auto px-5 py-2.5 text-center dark:bg-blue-600 dark:hover:bg-blue-700 dark:focus:ring-blue-800">
        <span data-i18n="common.save">Guardar</span>
    </button>
</form>
```

---

## Best Practices

### ✅ DO
- Use Flowbite components with `data-*` attributes
- Use Tailwind CSS utility classes
- Include dark mode classes (`dark:*`)
- Add `data-i18n` to ALL user-facing text
- Follow PRG pattern for forms
- Use semantic HTML5 elements
- Add proper ARIA labels for accessibility
- Use Font Awesome for icons consistently

### ❌ DON'T
- Write custom JavaScript (except darkmode.js and translations.js)
- Use inline styles
- Return `TemplateResponse` from POST routes
- Forget dark mode classes
- Forget i18n attributes
- Create new `Jinja2Templates` instances (use shared)
- Hardcode text without translations

---

## Accessibility

- **ALWAYS** include ARIA labels
- Use semantic HTML elements (`<nav>`, `<main>`, `<aside>`, etc.)
- Ensure proper keyboard navigation
- Include `sr-only` classes for screen readers
- Use sufficient color contrast (WCAG AA minimum)

```html
<button 
    aria-label="Close modal"
    data-modal-hide="modal-id">
    <svg class="w-3 h-3" aria-hidden="true">...</svg>
    <span class="sr-only">Close</span>
</button>
```

---

## Resources

- **Flowbite Documentation**: https://flowbite.com/docs/
- **Tailwind CSS**: https://tailwindcss.com/docs
- **Font Awesome**: https://fontawesome.com/icons
- **WCAG Guidelines**: https://www.w3.org/WAI/WCAG21/quickref/

---

**Remember**: This is an SSR-first application. All pages are rendered server-side with Jinja2. The only client-side JavaScript allowed is Flowbite.min.js, darkmode.js, and translations.js.
