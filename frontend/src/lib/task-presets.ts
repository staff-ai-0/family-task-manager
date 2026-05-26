export interface TaskPreset {
  emoji: string;
  title: string;
  effort_level: 1 | 2 | 3;
  interval_days: 1 | 3 | 7;
}

export const TASK_PRESETS: TaskPreset[] = [
  { emoji: "🍽️", title: "Wash Dishes",          effort_level: 1, interval_days: 1 },
  { emoji: "🗑️", title: "Take Out Trash",        effort_level: 1, interval_days: 7 },
  { emoji: "🧹", title: "Sweep Floor",            effort_level: 1, interval_days: 1 },
  { emoji: "🛏️", title: "Make Bed",               effort_level: 1, interval_days: 1 },
  { emoji: "🧴", title: "Wipe Kitchen Counter",   effort_level: 1, interval_days: 1 },
  { emoji: "🌿", title: "Water Plants",            effort_level: 1, interval_days: 3 },
  { emoji: "🐕", title: "Walk Dog",               effort_level: 1, interval_days: 1 },
  { emoji: "🐾", title: "Feed Pets",              effort_level: 1, interval_days: 1 },
  { emoji: "🧺", title: "Do Laundry",             effort_level: 2, interval_days: 7 },
  { emoji: "🧽", title: "Clean Bathroom",          effort_level: 2, interval_days: 7 },
  { emoji: "🏠", title: "Vacuum Living Room",      effort_level: 2, interval_days: 7 },
  { emoji: "🍳", title: "Help Cook Dinner",        effort_level: 2, interval_days: 1 },
  { emoji: "📚", title: "Study / Homework",        effort_level: 2, interval_days: 1 },
  { emoji: "🛒", title: "Help Grocery Shopping",   effort_level: 2, interval_days: 7 },
  { emoji: "🪟", title: "Clean Windows",           effort_level: 2, interval_days: 7 },
  { emoji: "🚗", title: "Wash Car",               effort_level: 3, interval_days: 7 },
  { emoji: "🌿", title: "Mow Lawn",               effort_level: 3, interval_days: 7 },
  { emoji: "📦", title: "Organize Closet",         effort_level: 3, interval_days: 7 },
  { emoji: "🧹", title: "Clean Garage",            effort_level: 3, interval_days: 7 },
];
