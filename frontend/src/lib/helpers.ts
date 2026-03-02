/**
 * Helper utilities for frontend pages
 */

/**
 * Get current month and year as numbers
 */
export function getCurrentMonth(): { year: number; month: number } {
  const now = new Date();
  return {
    year: now.getFullYear(),
    month: now.getMonth() + 1,
  };
}

/**
 * Format month name based on language
 */
export function getMonthName(monthNum: number, lang: string = "en"): string {
  const months = {
    en: ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
    es: ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"],
  };
  const monthList = months[lang as keyof typeof months] || months.en;
  return monthList[monthNum - 1] || "";
}

/**
 * Calculate previous month (handles year rollover)
 */
export function getPreviousMonth(month: number, year: number): { month: number; year: number } {
  if (month === 1) {
    return { month: 12, year: year - 1 };
  }
  return { month: month - 1, year };
}

/**
 * Calculate next month (handles year rollover)
 */
export function getNextMonth(month: number, year: number): { month: number; year: number } {
  if (month === 12) {
    return { month: 1, year: year + 1 };
  }
  return { month: month + 1, year };
}

/**
 * Check if given month/year is current month
 */
export function isCurrentMonth(month: number, year: number): boolean {
  const now = new Date();
  return year === now.getFullYear() && month === now.getMonth() + 1;
}
