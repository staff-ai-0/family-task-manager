---
applyTo: "app/templates/**/*.html,app/static/**/*.css,app/static/**/*.js"
---

# Frontend UI/UX Guidelines

## 🚨 MANDATORY: Code Quality and Maintenance Rules

### 🧹 **MANDATORY: Template Cleanup Rule**

**WHEN making ANY frontend changes, you MUST clean up:**

1. **🔍 Remove Unused Imports**: Delete unused CSS/JS libraries
2. **🗑️ Delete Dead HTML**: Remove commented-out template blocks
3. **📝 Consolidate Styles**: Move inline styles to CSS classes
4. **🔄 Reusable Components**: Extract repeated template patterns to partials
5. **📚 Update Documentation**: Keep component documentation current

## 🎨 Flowbite Component Guidelines

### Recommended Component Usage

**Task Cards**:
```html
<div class="max-w-sm p-6 bg-white border border-gray-200 rounded-lg shadow hover:bg-gray-100">
    <div class="flex justify-between items-start mb-2">
        <h5 class="mb-2 text-2xl font-bold tracking-tight text-gray-900">
            {{ task.title }}
        </h5>
        {% if task.is_default %}
        <span class="bg-red-100 text-red-800 text-xs font-medium px-2.5 py-0.5 rounded">
            Obligatoria
        </span>
        {% else %}
        <span class="bg-blue-100 text-blue-800 text-xs font-medium px-2.5 py-0.5 rounded">
            Extra
        </span>
        {% endif %}
    </div>
    
    <p class="mb-3 font-normal text-gray-700">{{ task.description }}</p>
    
    <div class="flex justify-between items-center">
        <span class="text-sm text-gray-500">
            <i class="fas fa-coins"></i> {{ task.points }} puntos
        </span>
        
        {% if task.status == 'PENDING' %}
        <button 
            hx-patch="/api/tasks/{{ task.id }}/complete"
            hx-target="#task-{{ task.id }}"
            hx-swap="outerHTML"
            class="text-white bg-green-700 hover:bg-green-800 focus:ring-4 focus:ring-green-300 font-medium rounded-lg text-sm px-5 py-2.5">
            Completar
        </button>
        {% else %}
        <span class="text-green-600 font-semibold">
            <i class="fas fa-check-circle"></i> Completada
        </span>
        {% endif %}
    </div>
</div>
```

**Reward Cards**:
```html
<div class="w-full max-w-sm bg-white border border-gray-200 rounded-lg shadow">
    <div class="px-5 pb-5">
        <div class="flex items-center justify-center h-32 bg-gradient-to-br from-purple-400 to-pink-400 rounded-t-lg">
            <i class="{{ reward.icon }} text-5xl text-white"></i>
        </div>
        
        <h5 class="mt-4 text-xl font-semibold tracking-tight text-gray-900">
            {{ reward.title }}
        </h5>
        
        <p class="mt-2 text-sm text-gray-600">{{ reward.description }}</p>
        
        <div class="flex items-center justify-between mt-4">
            <span class="text-2xl font-bold text-gray-900">
                {{ reward.points_cost }} <i class="fas fa-coins text-yellow-500"></i>
            </span>
            
            <button 
                x-data="{ disabled: {{ user.points }} < {{ reward.points_cost }} }"
                :disabled="disabled"
                @click="$dispatch('redeem-reward', { rewardId: '{{ reward.id }}' })"
                :class="disabled ? 'bg-gray-300 cursor-not-allowed' : 'bg-blue-700 hover:bg-blue-800'"
                class="text-white font-medium rounded-lg text-sm px-5 py-2.5 text-center">
                Canjear
            </button>
        </div>
    </div>
</div>
```

**Progress Bars**:
```html
<!-- Daily task completion progress -->
<div class="w-full bg-gray-200 rounded-full h-2.5">
    <div 
        class="bg-green-600 h-2.5 rounded-full transition-all duration-500" 
        style="width: {{ completion_percentage }}%">
    </div>
</div>
<p class="text-sm text-gray-600 mt-1">
    {{ completed_tasks }} de {{ total_tasks }} tareas completadas
</p>
```

**Modal for Reward Redemption**:
```html
<!-- Modal toggle button -->
<button 
    data-modal-target="redemption-modal-{{ reward.id }}" 
    data-modal-toggle="redemption-modal-{{ reward.id }}" 
    class="block text-white bg-blue-700 hover:bg-blue-800 focus:ring-4 focus:outline-none focus:ring-blue-300 font-medium rounded-lg text-sm px-5 py-2.5 text-center" 
    type="button">
    Canjear
</button>

<!-- Main modal -->
<div id="redemption-modal-{{ reward.id }}" tabindex="-1" aria-hidden="true" class="hidden overflow-y-auto overflow-x-hidden fixed top-0 right-0 left-0 z-50 justify-center items-center w-full md:inset-0 h-[calc(100%-1rem)] max-h-full">
    <div class="relative p-4 w-full max-w-md max-h-full">
        <div class="relative bg-white rounded-lg shadow">
            <div class="flex items-center justify-between p-4 md:p-5 border-b rounded-t">
                <h3 class="text-xl font-semibold text-gray-900">
                    Confirmar Canje
                </h3>
                <button type="button" class="text-gray-400 bg-transparent hover:bg-gray-200 hover:text-gray-900 rounded-lg text-sm w-8 h-8 ms-auto inline-flex justify-center items-center" data-modal-hide="redemption-modal-{{ reward.id }}">
                    <svg class="w-3 h-3" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 14 14">
                        <path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="m1 1 6 6m0 0 6 6M7 7l6-6M7 7l-6 6"/>
                    </svg>
                </button>
            </div>
            <div class="p-4 md:p-5 space-y-4">
                <p class="text-base leading-relaxed text-gray-500">
                    ¿Estás seguro de que quieres canjear <strong>{{ reward.title }}</strong> por {{ reward.points_cost }} puntos?
                </p>
                <p class="text-sm text-gray-400">
                    Te quedarán {{ user.points - reward.points_cost }} puntos.
                </p>
            </div>
            <div class="flex items-center p-4 md:p-5 border-t border-gray-200 rounded-b">
                <button 
                    hx-post="/api/rewards/{{ reward.id }}/redeem"
                    hx-target="#user-points"
                    hx-swap="innerHTML"
                    data-modal-hide="redemption-modal-{{ reward.id }}" 
                    type="button" 
                    class="text-white bg-blue-700 hover:bg-blue-800 focus:ring-4 focus:outline-none focus:ring-blue-300 font-medium rounded-lg text-sm px-5 py-2.5 text-center">
                    Confirmar
                </button>
                <button 
                    data-modal-hide="redemption-modal-{{ reward.id }}" 
                    type="button" 
                    class="py-2.5 px-5 ms-3 text-sm font-medium text-gray-900 focus:outline-none bg-white rounded-lg border border-gray-200 hover:bg-gray-100 hover:text-blue-700 focus:z-10 focus:ring-4 focus:ring-gray-100">
                    Cancelar
                </button>
            </div>
        </div>
    </div>
</div>
```

**Alert Messages**:
```html
<!-- Success alert -->
<div class="p-4 mb-4 text-sm text-green-800 rounded-lg bg-green-50" role="alert">
    <span class="font-medium">¡Éxito!</span> La tarea se completó correctamente.
</div>

<!-- Error alert -->
<div class="p-4 mb-4 text-sm text-red-800 rounded-lg bg-red-50" role="alert">
    <span class="font-medium">Error!</span> No tienes suficientes puntos.
</div>

<!-- Warning alert (consequence) -->
<div class="p-4 mb-4 text-sm text-yellow-800 rounded-lg bg-yellow-50" role="alert">
    <span class="font-medium">Atención!</span> Tienes consecuencias activas.
</div>
```

## HTMX Integration Patterns

### Task Completion

```html
<!-- Task card with HTMX -->
<div id="task-{{ task.id }}" class="task-card">
    <h3>{{ task.title }}</h3>
    <button 
        hx-patch="/api/tasks/{{ task.id }}/complete"
        hx-trigger="click"
        hx-target="#task-{{ task.id }}"
        hx-swap="outerHTML"
        hx-indicator="#spinner-{{ task.id }}"
        class="btn-complete">
        Completar
    </button>
    <div id="spinner-{{ task.id }}" class="htmx-indicator">
        <svg class="animate-spin h-5 w-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
    </div>
</div>
```

### Points Update

```html
<!-- Live points counter -->
<div id="user-points" class="flex items-center gap-2">
    <i class="fas fa-coins text-yellow-500 text-xl"></i>
    <span class="text-2xl font-bold">{{ user.points }}</span>
</div>

<!-- When task is completed, backend returns updated points HTML -->
<!-- Backend endpoint should return: -->
<!-- <div id="user-points" class="flex items-center gap-2">
    <i class="fas fa-coins text-yellow-500 text-xl"></i>
    <span class="text-2xl font-bold">150</span>
</div> -->
```

### Form Submission

```html
<form 
    hx-post="/api/tasks"
    hx-target="#task-list"
    hx-swap="beforeend"
    hx-on::after-request="this.reset()">
    
    <input 
        type="text" 
        name="title" 
        class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-blue-500 focus:border-blue-500 block w-full p-2.5" 
        placeholder="Nombre de la tarea" 
        required>
    
    <textarea 
        name="description" 
        rows="4" 
        class="block p-2.5 w-full text-sm text-gray-900 bg-gray-50 rounded-lg border border-gray-300 focus:ring-blue-500 focus:border-blue-500" 
        placeholder="Descripción..."></textarea>
    
    <button type="submit" class="text-white bg-blue-700 hover:bg-blue-800 focus:ring-4 focus:ring-blue-300 font-medium rounded-lg text-sm px-5 py-2.5">
        Crear Tarea
    </button>
</form>
```

## Alpine.js Interactivity

### Reactive Points Display

```html
<div x-data="{ 
    points: {{ user.points }},
    requiredPoints: {{ reward.points_cost }},
    get canRedeem() { return this.points >= this.requiredPoints; }
}">
    <div class="text-center">
        <p class="text-lg">Tus puntos: <span x-text="points" class="font-bold"></span></p>
        <p class="text-sm text-gray-600">Puntos necesarios: <span x-text="requiredPoints"></span></p>
    </div>
    
    <button 
        :disabled="!canRedeem"
        :class="canRedeem ? 'bg-blue-700 hover:bg-blue-800' : 'bg-gray-300 cursor-not-allowed'"
        class="text-white font-medium rounded-lg text-sm px-5 py-2.5">
        <span x-show="canRedeem">Canjear Recompensa</span>
        <span x-show="!canRedeem">Puntos insuficientes</span>
    </button>
</div>
```

### Task Filter

```html
<div x-data="{ 
    filter: 'all',
    tasks: {{ tasks | tojson }}
}">
    <!-- Filter buttons -->
    <div class="flex gap-2 mb-4">
        <button 
            @click="filter = 'all'"
            :class="filter === 'all' ? 'bg-blue-700 text-white' : 'bg-gray-200 text-gray-700'"
            class="px-4 py-2 rounded-lg">
            Todas
        </button>
        <button 
            @click="filter = 'default'"
            :class="filter === 'default' ? 'bg-blue-700 text-white' : 'bg-gray-200 text-gray-700'"
            class="px-4 py-2 rounded-lg">
            Obligatorias
        </button>
        <button 
            @click="filter = 'extra'"
            :class="filter === 'extra' ? 'bg-blue-700 text-white' : 'bg-gray-200 text-gray-700'"
            class="px-4 py-2 rounded-lg">
            Extras
        </button>
    </div>
    
    <!-- Task list -->
    <div class="grid gap-4">
        <template x-for="task in tasks" :key="task.id">
            <div 
                x-show="filter === 'all' || (filter === 'default' && task.is_default) || (filter === 'extra' && !task.is_default)"
                class="task-card">
                <h3 x-text="task.title"></h3>
                <p x-text="task.description"></p>
            </div>
        </template>
    </div>
</div>
```

### Consequence Banner

```html
<div 
    x-data="{ 
        hasConsequences: {{ 'true' if active_consequences else 'false' }},
        consequences: {{ active_consequences | tojson }}
    }"
    x-show="hasConsequences"
    class="bg-red-100 border-l-4 border-red-500 text-red-700 p-4 mb-4">
    
    <div class="flex items-center">
        <i class="fas fa-exclamation-triangle text-2xl mr-3"></i>
        <div>
            <p class="font-bold">Tienes consecuencias activas:</p>
            <template x-for="consequence in consequences" :key="consequence.id">
                <p class="text-sm" x-text="consequence.description"></p>
            </template>
        </div>
    </div>
</div>
```

## Responsive Design Patterns

### Mobile-First Grid Layout

```html
<!-- Dashboard grid -->
<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
    <!-- Task cards -->
    {% for task in tasks %}
    <div class="task-card">
        <!-- Card content -->
    </div>
    {% endfor %}
</div>
```

### Responsive Navigation

```html
<nav class="bg-white border-gray-200 px-4 lg:px-6 py-2.5">
    <div class="flex flex-wrap justify-between items-center mx-auto max-w-screen-xl">
        <a href="/" class="flex items-center">
            <span class="self-center text-xl font-semibold whitespace-nowrap">Family Tasks</span>
        </a>
        
        <button 
            data-collapse-toggle="mobile-menu" 
            type="button" 
            class="inline-flex items-center p-2 ml-1 text-sm text-gray-500 rounded-lg lg:hidden hover:bg-gray-100 focus:outline-none focus:ring-2 focus:ring-gray-200">
            <svg class="w-6 h-6" fill="currentColor" viewBox="0 0 20 20" xmlns="http://www.w3.org/2000/svg">
                <path fill-rule="evenodd" d="M3 5a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zM3 10a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zM3 15a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1z" clip-rule="evenodd"></path>
            </svg>
        </button>
        
        <div class="hidden justify-between items-center w-full lg:flex lg:w-auto lg:order-1" id="mobile-menu">
            <ul class="flex flex-col mt-4 font-medium lg:flex-row lg:space-x-8 lg:mt-0">
                <li><a href="/dashboard" class="block py-2 pr-4 pl-3 text-gray-700 hover:text-blue-700">Dashboard</a></li>
                <li><a href="/tasks" class="block py-2 pr-4 pl-3 text-gray-700 hover:text-blue-700">Tareas</a></li>
                <li><a href="/rewards" class="block py-2 pr-4 pl-3 text-gray-700 hover:text-blue-700">Recompensas</a></li>
            </ul>
        </div>
    </div>
</nav>
```

## Custom CSS Guidelines

### Color Scheme

```css
/* app/static/css/custom.css */

:root {
    /* Primary colors */
    --primary-blue: #1e40af;
    --primary-green: #059669;
    --primary-red: #dc2626;
    --primary-yellow: #f59e0b;
    
    /* Background colors */
    --bg-light: #f9fafb;
    --bg-white: #ffffff;
    
    /* Text colors */
    --text-dark: #1f2937;
    --text-gray: #6b7280;
}

.badge-default {
    background-color: var(--primary-red);
    color: white;
    padding: 0.25rem 0.75rem;
    border-radius: 0.375rem;
    font-size: 0.75rem;
    font-weight: 500;
}

.badge-extra {
    background-color: var(--primary-blue);
    color: white;
    padding: 0.25rem 0.75rem;
    border-radius: 0.375rem;
    font-size: 0.75rem;
    font-weight: 500;
}

.task-card-completed {
    opacity: 0.7;
    border: 2px solid var(--primary-green);
}
```

### Animations

```css
@keyframes slideIn {
    from {
        transform: translateX(-100%);
        opacity: 0;
    }
    to {
        transform: translateX(0);
        opacity: 1;
    }
}

.task-card-enter {
    animation: slideIn 0.3s ease-out;
}

.points-pulse {
    animation: pulse 1s ease-in-out;
}

@keyframes pulse {
    0%, 100% {
        transform: scale(1);
    }
    50% {
        transform: scale(1.1);
    }
}
```

## Accessibility Guidelines

### ARIA Labels

```html
<!-- Task completion button -->
<button 
    aria-label="Completar tarea: {{ task.title }}"
    hx-patch="/api/tasks/{{ task.id }}/complete">
    Completar
</button>

<!-- Points display -->
<div role="status" aria-live="polite" id="user-points">
    <span aria-label="Puntos actuales: {{ user.points }}">
        {{ user.points }} puntos
    </span>
</div>
```

### Keyboard Navigation

```html
<!-- Ensure all interactive elements are keyboard accessible -->
<div 
    tabindex="0" 
    role="button"
    @keydown.enter="completeTask()"
    @keydown.space="completeTask()"
    class="task-card">
    <!-- Content -->
</div>
```

---

**Last Updated**: December 11, 2025
