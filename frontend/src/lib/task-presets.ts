export interface TaskPreset {
  emoji: string;
  title: string;
  title_es: string;
  effort_level: 1 | 2 | 3;
  interval_days: 1 | 3 | 7;
}

export const TASK_PRESETS: TaskPreset[] = [
  { emoji: "🍽️", title: "Wash Dishes",          title_es: "Lavar platos",                  effort_level: 1, interval_days: 1 },
  { emoji: "🗑️", title: "Take Out Trash",        title_es: "Sacar la basura",               effort_level: 1, interval_days: 7 },
  { emoji: "🧹", title: "Sweep Floor",            title_es: "Barrer el piso",                effort_level: 1, interval_days: 1 },
  { emoji: "🛏️", title: "Make Bed",               title_es: "Tender la cama",                effort_level: 1, interval_days: 1 },
  { emoji: "🧴", title: "Wipe Kitchen Counter",   title_es: "Limpiar la barra de la cocina", effort_level: 1, interval_days: 1 },
  { emoji: "🌿", title: "Water Plants",            title_es: "Regar las plantas",             effort_level: 1, interval_days: 3 },
  { emoji: "🐕", title: "Walk Dog",               title_es: "Pasear al perro",               effort_level: 1, interval_days: 1 },
  { emoji: "🐾", title: "Feed Pets",              title_es: "Dar de comer a las mascotas",   effort_level: 1, interval_days: 1 },
  { emoji: "🧺", title: "Do Laundry",             title_es: "Lavar la ropa",                 effort_level: 2, interval_days: 7 },
  { emoji: "🧽", title: "Clean Bathroom",          title_es: "Limpiar el baño",               effort_level: 2, interval_days: 7 },
  { emoji: "🏠", title: "Vacuum Living Room",      title_es: "Aspirar la sala",               effort_level: 2, interval_days: 7 },
  { emoji: "🍳", title: "Help Cook Dinner",        title_es: "Ayudar a hacer la cena",        effort_level: 2, interval_days: 1 },
  { emoji: "📚", title: "Study / Homework",        title_es: "Estudiar / Tarea escolar",      effort_level: 2, interval_days: 1 },
  { emoji: "🛒", title: "Help Grocery Shopping",   title_es: "Ayudar con el súper",           effort_level: 2, interval_days: 7 },
  { emoji: "🪟", title: "Clean Windows",           title_es: "Limpiar las ventanas",          effort_level: 2, interval_days: 7 },
  { emoji: "🚗", title: "Wash Car",               title_es: "Lavar el coche",                effort_level: 3, interval_days: 7 },
  { emoji: "🌿", title: "Mow Lawn",               title_es: "Cortar el pasto",               effort_level: 3, interval_days: 7 },
  { emoji: "📦", title: "Organize Closet",         title_es: "Organizar el clóset",           effort_level: 3, interval_days: 7 },
  { emoji: "🧹", title: "Clean Garage",            title_es: "Limpiar la cochera",            effort_level: 3, interval_days: 7 },
];
