# Budget UX Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce 21 budget pages to 6 by consolidating into a Hub + Drawer architecture with a FAB for quick expense registration.

**Architecture:** Replace the current 6-tab BudgetNav with a 3-tab bar (Mes/Movimientos/Reportes) + hamburger drawer. Consolidate month+categories into the hub page, unify 4 report pages into sub-tabs, merge 5 settings pages into one accordion page. Add a floating action button (FAB) on all tabs for quick expense entry via modal.

**Tech Stack:** Astro 5, Tailwind CSS v4, vanilla JS for client-side interactivity (no new dependencies). Charts use inline SVG/CSS (no chart library — keep it lightweight, matching existing patterns).

---

## File Structure

### New files to create
- `frontend/src/components/BudgetNavNew.astro` — 3-tab navigation (Mes/Movimientos/Reportes) + hamburger icon
- `frontend/src/components/DrawerMenu.astro` — slide-out drawer with grouped links
- `frontend/src/components/FABButton.astro` — floating action button (+ icon)
- `frontend/src/components/FABModal.astro` — bottom-sheet modal for quick expense entry
- `frontend/src/components/ReportSubTabs.astro` — pill sub-tabs for report switching
- `frontend/src/components/PeriodSelector.astro` — shared period selector (1M/3M/6M/1A)
- `frontend/src/components/SettingsAccordion.astro` — collapsible section component
- `frontend/src/components/ReconcileModal.astro` — reconciliation modal for transactions page
- `frontend/src/components/CategoryProgressBar.astro` — progress bar with green/yellow/red thresholds
- `frontend/src/components/MonthSummaryBar.astro` — top summary (Ingresos/Gastado/Disponible + overall bar)
- `frontend/src/pages/budget/reports.astro` — unified reports page (replaces 4 report pages)

### Files to modify
- `frontend/src/pages/budget/index.astro` — rewrite as Hub + Month view
- `frontend/src/pages/budget/transactions.astro` — add filter bar, account selector, reconcile button
- `frontend/src/pages/budget/settings.astro` — rewrite as accordion with all settings sections
- `frontend/src/lib/i18n.ts` — add new translation keys

### Files to delete (after migration validated)
- `frontend/src/pages/budget/month/index.astro`
- `frontend/src/pages/budget/month/[year]/[month].astro`
- `frontend/src/pages/budget/categories/index.astro`
- `frontend/src/pages/budget/accounts/index.astro`
- `frontend/src/pages/budget/accounts/[id].astro`
- `frontend/src/pages/budget/accounts/[id]/reconcile.astro`
- `frontend/src/pages/budget/accounts/new.astro`
- `frontend/src/pages/budget/transactions/new.astro`
- `frontend/src/pages/budget/reports/spending.astro`
- `frontend/src/pages/budget/reports/income-vs-expense.astro`
- `frontend/src/pages/budget/reports/net-worth.astro`
- `frontend/src/pages/budget/reports/budget-analysis.astro`
- `frontend/src/pages/budget/settings/rules.astro`
- `frontend/src/pages/budget/settings/payees.astro`
- `frontend/src/pages/budget/settings/recurring.astro`
- `frontend/src/pages/budget/settings/backups.astro`

---

## Task 1: New 3-Tab Navigation + Drawer Menu

**Files:**
- Create: `frontend/src/components/BudgetNavNew.astro`
- Create: `frontend/src/components/DrawerMenu.astro`

This task builds the navigation skeleton that all pages will share.

- [ ] **Step 1: Create BudgetNavNew.astro**

```astro
---
interface Props {
    active: "month" | "transactions" | "reports";
    lang: "en" | "es";
}

const { active, lang } = Astro.props;

const tabs = [
    { id: "month", href: "/budget/", label: lang === "es" ? "Mes" : "Month", icon: "calendar" },
    { id: "transactions", href: "/budget/transactions", label: lang === "es" ? "Movimientos" : "Transactions", icon: "list" },
    { id: "reports", href: "/budget/reports", label: lang === "es" ? "Reportes" : "Reports", icon: "chart" },
];
---

<nav class="sticky top-0 z-20 bg-white border-b border-slate-200 shadow-sm">
    <div class="max-w-md md:max-w-4xl lg:max-w-6xl mx-auto flex items-center">
        <!-- Hamburger -->
        <button id="drawer-toggle" class="p-3 text-slate-500 hover:text-slate-700 transition-colors" aria-label="Menu">
            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16"/>
            </svg>
        </button>

        <!-- Tabs -->
        <div class="flex flex-1 justify-center gap-0">
            {tabs.map((tab) => (
                <a
                    href={tab.href}
                    class:list={[
                        "flex flex-col items-center px-5 py-2.5 text-xs font-medium transition-colors border-b-2",
                        active === tab.id
                            ? "text-primary-600 border-primary-600"
                            : "text-slate-400 border-transparent hover:text-slate-600",
                    ]}
                >
                    {tab.id === "month" && (
                        <svg class="w-5 h-5 mb-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/>
                        </svg>
                    )}
                    {tab.id === "transactions" && (
                        <svg class="w-5 h-5 mb-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"/>
                        </svg>
                    )}
                    {tab.id === "reports" && (
                        <svg class="w-5 h-5 mb-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"/>
                        </svg>
                    )}
                    <span>{tab.label}</span>
                </a>
            ))}
        </div>

        <!-- Spacer to balance hamburger -->
        <div class="w-12"></div>
    </div>
</nav>
```

- [ ] **Step 2: Create DrawerMenu.astro**

```astro
---
interface Props {
    lang: "en" | "es";
}

const { lang } = Astro.props;
const es = lang === "es";

const sections = [
    {
        title: es ? "Principal" : "Main",
        items: [
            { label: es ? "Vista del mes" : "Month View", href: "/budget/", icon: "📊" },
            { label: es ? "Movimientos" : "Transactions", href: "/budget/transactions", icon: "💳" },
            { label: es ? "Reportes" : "Reports", href: "/budget/reports", icon: "📈" },
        ],
    },
    {
        title: es ? "Gestión" : "Management",
        items: [
            { label: es ? "Cuentas" : "Accounts", href: "/budget/settings#accounts", icon: "🏦" },
            { label: es ? "Categorías" : "Categories", href: "/budget/settings#categories", icon: "📁" },
            { label: es ? "Beneficiarios" : "Payees", href: "/budget/settings#payees", icon: "👤" },
        ],
    },
    {
        title: es ? "Herramientas" : "Tools",
        items: [
            { label: es ? "Escanear ticket" : "Scan Receipt", href: "/budget/scan-receipt", icon: "📸" },
            { label: es ? "Importar CSV" : "Import CSV", href: "/budget/import", icon: "📥" },
            { label: es ? "Recurrentes" : "Recurring", href: "/budget/settings#recurring", icon: "🔄" },
            { label: es ? "Reglas auto" : "Auto Rules", href: "/budget/settings#rules", icon: "🤖" },
        ],
    },
    {
        title: es ? "Sistema" : "System",
        items: [
            { label: es ? "Respaldos" : "Backups", href: "/budget/settings#backups", icon: "💾" },
            { label: es ? "Configuración" : "Settings", href: "/budget/settings", icon: "⚙️" },
        ],
    },
];
---

<!-- Backdrop -->
<div id="drawer-backdrop" class="fixed inset-0 bg-black/50 z-30 hidden transition-opacity duration-300 opacity-0"></div>

<!-- Drawer -->
<div id="drawer-panel" class="fixed top-0 left-0 h-full w-72 bg-white z-40 shadow-xl transform -translate-x-full transition-transform duration-300">
    <div class="p-4 border-b border-slate-200 flex items-center justify-between">
        <h2 class="text-lg font-bold text-slate-800">{es ? "Menú" : "Menu"}</h2>
        <button id="drawer-close" class="p-1 text-slate-400 hover:text-slate-600">
            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
            </svg>
        </button>
    </div>

    <nav class="p-4 overflow-y-auto h-[calc(100%-65px)]">
        {sections.map((section) => (
            <div class="mb-5">
                <div class="text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-2">{section.title}</div>
                {section.items.map((item) => (
                    <a
                        href={item.href}
                        class="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm text-slate-600 hover:bg-slate-100 transition-colors mb-0.5"
                    >
                        <span>{item.icon}</span>
                        <span>{item.label}</span>
                    </a>
                ))}
            </div>
        ))}
    </nav>
</div>

<script>
    function initDrawer() {
        const toggle = document.getElementById("drawer-toggle");
        const close = document.getElementById("drawer-close");
        const backdrop = document.getElementById("drawer-backdrop");
        const panel = document.getElementById("drawer-panel");

        if (!toggle || !close || !backdrop || !panel) return;

        function openDrawer() {
            backdrop.classList.remove("hidden");
            requestAnimationFrame(() => {
                backdrop.classList.remove("opacity-0");
                panel.classList.remove("-translate-x-full");
            });
        }

        function closeDrawer() {
            backdrop.classList.add("opacity-0");
            panel.classList.add("-translate-x-full");
            setTimeout(() => backdrop.classList.add("hidden"), 300);
        }

        toggle.addEventListener("click", openDrawer);
        close.addEventListener("click", closeDrawer);
        backdrop.addEventListener("click", closeDrawer);
    }

    initDrawer();
    document.addEventListener("astro:after-swap", initDrawer);
</script>
```

- [ ] **Step 3: Verify components render**

Create a temporary test by modifying `frontend/src/pages/budget/index.astro` to import and render both components. Open http://localhost:3003/budget/ and verify:
- 3 tabs render with correct labels
- Hamburger button opens drawer with slide animation
- Drawer links are grouped correctly
- Clicking backdrop closes drawer
- Active tab highlights correctly

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/BudgetNavNew.astro frontend/src/components/DrawerMenu.astro
git commit -m "feat(budget): add 3-tab nav and drawer menu components"
```

---

## Task 2: FAB Button + Quick Expense Modal

**Files:**
- Create: `frontend/src/components/FABButton.astro`
- Create: `frontend/src/components/FABModal.astro`
- Modify: `frontend/src/lib/i18n.ts` — add new translation keys

- [ ] **Step 1: Add i18n keys**

Add these keys to the translations object in `frontend/src/lib/i18n.ts`:

```typescript
// Add to the 'es' translations:
fab_register_expense: "Registrar gasto",
fab_amount: "Monto",
fab_manual: "Manual",
fab_photo: "Foto",
fab_scan: "Scan",
fab_payee: "Beneficiario",
fab_category: "Categoría",
fab_account: "Cuenta",
fab_note: "Nota",
fab_note_placeholder: "Nota opcional...",
fab_save: "Guardar gasto",
fab_saved: "¡Registrado!",
fab_in_category: "en",
fab_available: "libre",
fab_another: "+ Otro gasto",
fab_close: "Cerrar",
fab_auto_rule: "regla ✓",

// Add to the 'en' translations:
fab_register_expense: "Register expense",
fab_amount: "Amount",
fab_manual: "Manual",
fab_photo: "Photo",
fab_scan: "Scan",
fab_payee: "Payee",
fab_category: "Category",
fab_account: "Account",
fab_note: "Note",
fab_note_placeholder: "Optional note...",
fab_save: "Save expense",
fab_saved: "Saved!",
fab_in_category: "in",
fab_available: "available",
fab_another: "+ Another",
fab_close: "Close",
fab_auto_rule: "rule ✓",
```

- [ ] **Step 2: Create FABButton.astro**

```astro
---
// No props — this is a fixed-position button
---

<button
    id="fab-button"
    class="fixed bottom-20 right-4 md:bottom-8 md:right-8 z-20 w-14 h-14 bg-primary-600 hover:bg-primary-700 text-white rounded-full shadow-lg hover:shadow-xl transition-all duration-200 flex items-center justify-center active:scale-95"
    aria-label="Register expense"
>
    <svg class="w-7 h-7" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M12 4v16m8-8H4"/>
    </svg>
</button>
```

- [ ] **Step 3: Create FABModal.astro**

```astro
---
import { t } from "@lib/i18n";
import type { Lang } from "@lib/i18n";

interface Props {
    lang: Lang;
    token: string;
    accounts: Array<{ id: string; name: string; type: string }>;
    categories: Array<{ id: string; name: string; group_name: string }>;
}

const { lang, token, accounts, categories } = Astro.props;
const es = lang === "es";
---

<!-- Backdrop -->
<div id="fab-backdrop" class="fixed inset-0 bg-black/50 z-40 hidden transition-opacity duration-300 opacity-0"></div>

<!-- Bottom Sheet -->
<div id="fab-modal" class="fixed bottom-0 left-0 right-0 z-50 transform translate-y-full transition-transform duration-300">
    <div class="max-w-md mx-auto bg-white rounded-t-2xl shadow-2xl max-h-[85vh] overflow-y-auto">
        <!-- Handle bar -->
        <div class="flex justify-center pt-3 pb-1">
            <div class="w-10 h-1 bg-slate-300 rounded-full"></div>
        </div>

        <!-- Step 1: Entry (shown by default) -->
        <div id="fab-step-entry" class="p-5">
            <h3 class="text-lg font-bold text-slate-800 text-center mb-4">{t(lang, "fab_register_expense")}</h3>

            <!-- Amount input -->
            <div class="mb-4">
                <label class="text-xs text-slate-500 mb-1 block">{t(lang, "fab_amount")}</label>
                <input
                    id="fab-amount"
                    type="number"
                    step="0.01"
                    min="0"
                    placeholder="0.00"
                    class="w-full text-3xl font-bold text-center text-slate-800 border-b-2 border-slate-200 focus:border-primary-600 outline-none py-2 bg-transparent"
                    inputmode="decimal"
                />
                <!-- Quick amounts -->
                <div class="flex gap-2 justify-center mt-3">
                    {[50, 100, 200, 500].map((amt) => (
                        <button
                            class="fab-quick-amount px-4 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-600 text-sm rounded-full transition-colors"
                            data-amount={amt}
                        >
                            ${amt}
                        </button>
                    ))}
                </div>
            </div>

            <!-- Mode buttons -->
            <div class="flex gap-2 mb-4">
                <button class="fab-mode flex-1 py-3 rounded-xl bg-primary-50 border-2 border-primary-600 text-primary-600 text-center text-sm font-medium" data-mode="manual">
                    <div class="text-xl mb-0.5">⌨️</div>
                    {t(lang, "fab_manual")}
                </button>
                <a href="/budget/scan-receipt" class="flex-1 py-3 rounded-xl bg-slate-50 border-2 border-slate-200 text-slate-600 text-center text-sm font-medium hover:border-slate-300 transition-colors">
                    <div class="text-xl mb-0.5">📸</div>
                    {t(lang, "fab_photo")}
                </a>
                <a href="/budget/import" class="flex-1 py-3 rounded-xl bg-slate-50 border-2 border-slate-200 text-slate-600 text-center text-sm font-medium hover:border-slate-300 transition-colors">
                    <div class="text-xl mb-0.5">📄</div>
                    {t(lang, "fab_scan")}
                </a>
            </div>

            <!-- Form fields -->
            <div class="space-y-3">
                <div>
                    <label class="text-xs text-slate-500 mb-1 block">{t(lang, "fab_payee")}</label>
                    <input
                        id="fab-payee"
                        type="text"
                        placeholder={es ? "Ej: Walmart, Oxxo..." : "E.g.: Walmart, Target..."}
                        class="w-full px-3 py-2.5 bg-slate-50 border border-slate-200 rounded-lg text-sm focus:border-primary-600 focus:ring-1 focus:ring-primary-600 outline-none"
                        autocomplete="off"
                    />
                    <span id="fab-rule-indicator" class="text-xs text-green-600 mt-0.5 hidden">{t(lang, "fab_auto_rule")}</span>
                </div>

                <div>
                    <label class="text-xs text-slate-500 mb-1 block">{t(lang, "fab_category")}</label>
                    <select id="fab-category" class="w-full px-3 py-2.5 bg-slate-50 border border-slate-200 rounded-lg text-sm focus:border-primary-600 outline-none">
                        <option value="">{es ? "Seleccionar..." : "Select..."}</option>
                        {categories.map((cat) => (
                            <option value={cat.id}>{cat.group_name} → {cat.name}</option>
                        ))}
                    </select>
                </div>

                <div>
                    <label class="text-xs text-slate-500 mb-1 block">{t(lang, "fab_account")}</label>
                    <select id="fab-account" class="w-full px-3 py-2.5 bg-slate-50 border border-slate-200 rounded-lg text-sm focus:border-primary-600 outline-none">
                        {accounts.map((acc) => (
                            <option value={acc.id}>{acc.name}</option>
                        ))}
                    </select>
                </div>

                <div>
                    <label class="text-xs text-slate-500 mb-1 block">{t(lang, "fab_note")}</label>
                    <input
                        id="fab-note"
                        type="text"
                        placeholder={t(lang, "fab_note_placeholder")}
                        class="w-full px-3 py-2.5 bg-slate-50 border border-slate-200 rounded-lg text-sm focus:border-primary-600 outline-none"
                    />
                </div>
            </div>

            <!-- Error message -->
            <div id="fab-error" class="hidden mt-3 p-2 bg-red-50 text-red-600 text-sm rounded-lg"></div>

            <!-- Save button -->
            <button
                id="fab-save"
                class="w-full mt-4 py-3 bg-primary-600 hover:bg-primary-700 text-white font-semibold rounded-xl transition-colors active:scale-[0.98]"
            >
                {t(lang, "fab_save")}
            </button>
        </div>

        <!-- Step 2: Confirmation (hidden by default) -->
        <div id="fab-step-confirm" class="p-5 text-center hidden">
            <div class="text-5xl mb-3">✅</div>
            <div class="text-lg font-bold text-green-600 mb-1">{t(lang, "fab_saved")}</div>
            <div id="fab-confirm-summary" class="text-sm text-slate-500 mb-5"></div>

            <!-- Category impact -->
            <div id="fab-confirm-impact" class="bg-slate-50 rounded-xl p-4 mb-5 text-left hidden">
                <div id="fab-impact-label" class="text-xs text-slate-500 mb-2"></div>
                <div class="flex justify-between text-sm mb-1.5">
                    <span id="fab-impact-spent" class="text-slate-700"></span>
                    <span id="fab-impact-available" class="text-green-600"></span>
                </div>
                <div class="w-full bg-slate-200 rounded-full h-1.5">
                    <div id="fab-impact-bar" class="h-1.5 rounded-full transition-all duration-500"></div>
                </div>
            </div>

            <div class="flex gap-3">
                <button id="fab-another" class="flex-1 py-2.5 bg-slate-100 hover:bg-slate-200 text-slate-700 text-sm font-medium rounded-xl transition-colors">
                    {t(lang, "fab_another")}
                </button>
                <button id="fab-done" class="flex-1 py-2.5 bg-slate-100 hover:bg-slate-200 text-slate-700 text-sm font-medium rounded-xl transition-colors">
                    {t(lang, "fab_close")}
                </button>
            </div>
        </div>
    </div>
</div>

<script define:vars={{ token }}>
    function initFABModal() {
        const fab = document.getElementById("fab-button");
        const backdrop = document.getElementById("fab-backdrop");
        const modal = document.getElementById("fab-modal");
        const stepEntry = document.getElementById("fab-step-entry");
        const stepConfirm = document.getElementById("fab-step-confirm");

        if (!fab || !backdrop || !modal) return;

        function openModal() {
            backdrop.classList.remove("hidden");
            requestAnimationFrame(() => {
                backdrop.classList.remove("opacity-0");
                modal.classList.remove("translate-y-full");
            });
            document.getElementById("fab-amount")?.focus();
        }

        function closeModal() {
            backdrop.classList.add("opacity-0");
            modal.classList.add("translate-y-full");
            setTimeout(() => {
                backdrop.classList.add("hidden");
                resetForm();
            }, 300);
        }

        function resetForm() {
            stepEntry.classList.remove("hidden");
            stepConfirm.classList.add("hidden");
            document.getElementById("fab-amount").value = "";
            document.getElementById("fab-payee").value = "";
            document.getElementById("fab-category").selectedIndex = 0;
            document.getElementById("fab-note").value = "";
            document.getElementById("fab-error").classList.add("hidden");
            document.getElementById("fab-rule-indicator").classList.add("hidden");
        }

        // Open/close
        fab.addEventListener("click", openModal);
        backdrop.addEventListener("click", closeModal);
        document.getElementById("fab-done")?.addEventListener("click", closeModal);

        // Quick amounts
        document.querySelectorAll(".fab-quick-amount").forEach((btn) => {
            btn.addEventListener("click", () => {
                document.getElementById("fab-amount").value = btn.dataset.amount;
            });
        });

        // Another expense
        document.getElementById("fab-another")?.addEventListener("click", () => {
            resetForm();
        });

        // Auto-categorization on payee blur
        const payeeInput = document.getElementById("fab-payee");
        let debounceTimer;
        payeeInput?.addEventListener("input", () => {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(async () => {
                const payee = payeeInput.value.trim();
                if (payee.length < 2) return;
                try {
                    const res = await fetch(`/api/budget/categorization-rules/match?payee=${encodeURIComponent(payee)}`, {
                        headers: { Authorization: `Bearer ${token}` },
                    });
                    if (res.ok) {
                        const data = await res.json();
                        if (data.category_id) {
                            document.getElementById("fab-category").value = data.category_id;
                            document.getElementById("fab-rule-indicator").classList.remove("hidden");
                        }
                    }
                } catch {}
            }, 400);
        });

        // Save
        document.getElementById("fab-save")?.addEventListener("click", async () => {
            const amount = parseFloat(document.getElementById("fab-amount").value);
            const payee = document.getElementById("fab-payee").value.trim();
            const categoryId = document.getElementById("fab-category").value;
            const accountId = document.getElementById("fab-account").value;
            const note = document.getElementById("fab-note").value.trim();
            const errorEl = document.getElementById("fab-error");

            if (!amount || amount <= 0) {
                errorEl.textContent = "Enter an amount";
                errorEl.classList.remove("hidden");
                return;
            }
            if (!categoryId) {
                errorEl.textContent = "Select a category";
                errorEl.classList.remove("hidden");
                return;
            }
            if (!accountId) {
                errorEl.textContent = "Select an account";
                errorEl.classList.remove("hidden");
                return;
            }

            errorEl.classList.add("hidden");
            const saveBtn = document.getElementById("fab-save");
            saveBtn.disabled = true;
            saveBtn.textContent = "...";

            try {
                const today = new Date().toISOString().split("T")[0];
                const res = await fetch("/api/budget/transactions/", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        Authorization: `Bearer ${token}`,
                    },
                    body: JSON.stringify({
                        amount: Math.round(amount * -100), // negative = expense, in cents
                        date: today,
                        payee_name: payee || null,
                        category_id: categoryId,
                        account_id: accountId,
                        notes: note || null,
                    }),
                });

                if (!res.ok) {
                    const err = await res.json();
                    throw new Error(err.detail || "Failed to save");
                }

                const saved = await res.json();

                // Show confirmation
                const catSelect = document.getElementById("fab-category");
                const catLabel = catSelect.options[catSelect.selectedIndex]?.text || "";
                document.getElementById("fab-confirm-summary").textContent = `$${amount.toFixed(2)} ${catLabel}`;

                stepEntry.classList.add("hidden");
                stepConfirm.classList.remove("hidden");
            } catch (err) {
                errorEl.textContent = err.message;
                errorEl.classList.remove("hidden");
            } finally {
                saveBtn.disabled = false;
                saveBtn.textContent = saveBtn.dataset.label || "Save";
            }
        });
    }

    initFABModal();
    document.addEventListener("astro:after-swap", initFABModal);
</script>
```

- [ ] **Step 4: Verify FAB renders and saves**

Open http://localhost:3003/budget/ (after integrating into index.astro in a later task). For now, verify the components are syntactically correct:

```bash
cd frontend && npm run build 2>&1 | head -20
```

Expected: Build succeeds with no errors in the new component files.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/FABButton.astro frontend/src/components/FABModal.astro frontend/src/lib/i18n.ts
git commit -m "feat(budget): add FAB button and quick expense modal"
```

---

## Task 3: CategoryProgressBar + MonthSummaryBar Components

**Files:**
- Create: `frontend/src/components/CategoryProgressBar.astro`
- Create: `frontend/src/components/MonthSummaryBar.astro`

- [ ] **Step 1: Create CategoryProgressBar.astro**

```astro
---
interface Props {
    spent: number;
    budgeted: number;
    formatCurrency: (amount: number) => string;
}

const { spent, budgeted, formatCurrency } = Astro.props;

const percentage = budgeted > 0 ? Math.min((Math.abs(spent) / budgeted) * 100, 100) : 0;
const overBudget = Math.abs(spent) > budgeted && budgeted > 0;

// Green < 75%, Yellow 75-95%, Red > 95%
let barColor = "bg-green-500";
if (overBudget || percentage > 95) barColor = "bg-red-500";
else if (percentage > 75) barColor = "bg-amber-500";
---

<div class="w-full bg-slate-200 rounded-full h-1.5">
    <div
        class:list={["h-1.5 rounded-full transition-all duration-300", barColor]}
        style={`width: ${percentage}%`}
    ></div>
</div>
```

- [ ] **Step 2: Create MonthSummaryBar.astro**

```astro
---
import type { Lang } from "@lib/i18n";

interface Props {
    income: number;
    spent: number;
    budgeted: number;
    lang: Lang;
    formatCurrency: (amount: number) => string;
}

const { income, spent, budgeted, lang, formatCurrency } = Astro.props;
const es = lang === "es";
const available = income - Math.abs(spent);
const usagePercent = income > 0 ? Math.min((Math.abs(spent) / income) * 100, 100) : 0;

let barColor = "bg-green-500";
if (usagePercent > 95) barColor = "bg-red-500";
else if (usagePercent > 75) barColor = "bg-amber-500";
---

<div class="bg-white rounded-xl shadow-sm p-4 mx-4 mt-3">
    <div class="flex justify-between text-center mb-3">
        <div>
            <div class="text-[10px] text-slate-400 uppercase">{es ? "Ingresos" : "Income"}</div>
            <div class="text-sm font-bold text-green-600">{formatCurrency(income)}</div>
        </div>
        <div>
            <div class="text-[10px] text-slate-400 uppercase">{es ? "Gastado" : "Spent"}</div>
            <div class="text-sm font-bold text-red-500">{formatCurrency(Math.abs(spent))}</div>
        </div>
        <div>
            <div class="text-[10px] text-slate-400 uppercase">{es ? "Disponible" : "Available"}</div>
            <div class:list={["text-sm font-bold", available >= 0 ? "text-green-600" : "text-red-500"]}>
                {formatCurrency(available)}
            </div>
        </div>
    </div>
    <div class="w-full bg-slate-200 rounded-full h-2">
        <div
            class:list={["h-2 rounded-full transition-all duration-500", barColor]}
            style={`width: ${usagePercent}%`}
        ></div>
    </div>
    <div class="text-[10px] text-slate-400 text-right mt-1">
        {Math.round(usagePercent)}% {es ? "del presupuesto usado" : "of budget used"}
    </div>
</div>
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/CategoryProgressBar.astro frontend/src/components/MonthSummaryBar.astro
git commit -m "feat(budget): add CategoryProgressBar and MonthSummaryBar components"
```

---

## Task 4: Rewrite Hub Page (`/budget/index.astro`)

**Files:**
- Modify: `frontend/src/pages/budget/index.astro` — full rewrite as Hub + Month View

This is the core page. It replaces `index.astro` (hub cards), `month/[year]/[month].astro`, and `categories/index.astro`.

- [ ] **Step 1: Read existing month page for data fetching patterns**

Read `frontend/src/pages/budget/month/[year]/[month].astro` to understand the API calls and data structures used. Note the exact fetch calls for month budget data, category groups, and goals.

- [ ] **Step 2: Read existing index.astro**

Read `frontend/src/pages/budget/index.astro` to understand the current layout and imports.

- [ ] **Step 3: Rewrite index.astro**

Rewrite `frontend/src/pages/budget/index.astro` with the new Hub + Month View layout. The page should:

1. **Auth & data fetching (frontmatter):**
   - Same auth pattern as current pages (token, user check, role check)
   - Fetch current month budget: `GET /api/budget/month/{year}/{month}`
   - Fetch category groups: `GET /api/budget/categories/groups`
   - Fetch accounts: `GET /api/budget/accounts/`
   - Fetch goals: `GET /api/budget/goals/`
   - Calculate `readyToAssign` from month data

2. **Layout:**
   - `Layout` wrapper with title
   - `BudgetNavNew` with `active="month"`
   - `DrawerMenu`
   - `BudgetMonthNav` (existing component for prev/next month arrows + ready to assign)
   - `MonthSummaryBar` (new — income/spent/available)
   - For each category group: render `BudgetCategoryGroup` (existing component — reuse as-is)
   - `AssignFundsModal` (existing)
   - `FABButton` + `FABModal`
   - `BottomNav`

The key change is replacing `BudgetNav` (old 6-tab) with `BudgetNavNew` (new 3-tab) + `DrawerMenu`, and adding the `MonthSummaryBar` + FAB.

```astro
---
import Layout from "@layouts/Layout.astro";
import BottomNav from "@components/BottomNav.astro";
import BudgetNavNew from "@components/BudgetNavNew.astro";
import DrawerMenu from "@components/DrawerMenu.astro";
import BudgetMonthNav from "@components/BudgetMonthNav.astro";
import MonthSummaryBar from "@components/MonthSummaryBar.astro";
import BudgetCategoryGroup from "@components/BudgetCategoryGroup.astro";
import AssignFundsModal from "@components/AssignFundsModal.astro";
import FABButton from "@components/FABButton.astro";
import FABModal from "@components/FABModal.astro";
import { apiFetch } from "@lib/api";
import { getMonthBudget, getCategoryGroups, formatCurrency } from "@lib/api/budget";
import { t } from "@lib/i18n";

// Auth
const token = Astro.cookies.get("access_token")?.value;
if (!token) return Astro.redirect("/login");
const lang = (Astro.cookies.get("lang")?.value ?? "en") as "en" | "es";

const { data: user, ok: userOk } = await apiFetch<any>("/api/auth/me", { token });
if (!userOk) { Astro.cookies.delete("access_token"); return Astro.redirect("/login"); }
if (user.role !== "parent") return Astro.redirect("/dashboard");

// Current month
const now = new Date();
const yearParam = Astro.url.searchParams.get("year");
const monthParam = Astro.url.searchParams.get("month");
const year = yearParam ? parseInt(yearParam) : now.getFullYear();
const month = monthParam ? parseInt(monthParam) : now.getMonth() + 1;

// Fetch data
const [monthRes, groupsRes, accountsRes, goalsRes] = await Promise.all([
    getMonthBudget(token, year, month),
    getCategoryGroups(token),
    apiFetch<any[]>("/api/budget/accounts/", { token }),
    apiFetch<any[]>("/api/budget/goals/", { token }),
]);

const monthData = monthRes.data;
const groups = groupsRes.data || [];
const accounts = accountsRes.data || [];
const goals = goalsRes.data || [];

// Calculate totals
const income = monthData?.total_income || 0;
const spent = monthData?.total_activity || 0;
const budgeted = monthData?.total_budgeted || 0;
const readyToAssign = monthData?.ready_to_assign || 0;

// Build goals map
const goalsByCategory: Record<string, any> = {};
goals.forEach((g: any) => { goalsByCategory[g.category_id] = g; });

// Build flat category list for FAB modal
const allCategories = groups
    .filter((g: any) => !g.is_income)
    .flatMap((g: any) => (g.categories || []).map((c: any) => ({
        id: c.id, name: c.name, group_name: g.name,
    })));

// Category groups with activity from month data
const expenseGroups = (monthData?.category_groups || groups).filter((g: any) => !g.is_income);
const incomeGroups = (monthData?.category_groups || groups).filter((g: any) => g.is_income);

const allExpenseCategories = expenseGroups.flatMap((g: any) => g.categories || []);
---

<Layout title={lang === "es" ? "Presupuesto" : "Budget"}>
    <div class="w-full max-w-md md:max-w-4xl lg:max-w-6xl mx-auto bg-slate-50 min-h-screen flex flex-col pb-20">
        <BudgetNavNew active="month" lang={lang} />
        <DrawerMenu lang={lang} />

        <BudgetMonthNav
            year={year}
            month={month}
            readyToAssign={readyToAssign}
            lang={lang}
            t={t}
            formatCurrency={formatCurrency}
            baseRoute="/budget"
        />

        <MonthSummaryBar
            income={income}
            spent={spent}
            budgeted={budgeted}
            lang={lang}
            formatCurrency={formatCurrency}
        />

        <!-- Category Groups -->
        <div class="px-4 py-3 space-y-3">
            {incomeGroups.map((group: any) => (
                <BudgetCategoryGroup
                    group={group}
                    isIncome={true}
                    lang={lang}
                    t={t}
                    formatCurrency={formatCurrency}
                    token={token}
                    goalsByCategory={goalsByCategory}
                />
            ))}
            {expenseGroups.map((group: any) => (
                <BudgetCategoryGroup
                    group={group}
                    isIncome={false}
                    lang={lang}
                    t={t}
                    formatCurrency={formatCurrency}
                    token={token}
                    allExpenseCategories={allExpenseCategories}
                    goalsByCategory={goalsByCategory}
                />
            ))}
        </div>

        <BottomNav active="budget" role={user.role} lang={lang} />
    </div>

    <FABButton />
    <FABModal lang={lang} token={token} accounts={accounts} categories={allCategories} />
    <AssignFundsModal
        readyToAssign={readyToAssign}
        categories={allExpenseCategories}
        lang={lang}
        t={t}
        formatCurrency={formatCurrency}
    />
</Layout>
```

Note: The month navigation uses query params (`?year=2026&month=3`) instead of path params (`/month/2026/3`). The `BudgetMonthNav` component's prev/next links will need a small adjustment to generate `?year=X&month=Y` links instead of `/budget/month/X/Y`. This is handled in Step 4.

- [ ] **Step 4: Adjust BudgetMonthNav links for query param routing**

Edit `frontend/src/components/BudgetMonthNav.astro` to update the prev/next month links. Find the `<a>` tags for previous and next month, and change them from:

```
href=`/budget/month/${prevYear}/${prevMonth}`
```
to:
```
href=`/budget/?year=${prevYear}&month=${prevMonth}`
```

Do the same for the next month link. Also update the "current month" link from `/budget/month/${currentYear}/${currentMonth}` to `/budget/`.

- [ ] **Step 5: Verify the hub page renders**

Open http://localhost:3003/budget/ and verify:
- 3-tab nav appears at top with "Mes" active
- Hamburger opens the drawer
- Month summary shows income/spent/available
- Category groups render with progress bars
- FAB button visible in bottom-right
- Clicking FAB opens the expense modal
- Month navigation arrows work (change ?year/&month params)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/budget/index.astro frontend/src/components/BudgetMonthNav.astro
git commit -m "feat(budget): rewrite hub page with month view, FAB, and new nav"
```

---

## Task 5: Enhance Transactions Page with Filters

**Files:**
- Modify: `frontend/src/pages/budget/transactions.astro` — add filter bar and account selector

- [ ] **Step 1: Read the current transactions page**

Read `frontend/src/pages/budget/transactions.astro` to understand the current structure.

- [ ] **Step 2: Add filter bar and update nav**

Modify `frontend/src/pages/budget/transactions.astro`:

1. Replace `BudgetNav` import with `BudgetNavNew` + `DrawerMenu`
2. Add a filter bar at the top with:
   - Account dropdown (fetched from `/api/budget/accounts/`)
   - Category dropdown (fetched from `/api/budget/categories/groups`)
   - Date range (month selector or from/to)
   - Search input for payee/note
3. Pass filter values as query params to the API call
4. Add FABButton + FABModal at the bottom
5. Add a "Reconcile" button that appears when an account is selected in the filter

Key changes to the frontmatter:

```astro
// Add imports
import BudgetNavNew from "@components/BudgetNavNew.astro";
import DrawerMenu from "@components/DrawerMenu.astro";
import FABButton from "@components/FABButton.astro";
import FABModal from "@components/FABModal.astro";

// Read filter params
const accountFilter = Astro.url.searchParams.get("account") || "";
const categoryFilter = Astro.url.searchParams.get("category") || "";
const searchFilter = Astro.url.searchParams.get("search") || "";

// Fetch accounts and categories for filter dropdowns
const accountsRes = await apiFetch<any[]>("/api/budget/accounts/", { token });
const accounts = accountsRes.data || [];
const groupsRes = await getCategoryGroups(token);
const groups = groupsRes.data || [];

// Build API query with filters
let txUrl = `/api/budget/transactions/?limit=100`;
if (accountFilter) txUrl += `&account_id=${accountFilter}`;
if (categoryFilter) txUrl += `&category_id=${categoryFilter}`;
if (searchFilter) txUrl += `&search=${encodeURIComponent(searchFilter)}`;
```

Add the filter bar HTML between `BudgetNavNew` and the transaction list:

```html
<!-- Filter Bar -->
<div class="px-4 py-3 bg-white border-b border-slate-200 flex flex-wrap gap-2">
    <select id="filter-account" class="text-sm border border-slate-200 rounded-lg px-2 py-1.5 bg-slate-50">
        <option value="">{es ? "Todas las cuentas" : "All accounts"}</option>
        {accounts.map((acc) => (
            <option value={acc.id} selected={acc.id === accountFilter}>{acc.name}</option>
        ))}
    </select>
    <select id="filter-category" class="text-sm border border-slate-200 rounded-lg px-2 py-1.5 bg-slate-50">
        <option value="">{es ? "Todas las categorías" : "All categories"}</option>
        {groups.flatMap((g) => g.categories || []).map((cat) => (
            <option value={cat.id} selected={cat.id === categoryFilter}>{cat.name}</option>
        ))}
    </select>
    <input
        id="filter-search"
        type="text"
        placeholder={es ? "Buscar..." : "Search..."}
        value={searchFilter}
        class="text-sm border border-slate-200 rounded-lg px-2 py-1.5 bg-slate-50 flex-1 min-w-[120px]"
    />
</div>
```

Add client-side script for filter navigation:

```html
<script>
    function initFilters() {
        const account = document.getElementById("filter-account");
        const category = document.getElementById("filter-category");
        const search = document.getElementById("filter-search");

        function applyFilters() {
            const params = new URLSearchParams();
            if (account?.value) params.set("account", account.value);
            if (category?.value) params.set("category", category.value);
            if (search?.value) params.set("search", search.value);
            const qs = params.toString();
            window.location.href = "/budget/transactions" + (qs ? "?" + qs : "");
        }

        account?.addEventListener("change", applyFilters);
        category?.addEventListener("change", applyFilters);
        let searchTimer;
        search?.addEventListener("input", () => {
            clearTimeout(searchTimer);
            searchTimer = setTimeout(applyFilters, 500);
        });
    }

    initFilters();
    document.addEventListener("astro:after-swap", initFilters);
</script>
```

- [ ] **Step 3: Verify filters work**

Open http://localhost:3003/budget/transactions and verify:
- Filter dropdowns appear at the top
- Selecting an account filters the list
- Selecting a category filters the list
- Typing in search filters by payee/note
- FAB button + modal work
- New nav shows "Movimientos" tab as active

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/budget/transactions.astro
git commit -m "feat(budget): add filter bar and new nav to transactions page"
```

---

## Task 6: Unified Reports Page

**Files:**
- Create: `frontend/src/components/ReportSubTabs.astro`
- Create: `frontend/src/components/PeriodSelector.astro`
- Create: `frontend/src/pages/budget/reports.astro`

- [ ] **Step 1: Read existing report pages for data fetching patterns**

Read `frontend/src/pages/budget/reports/spending.astro` and `frontend/src/pages/budget/reports/income-vs-expense.astro` to understand the API calls, data structures, and chart rendering patterns used.

- [ ] **Step 2: Create ReportSubTabs.astro**

```astro
---
interface Props {
    active: "spending" | "cashflow" | "networth" | "analysis";
    lang: "en" | "es";
}

const { active, lang } = Astro.props;
const es = lang === "es";

const tabs = [
    { id: "spending", label: es ? "Gastos" : "Spending" },
    { id: "cashflow", label: es ? "Flujo" : "Cashflow" },
    { id: "networth", label: es ? "Patrimonio" : "Net Worth" },
    { id: "analysis", label: es ? "vs Presupuesto" : "vs Budget" },
];
---

<div class="flex gap-1.5 px-4 py-2 overflow-x-auto" id="report-sub-tabs">
    {tabs.map((tab) => (
        <button
            class:list={[
                "report-tab px-4 py-1.5 rounded-full text-sm font-medium whitespace-nowrap transition-colors",
                active === tab.id
                    ? "bg-primary-600 text-white"
                    : "bg-slate-100 text-slate-500 hover:bg-slate-200",
            ]}
            data-tab={tab.id}
        >
            {tab.label}
        </button>
    ))}
</div>
```

- [ ] **Step 3: Create PeriodSelector.astro**

```astro
---
interface Props {
    activePeriod: "1m" | "3m" | "6m" | "1y";
}

const { activePeriod } = Astro.props;

const periods = [
    { id: "1m", label: "1M" },
    { id: "3m", label: "3M" },
    { id: "6m", label: "6M" },
    { id: "1y", label: "1A" },
];
---

<div class="flex items-center justify-between px-4 py-2 border-b border-slate-200">
    <button id="period-prev" class="p-1 text-slate-400 hover:text-slate-600">
        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"/>
        </svg>
    </button>
    <div class="flex gap-1" id="period-buttons">
        {periods.map((p) => (
            <button
                class:list={[
                    "period-btn px-3 py-1 rounded text-xs font-medium transition-colors",
                    activePeriod === p.id
                        ? "bg-primary-600 text-white"
                        : "bg-slate-100 text-slate-500 hover:bg-slate-200",
                ]}
                data-period={p.id}
            >
                {p.label}
            </button>
        ))}
    </div>
    <button id="period-next" class="p-1 text-slate-400 hover:text-slate-600">
        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/>
        </svg>
    </button>
</div>
```

- [ ] **Step 4: Create reports.astro**

Create `frontend/src/pages/budget/reports.astro`. This page renders all 4 report types with client-side tab switching. Each report section is a `<div>` that gets shown/hidden.

```astro
---
import Layout from "@layouts/Layout.astro";
import BottomNav from "@components/BottomNav.astro";
import BudgetNavNew from "@components/BudgetNavNew.astro";
import DrawerMenu from "@components/DrawerMenu.astro";
import ReportSubTabs from "@components/ReportSubTabs.astro";
import PeriodSelector from "@components/PeriodSelector.astro";
import FABButton from "@components/FABButton.astro";
import FABModal from "@components/FABModal.astro";
import { apiFetch } from "@lib/api";
import { getCategoryGroups, formatCurrency } from "@lib/api/budget";
import { t } from "@lib/i18n";

// Auth
const token = Astro.cookies.get("access_token")?.value;
if (!token) return Astro.redirect("/login");
const lang = (Astro.cookies.get("lang")?.value ?? "en") as "en" | "es";
const es = lang === "es";

const { data: user, ok: userOk } = await apiFetch<any>("/api/auth/me", { token });
if (!userOk) { Astro.cookies.delete("access_token"); return Astro.redirect("/login"); }
if (user.role !== "parent") return Astro.redirect("/dashboard");

// Default: current month, spending tab, 3m period
const activeTab = (Astro.url.searchParams.get("tab") || "spending") as "spending" | "cashflow" | "networth" | "analysis";
const period = (Astro.url.searchParams.get("period") || "3m") as "1m" | "3m" | "6m" | "1y";

// Calculate date range from period
const now = new Date();
const endDate = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
const monthsBack = period === "1m" ? 1 : period === "3m" ? 3 : period === "6m" ? 6 : 12;
const startD = new Date(now.getFullYear(), now.getMonth() - monthsBack + 1, 1);
const startDate = `${startD.getFullYear()}-${String(startD.getMonth() + 1).padStart(2, "0")}-01`;

// Fetch report data based on active tab
const reportUrl = `/api/budget/reports?start_date=${startDate}&end_date=${endDate}`;
const { data: reportData } = await apiFetch<any>(reportUrl, { token });

// Fetch accounts + categories for FAB
const [accountsRes, groupsRes] = await Promise.all([
    apiFetch<any[]>("/api/budget/accounts/", { token }),
    getCategoryGroups(token),
]);
const accounts = accountsRes.data || [];
const groups = groupsRes.data || [];
const allCategories = groups
    .filter((g: any) => !g.is_income)
    .flatMap((g: any) => (g.categories || []).map((c: any) => ({
        id: c.id, name: c.name, group_name: g.name,
    })));

// Extract report sections
const spendingByCategory = reportData?.spending_by_category || [];
const totalSpending = spendingByCategory.reduce((sum: number, c: any) => sum + Math.abs(c.total), 0);
const incomeVsExpense = reportData?.income_vs_expense || [];
const netWorth = reportData?.net_worth || {};
const budgetAnalysis = reportData?.budget_vs_actual || [];
---

<Layout title={es ? "Reportes" : "Reports"}>
    <div class="w-full max-w-md md:max-w-4xl lg:max-w-6xl mx-auto bg-slate-50 min-h-screen flex flex-col pb-20">
        <BudgetNavNew active="reports" lang={lang} />
        <DrawerMenu lang={lang} />

        <ReportSubTabs active={activeTab} lang={lang} />
        <PeriodSelector activePeriod={period} />

        <!-- Spending Report -->
        <div id="report-spending" class:list={["px-4 py-4", activeTab !== "spending" && "hidden"]}>
            {spendingByCategory.length > 0 ? (
                <div class="bg-white rounded-xl shadow-sm p-4">
                    <div class="text-center mb-4">
                        <div class="text-2xl font-bold text-slate-800">{formatCurrency(totalSpending)}</div>
                        <div class="text-xs text-slate-400">{es ? "total gastado" : "total spent"}</div>
                    </div>
                    <div class="space-y-3">
                        {spendingByCategory.map((cat: any) => {
                            const pct = totalSpending > 0 ? (Math.abs(cat.total) / totalSpending * 100) : 0;
                            return (
                                <div>
                                    <div class="flex justify-between text-sm mb-1">
                                        <span class="text-slate-700">{cat.name}</span>
                                        <span class="text-slate-500">{formatCurrency(Math.abs(cat.total))} ({Math.round(pct)}%)</span>
                                    </div>
                                    <div class="w-full bg-slate-200 rounded-full h-2">
                                        <div class="h-2 rounded-full bg-primary-500" style={`width: ${pct}%`}></div>
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </div>
            ) : (
                <div class="text-center text-slate-400 py-12">{es ? "Sin datos para este período" : "No data for this period"}</div>
            )}
        </div>

        <!-- Cashflow Report -->
        <div id="report-cashflow" class:list={["px-4 py-4", activeTab !== "cashflow" && "hidden"]}>
            {incomeVsExpense.length > 0 ? (
                <div class="bg-white rounded-xl shadow-sm p-4">
                    <div class="space-y-4">
                        {incomeVsExpense.map((m: any) => (
                            <div>
                                <div class="text-xs text-slate-400 mb-2">{m.month}</div>
                                <div class="flex gap-2">
                                    <div class="flex-1">
                                        <div class="text-xs text-green-600 mb-0.5">{es ? "Ingreso" : "Income"}</div>
                                        <div class="bg-green-100 rounded h-4" style={`width: 100%`}>
                                            <div class="text-[10px] text-green-700 px-1 leading-4">{formatCurrency(m.income)}</div>
                                        </div>
                                    </div>
                                    <div class="flex-1">
                                        <div class="text-xs text-red-500 mb-0.5">{es ? "Gasto" : "Expense"}</div>
                                        <div class="bg-red-100 rounded h-4" style={`width: ${m.income > 0 ? (Math.abs(m.expense) / m.income * 100) : 100}%`}>
                                            <div class="text-[10px] text-red-700 px-1 leading-4">{formatCurrency(Math.abs(m.expense))}</div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            ) : (
                <div class="text-center text-slate-400 py-12">{es ? "Sin datos para este período" : "No data for this period"}</div>
            )}
        </div>

        <!-- Net Worth Report -->
        <div id="report-networth" class:list={["px-4 py-4", activeTab !== "networth" && "hidden"]}>
            <div class="bg-white rounded-xl shadow-sm p-4 text-center">
                <div class="text-xs text-slate-400 mb-1">{es ? "Patrimonio neto" : "Net Worth"}</div>
                <div class:list={["text-3xl font-bold", (netWorth.total || 0) >= 0 ? "text-green-600" : "text-red-500"]}>
                    {formatCurrency(netWorth.total || 0)}
                </div>
                {netWorth.accounts && (
                    <div class="mt-4 space-y-2 text-left">
                        {netWorth.accounts.map((acc: any) => (
                            <div class="flex justify-between text-sm">
                                <span class="text-slate-600">{acc.name}</span>
                                <span class:list={[acc.balance >= 0 ? "text-green-600" : "text-red-500"]}>
                                    {formatCurrency(acc.balance)}
                                </span>
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </div>

        <!-- Budget Analysis Report -->
        <div id="report-analysis" class:list={["px-4 py-4", activeTab !== "analysis" && "hidden"]}>
            {budgetAnalysis.length > 0 ? (
                <div class="bg-white rounded-xl shadow-sm p-4 space-y-3">
                    {budgetAnalysis.map((cat: any) => {
                        const pct = cat.budgeted > 0 ? (Math.abs(cat.actual) / cat.budgeted * 100) : 0;
                        const over = pct > 100;
                        return (
                            <div>
                                <div class="flex justify-between text-sm mb-1">
                                    <span class="text-slate-700">{cat.name}</span>
                                    <span class:list={[over ? "text-red-500" : "text-green-600"]}>
                                        {formatCurrency(Math.abs(cat.actual))} / {formatCurrency(cat.budgeted)}
                                    </span>
                                </div>
                                <div class="w-full bg-slate-200 rounded-full h-2">
                                    <div
                                        class:list={["h-2 rounded-full", over ? "bg-red-500" : "bg-green-500"]}
                                        style={`width: ${Math.min(pct, 100)}%`}
                                    ></div>
                                </div>
                            </div>
                        );
                    })}
                </div>
            ) : (
                <div class="text-center text-slate-400 py-12">{es ? "Sin datos para este período" : "No data for this period"}</div>
            )}
        </div>

        <BottomNav active="budget" role={user.role} lang={lang} />
    </div>

    <FABButton />
    <FABModal lang={lang} token={token} accounts={accounts} categories={allCategories} />
</Layout>

<script>
    function initReportTabs() {
        const tabs = document.querySelectorAll(".report-tab");
        const sections = {
            spending: document.getElementById("report-spending"),
            cashflow: document.getElementById("report-cashflow"),
            networth: document.getElementById("report-networth"),
            analysis: document.getElementById("report-analysis"),
        };

        tabs.forEach((tab) => {
            tab.addEventListener("click", () => {
                const id = tab.dataset.tab;

                // Update URL without reload
                const url = new URL(window.location.href);
                url.searchParams.set("tab", id);
                history.replaceState(null, "", url.toString());

                // Toggle tabs
                tabs.forEach((t) => {
                    t.classList.toggle("bg-primary-600", t.dataset.tab === id);
                    t.classList.toggle("text-white", t.dataset.tab === id);
                    t.classList.toggle("bg-slate-100", t.dataset.tab !== id);
                    t.classList.toggle("text-slate-500", t.dataset.tab !== id);
                });

                // Toggle sections
                Object.entries(sections).forEach(([key, el]) => {
                    if (el) el.classList.toggle("hidden", key !== id);
                });
            });
        });

        // Period buttons
        const periodBtns = document.querySelectorAll(".period-btn");
        periodBtns.forEach((btn) => {
            btn.addEventListener("click", () => {
                const url = new URL(window.location.href);
                url.searchParams.set("period", btn.dataset.period);
                window.location.href = url.toString();
            });
        });
    }

    initReportTabs();
    document.addEventListener("astro:after-swap", initReportTabs);
</script>
```

- [ ] **Step 5: Verify reports page**

Open http://localhost:3003/budget/reports and verify:
- 4 pill sub-tabs render, "Gastos" active by default
- Clicking sub-tabs switches content without page reload
- Period selector buttons trigger page reload with new data
- "Reportes" tab is highlighted in the nav
- FAB works

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ReportSubTabs.astro frontend/src/components/PeriodSelector.astro frontend/src/pages/budget/reports.astro
git commit -m "feat(budget): add unified reports page with sub-tabs and period selector"
```

---

## Task 7: Unified Settings Page

**Files:**
- Create: `frontend/src/components/SettingsAccordion.astro`
- Modify: `frontend/src/pages/budget/settings.astro` — rewrite as single accordion page

- [ ] **Step 1: Read existing settings sub-pages**

Read these files to understand their content and API calls:
- `frontend/src/pages/budget/settings.astro`
- `frontend/src/pages/budget/settings/payees.astro`
- `frontend/src/pages/budget/settings/rules.astro`
- `frontend/src/pages/budget/settings/recurring.astro`
- `frontend/src/pages/budget/settings/backups.astro`

- [ ] **Step 2: Create SettingsAccordion.astro**

```astro
---
interface Props {
    id: string;
    title: string;
    icon: string;
    defaultOpen?: boolean;
}

const { id, title, icon, defaultOpen = false } = Astro.props;
---

<div class="bg-white rounded-xl shadow-sm overflow-hidden mb-3" id={`accordion-${id}`}>
    <button
        class="accordion-toggle w-full flex items-center justify-between p-4 text-left hover:bg-slate-50 transition-colors"
        data-target={`accordion-content-${id}`}
    >
        <div class="flex items-center gap-3">
            <span class="text-lg">{icon}</span>
            <span class="font-semibold text-slate-800">{title}</span>
        </div>
        <svg class:list={["accordion-chevron w-5 h-5 text-slate-400 transition-transform duration-200", defaultOpen && "rotate-180"]} fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
        </svg>
    </button>
    <div
        id={`accordion-content-${id}`}
        class:list={["accordion-content border-t border-slate-100 px-4 py-4", !defaultOpen && "hidden"]}
    >
        <slot />
    </div>
</div>

<script>
    function initAccordions() {
        document.querySelectorAll(".accordion-toggle").forEach((btn) => {
            btn.addEventListener("click", () => {
                const target = document.getElementById(btn.dataset.target);
                const chevron = btn.querySelector(".accordion-chevron");
                if (target) {
                    target.classList.toggle("hidden");
                    chevron?.classList.toggle("rotate-180");
                }
            });
        });

        // Auto-open section from hash
        const hash = window.location.hash?.replace("#", "");
        if (hash) {
            const target = document.getElementById(`accordion-content-${hash}`);
            if (target && target.classList.contains("hidden")) {
                target.classList.remove("hidden");
                const btn = document.querySelector(`[data-target="accordion-content-${hash}"]`);
                btn?.querySelector(".accordion-chevron")?.classList.add("rotate-180");
                target.scrollIntoView({ behavior: "smooth", block: "start" });
            }
        }
    }

    initAccordions();
    document.addEventListener("astro:after-swap", initAccordions);
</script>
```

- [ ] **Step 3: Rewrite settings.astro**

Rewrite `frontend/src/pages/budget/settings.astro` to consolidate all 5 settings sub-pages into one page with accordion sections. Pull the content (HTML + scripts) from each sub-page into its corresponding accordion section.

The page structure:

```astro
---
import Layout from "@layouts/Layout.astro";
import BottomNav from "@components/BottomNav.astro";
import BudgetNavNew from "@components/BudgetNavNew.astro";
import DrawerMenu from "@components/DrawerMenu.astro";
import BudgetHeader from "@components/BudgetHeader.astro";
import SettingsAccordion from "@components/SettingsAccordion.astro";
import { apiFetch } from "@lib/api";
import { formatCurrency } from "@lib/api/budget";
import { t } from "@lib/i18n";

// Auth (same pattern)
const token = Astro.cookies.get("access_token")?.value;
if (!token) return Astro.redirect("/login");
const lang = (Astro.cookies.get("lang")?.value ?? "en") as "en" | "es";
const es = lang === "es";

const { data: user, ok: userOk } = await apiFetch<any>("/api/auth/me", { token });
if (!userOk) { Astro.cookies.delete("access_token"); return Astro.redirect("/login"); }
if (user.role !== "parent") return Astro.redirect("/dashboard");

// Fetch all settings data in parallel
const [accountsRes, payeesRes, rulesRes, recurringRes] = await Promise.all([
    apiFetch<any[]>("/api/budget/accounts/", { token }),
    apiFetch<any[]>("/api/budget/payees/", { token }),
    apiFetch<any[]>("/api/budget/categorization-rules/", { token }),
    apiFetch<any[]>("/api/budget/recurring-transactions/", { token }),
]);

const accounts = accountsRes.data || [];
const payees = payeesRes.data || [];
const rules = rulesRes.data || [];
const recurring = recurringRes.data || [];
---

<Layout title={es ? "Configuración" : "Settings"}>
    <div class="w-full max-w-md md:max-w-4xl lg:max-w-6xl mx-auto bg-slate-50 min-h-screen flex flex-col pb-20">
        <BudgetNavNew active="month" lang={lang} />
        <DrawerMenu lang={lang} />
        <BudgetHeader title={es ? "Configuración" : "Settings"} lang={lang} />

        <div class="px-4 py-4">
            <!-- Accounts -->
            <SettingsAccordion id="accounts" title={es ? "Cuentas" : "Accounts"} icon="🏦">
                <!-- Port content from accounts/index.astro + accounts/new.astro -->
                <!-- Account list with add/edit capability -->
                {accounts.length > 0 ? (
                    <div class="space-y-2">
                        {accounts.map((acc: any) => (
                            <div class="flex items-center justify-between p-3 bg-slate-50 rounded-lg">
                                <div>
                                    <div class="font-medium text-sm text-slate-800">{acc.name}</div>
                                    <div class="text-xs text-slate-400">{acc.type}</div>
                                </div>
                                <div class="text-sm font-medium text-slate-700">{formatCurrency(acc.balance)}</div>
                            </div>
                        ))}
                    </div>
                ) : (
                    <p class="text-sm text-slate-400">{es ? "No hay cuentas" : "No accounts"}</p>
                )}
                <a href="/budget/accounts/new" class="inline-block mt-3 text-sm text-primary-600 hover:text-primary-700 font-medium">
                    + {es ? "Agregar cuenta" : "Add account"}
                </a>
            </SettingsAccordion>

            <!-- Payees -->
            <SettingsAccordion id="payees" title={es ? "Beneficiarios" : "Payees"} icon="👤">
                {payees.length > 0 ? (
                    <div class="space-y-1">
                        {payees.map((p: any) => (
                            <div class="flex items-center justify-between py-2 px-3 hover:bg-slate-50 rounded-lg text-sm">
                                <span class="text-slate-700">{p.name}</span>
                                {p.is_favorite && <span class="text-xs text-amber-500">★</span>}
                            </div>
                        ))}
                    </div>
                ) : (
                    <p class="text-sm text-slate-400">{es ? "No hay beneficiarios" : "No payees"}</p>
                )}
            </SettingsAccordion>

            <!-- Categorization Rules -->
            <SettingsAccordion id="rules" title={es ? "Reglas de categorización" : "Categorization Rules"} icon="🤖">
                {rules.length > 0 ? (
                    <div class="space-y-2">
                        {rules.map((r: any) => (
                            <div class="flex items-center justify-between p-3 bg-slate-50 rounded-lg text-sm">
                                <div>
                                    <span class="text-slate-800">"{r.match_value}"</span>
                                    <span class="text-slate-400 mx-2">→</span>
                                    <span class="text-primary-600">{r.category_name || r.category_id}</span>
                                </div>
                                <span class="text-xs text-slate-400">{r.match_type}</span>
                            </div>
                        ))}
                    </div>
                ) : (
                    <p class="text-sm text-slate-400">{es ? "No hay reglas" : "No rules"}</p>
                )}
            </SettingsAccordion>

            <!-- Recurring Transactions -->
            <SettingsAccordion id="recurring" title={es ? "Transacciones recurrentes" : "Recurring Transactions"} icon="🔄">
                {recurring.length > 0 ? (
                    <div class="space-y-2">
                        {recurring.map((r: any) => (
                            <div class="flex items-center justify-between p-3 bg-slate-50 rounded-lg text-sm">
                                <div>
                                    <div class="font-medium text-slate-800">{r.title || r.payee_name}</div>
                                    <div class="text-xs text-slate-400">{r.frequency} — {es ? "próximo" : "next"}: {r.next_date}</div>
                                </div>
                                <div class="font-medium text-slate-700">{formatCurrency(Math.abs(r.amount))}</div>
                            </div>
                        ))}
                    </div>
                ) : (
                    <p class="text-sm text-slate-400">{es ? "No hay recurrentes" : "No recurring transactions"}</p>
                )}
            </SettingsAccordion>

            <!-- Backups -->
            <SettingsAccordion id="backups" title={es ? "Respaldos" : "Backups"} icon="💾">
                <div class="space-y-3">
                    <a
                        href="/api/budget/export"
                        class="inline-flex items-center gap-2 px-4 py-2 bg-primary-600 text-white text-sm font-medium rounded-lg hover:bg-primary-700 transition-colors"
                    >
                        📥 {es ? "Exportar datos" : "Export data"}
                    </a>
                    <p class="text-xs text-slate-400">{es ? "Descarga un respaldo completo de tus datos de presupuesto." : "Download a complete backup of your budget data."}</p>
                </div>
            </SettingsAccordion>
        </div>

        <BottomNav active="budget" role={user.role} lang={lang} />
    </div>
</Layout>
```

Note: This is a simplified version. When implementing, port the interactive elements (add/edit/delete modals, inline editing) from each sub-page. The accordion content should mirror the functionality of the original pages.

- [ ] **Step 4: Verify settings page**

Open http://localhost:3003/budget/settings and verify:
- All 5 accordion sections render
- Clicking a section toggles open/close
- URL hash navigation works (e.g., /budget/settings#rules opens rules section)
- Data loads correctly for each section

Test drawer navigation: open drawer → click "Reglas auto" → should navigate to /budget/settings#rules with rules section open.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/SettingsAccordion.astro frontend/src/pages/budget/settings.astro
git commit -m "feat(budget): consolidate settings into single accordion page"
```

---

## Task 8: Update Scan Receipt and Import Pages

**Files:**
- Modify: `frontend/src/pages/budget/scan-receipt.astro`
- Modify: `frontend/src/pages/budget/import.astro`

These pages stay as-is functionally, but need the new nav.

- [ ] **Step 1: Update scan-receipt.astro nav**

Read `frontend/src/pages/budget/scan-receipt.astro`, then replace:
- `import BudgetNav from "@components/BudgetNav.astro"` → `import BudgetNavNew from "@components/BudgetNavNew.astro"` + `import DrawerMenu from "@components/DrawerMenu.astro"`
- `<BudgetNav active="..." .../>` → `<BudgetNavNew active="month" lang={lang} />` + `<DrawerMenu lang={lang} />`

- [ ] **Step 2: Update import.astro nav**

Same changes as Step 1 for `frontend/src/pages/budget/import.astro`.

- [ ] **Step 3: Verify both pages render**

Open http://localhost:3003/budget/scan-receipt and http://localhost:3003/budget/import. Verify new nav renders and drawer works. Existing functionality should be unchanged.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/budget/scan-receipt.astro frontend/src/pages/budget/import.astro
git commit -m "feat(budget): update scan-receipt and import pages with new nav"
```

---

## Task 9: Clean Up Old Pages

**Files:**
- Delete: 15 old pages (see list below)
- Modify: `frontend/src/components/BudgetNav.astro` — keep for now (backward compat) or delete

- [ ] **Step 1: Delete old pages**

Delete these files:

```bash
rm frontend/src/pages/budget/month/index.astro
rm frontend/src/pages/budget/month/[year]/[month].astro
rm -r frontend/src/pages/budget/month/
rm frontend/src/pages/budget/categories/index.astro
rm -r frontend/src/pages/budget/categories/
rm frontend/src/pages/budget/accounts/index.astro
rm frontend/src/pages/budget/accounts/[id].astro
rm frontend/src/pages/budget/accounts/[id]/reconcile.astro
rm -r frontend/src/pages/budget/accounts/[id]/
rm frontend/src/pages/budget/accounts/new.astro
rm -r frontend/src/pages/budget/accounts/
rm frontend/src/pages/budget/transactions/new.astro
rm -r frontend/src/pages/budget/transactions/
rm frontend/src/pages/budget/reports/spending.astro
rm frontend/src/pages/budget/reports/income-vs-expense.astro
rm frontend/src/pages/budget/reports/net-worth.astro
rm frontend/src/pages/budget/reports/budget-analysis.astro
rm -r frontend/src/pages/budget/reports/
rm frontend/src/pages/budget/settings/rules.astro
rm frontend/src/pages/budget/settings/payees.astro
rm frontend/src/pages/budget/settings/recurring.astro
rm frontend/src/pages/budget/settings/backups.astro
rm -r frontend/src/pages/budget/settings/
```

- [ ] **Step 2: Delete old BudgetNav component**

```bash
rm frontend/src/components/BudgetNav.astro
```

- [ ] **Step 3: Verify no broken imports**

```bash
cd frontend && npm run build 2>&1 | tail -30
```

Expected: Build succeeds. If there are broken imports referencing deleted files or `BudgetNav`, fix them.

- [ ] **Step 4: Verify all 6 new pages work**

Test each page in the browser:
- http://localhost:3003/budget/ (hub + month)
- http://localhost:3003/budget/transactions (with filters)
- http://localhost:3003/budget/reports (with sub-tabs)
- http://localhost:3003/budget/scan-receipt
- http://localhost:3003/budget/import
- http://localhost:3003/budget/settings (with accordions)

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(budget): remove 15 old pages and old BudgetNav component"
```

---

## Task 10: Final Verification and Polish

**Files:**
- Various minor fixes across new pages

- [ ] **Step 1: Test the complete daily loop**

1. Open http://localhost:3003/budget/
2. Click FAB (+)
3. Enter amount, payee, category, save
4. Verify confirmation shows
5. Close modal
6. Verify the month view reflects the new transaction (may need page refresh)

- [ ] **Step 2: Test drawer navigation**

1. Click ☰
2. Navigate to each drawer link
3. Verify all links work and land on correct pages/sections

- [ ] **Step 3: Test reports flow**

1. Click "Reportes" tab
2. Switch between all 4 sub-tabs
3. Change period selector
4. Verify data changes

- [ ] **Step 4: Test mobile responsiveness**

Open Chrome DevTools, toggle device toolbar (Ctrl+Shift+M), test at 375px width:
- Tab bar doesn't overflow
- Drawer opens full-width
- FAB doesn't overlap content
- Bottom sheet modal works on mobile

- [ ] **Step 5: Fix any issues found**

Address any bugs or visual issues discovered during testing.

- [ ] **Step 6: Final commit**

```bash
git add -A
git commit -m "fix(budget): polish UX redesign after testing"
```
