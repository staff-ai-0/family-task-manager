type ToastType = 'success' | 'error' | 'info';

const ICONS: Record<ToastType, string> = {
  success: `<svg class="w-5 h-5 text-green-600 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>`,
  error: `<svg class="w-5 h-5 text-red-600 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>`,
  info: `<svg class="w-5 h-5 text-blue-600 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>`,
};

const BORDER_COLORS: Record<ToastType, string> = {
  success: 'border-green-500',
  error: 'border-red-500',
  info: 'border-blue-500',
};

const BAR_COLORS: Record<ToastType, string> = {
  success: 'bg-green-500',
  error: 'bg-red-500',
  info: 'bg-blue-500',
};

const MAX_VISIBLE = 3;

export function showToast(message: string, type: ToastType = 'info', durationMs: number = 4000): void {
  const container = document.getElementById('toast-container');
  if (!container) return;

  // Enforce max visible
  while (container.children.length >= MAX_VISIBLE) {
    container.removeChild(container.firstChild!);
  }

  const toast = document.createElement('div');
  toast.className = `pointer-events-auto bg-white border-l-4 ${BORDER_COLORS[type]} shadow-lg rounded-lg p-4 flex items-start gap-3 animate-slide-in relative overflow-hidden`;
  toast.style.cssText = `--toast-duration: ${durationMs}ms`;
  toast.innerHTML = `
    ${ICONS[type]}
    <p class="text-sm text-slate-700 flex-1">${escapeHtml(message)}</p>
    <button class="text-slate-400 hover:text-slate-600 text-lg leading-none flex-shrink-0">&times;</button>
    <div class="absolute bottom-0 left-0 h-0.5 ${BAR_COLORS[type]} animate-countdown"></div>
  `;

  // Click to dismiss
  toast.querySelector('button')!.addEventListener('click', () => remove(toast));

  // Auto-dismiss with pause-on-hover
  let remaining = durationMs;
  let start = Date.now();
  let timer = setTimeout(() => remove(toast), remaining);

  toast.addEventListener('mouseenter', () => {
    clearTimeout(timer);
    remaining -= Date.now() - start;
    toast.style.animationPlayState = 'paused';
    const bar = toast.querySelector<HTMLElement>('.animate-countdown');
    if (bar) bar.style.animationPlayState = 'paused';
  });

  toast.addEventListener('mouseleave', () => {
    start = Date.now();
    timer = setTimeout(() => remove(toast), remaining);
    toast.style.animationPlayState = 'running';
    const bar = toast.querySelector<HTMLElement>('.animate-countdown');
    if (bar) bar.style.animationPlayState = 'running';
  });

  container.appendChild(toast);
}

function remove(el: HTMLElement): void {
  el.style.opacity = '0';
  el.style.transform = 'translateX(100%)';
  el.style.transition = 'opacity 0.2s, transform 0.2s';
  setTimeout(() => el.remove(), 200);
}

function escapeHtml(s: string): string {
  const div = document.createElement('div');
  div.textContent = s;
  return div.innerHTML;
}
