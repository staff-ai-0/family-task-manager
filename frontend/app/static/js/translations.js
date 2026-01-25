// Multi-language translation system (i18n)
// This is the ONLY custom JavaScript allowed (besides darkmode.js)

const translations = {
    es: {
        // App
        "app.name": "Family Task Manager",
        
        // Navigation
        "nav.dashboard": "Dashboard",
        "nav.tasks": "Tareas",
        "nav.rewards": "Recompensas",
        "nav.consequences": "Consecuencias",
        "nav.points": "Puntos",
        "nav.family": "Familia",
        "nav.settings": "Configuración",
        "nav.profile": "Perfil",
        "nav.logout": "Cerrar Sesión",
        
        // Sidebar
        "sidebar.my_points": "Mis Puntos",
        
        // Common
        "common.save": "Guardar",
        "common.cancel": "Cancelar",
        "common.edit": "Editar",
        "common.delete": "Eliminar",
        "common.actions": "Acciones",
        "common.close": "Cerrar",
        "common.confirm": "Confirmar",
        "common.back": "Volver",
        "common.next": "Siguiente",
        "common.previous": "Anterior",
        "common.search": "Buscar",
        "common.filter": "Filtrar",
        "common.loading": "Cargando...",
        
        // Dashboard
        "dashboard.title": "Dashboard",
        "dashboard.welcome": "Bienvenido",
        "dashboard.completed_tasks": "Tareas Completadas",
        "dashboard.pending_tasks": "Tareas Pendientes",
        "dashboard.total_points": "Puntos Totales",
        "dashboard.active_consequences": "Consecuencias Activas",
        "dashboard.status_excellent": "¡Excelente!",
        "dashboard.today_tasks": "Tareas de Hoy",
        "dashboard.available_rewards": "Recompensas Disponibles",
        
        // Tasks
        "tasks.title": "Tareas",
        "tasks.new": "Nueva Tarea",
        "tasks.create_title": "Crear Nueva Tarea",
        "tasks.field_title": "Título",
        "tasks.field_description": "Descripción",
        "tasks.field_points": "Puntos",
        "tasks.field_frequency": "Frecuencia",
        "tasks.field_assigned_to": "Asignado a",
        "tasks.completed": "Completadas",
        "tasks.pending": "Pendientes",
        "tasks.complete": "Completar",
        "tasks.mandatory": "Obligatoria",
        "tasks.optional": "Opcional",
        "tasks.daily": "Diaria",
        "tasks.weekly": "Semanal",
        "tasks.once": "Una vez",
        
        // Rewards
        "rewards.title": "Recompensas",
        "rewards.new": "Nueva Recompensa",
        "rewards.create_title": "Crear Nueva Recompensa",
        "rewards.field_title": "Título",
        "rewards.field_description": "Descripción",
        "rewards.field_points_cost": "Costo en Puntos",
        "rewards.field_category": "Categoría",
        "rewards.redeem": "Canjear",
        "rewards.available": "Disponible",
        "rewards.not_enough_points": "puntos más",
        "rewards.redeemed": "Canjeada",
        "rewards.pending_approval": "Pendiente de Aprobación",
        
        // Consequences
        "consequences.title": "Consecuencias",
        "consequences.active": "Activas",
        "consequences.history": "Historial",
        "consequences.days_remaining": "días restantes",
        "consequences.severity_low": "Leve",
        "consequences.severity_medium": "Media",
        "consequences.severity_high": "Alta",
        
        // Points
        "points.title": "Historial de Puntos",
        "points.earned": "Ganados",
        "points.spent": "Gastados",
        "points.balance": "Saldo",
        "points.transaction_history": "Historial de Transacciones",
        
        // Family
        "family.title": "Gestión Familiar",
        "family.members": "Miembros",
        "family.add_member": "Agregar Miembro",
        
        // Alerts
        "alerts.success": "Éxito",
        "alerts.error": "Error",
        "alerts.warning": "Advertencia",
        "alerts.info": "Información"
    },
    en: {
        // App
        "app.name": "Family Task Manager",
        
        // Navigation
        "nav.dashboard": "Dashboard",
        "nav.tasks": "Tasks",
        "nav.rewards": "Rewards",
        "nav.consequences": "Consequences",
        "nav.points": "Points",
        "nav.family": "Family",
        "nav.settings": "Settings",
        "nav.profile": "Profile",
        "nav.logout": "Logout",
        
        // Sidebar
        "sidebar.my_points": "My Points",
        
        // Common
        "common.save": "Save",
        "common.cancel": "Cancel",
        "common.edit": "Edit",
        "common.delete": "Delete",
        "common.actions": "Actions",
        "common.close": "Close",
        "common.confirm": "Confirm",
        "common.back": "Back",
        "common.next": "Next",
        "common.previous": "Previous",
        "common.search": "Search",
        "common.filter": "Filter",
        "common.loading": "Loading...",
        
        // Dashboard
        "dashboard.title": "Dashboard",
        "dashboard.welcome": "Welcome",
        "dashboard.completed_tasks": "Completed Tasks",
        "dashboard.pending_tasks": "Pending Tasks",
        "dashboard.total_points": "Total Points",
        "dashboard.active_consequences": "Active Consequences",
        "dashboard.status_excellent": "Excellent!",
        "dashboard.today_tasks": "Today's Tasks",
        "dashboard.available_rewards": "Available Rewards",
        
        // Tasks
        "tasks.title": "Tasks",
        "tasks.new": "New Task",
        "tasks.create_title": "Create New Task",
        "tasks.field_title": "Title",
        "tasks.field_description": "Description",
        "tasks.field_points": "Points",
        "tasks.field_frequency": "Frequency",
        "tasks.field_assigned_to": "Assigned to",
        "tasks.completed": "Completed",
        "tasks.pending": "Pending",
        "tasks.complete": "Complete",
        "tasks.mandatory": "Mandatory",
        "tasks.optional": "Optional",
        "tasks.daily": "Daily",
        "tasks.weekly": "Weekly",
        "tasks.once": "Once",
        
        // Rewards
        "rewards.title": "Rewards",
        "rewards.new": "New Reward",
        "rewards.create_title": "Create New Reward",
        "rewards.field_title": "Title",
        "rewards.field_description": "Description",
        "rewards.field_points_cost": "Points Cost",
        "rewards.field_category": "Category",
        "rewards.redeem": "Redeem",
        "rewards.available": "Available",
        "rewards.not_enough_points": "more points needed",
        "rewards.redeemed": "Redeemed",
        "rewards.pending_approval": "Pending Approval",
        
        // Consequences
        "consequences.title": "Consequences",
        "consequences.active": "Active",
        "consequences.history": "History",
        "consequences.days_remaining": "days remaining",
        "consequences.severity_low": "Low",
        "consequences.severity_medium": "Medium",
        "consequences.severity_high": "High",
        
        // Points
        "points.title": "Points History",
        "points.earned": "Earned",
        "points.spent": "Spent",
        "points.balance": "Balance",
        "points.transaction_history": "Transaction History",
        
        // Family
        "family.title": "Family Management",
        "family.members": "Members",
        "family.add_member": "Add Member",
        
        // Alerts
        "alerts.success": "Success",
        "alerts.error": "Error",
        "alerts.warning": "Warning",
        "alerts.info": "Information"
    }
};

// Get current language from localStorage or default to Spanish
let currentLang = localStorage.getItem('language') || 'es';

// Translate page
function translatePage() {
    document.querySelectorAll('[data-i18n]').forEach(element => {
        const key = element.getAttribute('data-i18n');
        if (translations[currentLang] && translations[currentLang][key]) {
            element.textContent = translations[currentLang][key];
        }
    });
    
    // Update language indicator
    const langEs = document.getElementById('lang-es');
    const langEn = document.getElementById('lang-en');
    if (langEs && langEn) {
        if (currentLang === 'es') {
            langEs.classList.remove('hidden');
            langEn.classList.add('hidden');
        } else {
            langEn.classList.remove('hidden');
            langEs.classList.add('hidden');
        }
    }
}

// Language toggle
function setLanguage(lang) {
    currentLang = lang;
    localStorage.setItem('language', lang);
    translatePage();
}

// Toggle between languages
const languageToggle = document.getElementById('language-toggle');
if (languageToggle) {
    languageToggle.addEventListener('click', function() {
        setLanguage(currentLang === 'es' ? 'en' : 'es');
    });
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', translatePage);
