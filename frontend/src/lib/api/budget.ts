/**
 * Budget API client for Family Task Manager
 * Provides typed functions for all budget-related API endpoints
 */

import { apiFetch } from "../api";
import type { ApiResponse } from "../../types/api";
import type { BudgetImportLog } from "@lib/types/budget";

// Budget Types
export interface BudgetCategoryGroup {
    id: string;
    family_id: string;
    name: string;
    sort_order: number;
    is_income: boolean;
    hidden: boolean;
    created_at: string;
    updated_at: string;
}

export interface BudgetCategory {
    id: string;
    family_id: string;
    name: string;
    group_id: string;
    sort_order: number;
    hidden: boolean;
    rollover_enabled: boolean;
    goal_amount: number;
    created_at: string;
    updated_at: string;
}

export interface CategoryGroupWithCategories extends BudgetCategoryGroup {
    categories: BudgetCategory[];
}

export interface BudgetAccount {
    id: string;
    family_id: string;
    name: string;
    type: "checking" | "savings" | "credit" | "investment" | "other";
    offbudget: boolean;
    closed: boolean;
    notes?: string;
    sort_order: number;
    created_at: string;
    updated_at: string;
}

export interface BudgetPayee {
    id: string;
    family_id: string;
    name: string;
    created_at: string;
    updated_at: string;
}

export interface BudgetTransaction {
    id: string;
    family_id: string;
    account_id: string;
    date: string;
    amount: number;
    payee_id?: string;
    category_id?: string;
    notes?: string;
    cleared: boolean;
    reconciled: boolean;
    imported_id?: string;
    parent_id?: string;
    is_parent: boolean;
    transfer_account_id?: string;
    created_at: string;
    updated_at: string;
}

export interface BudgetAllocation {
    id: string;
    family_id: string;
    category_id: string;
    month: string; // YYYY-MM-DD (always 1st of month)
    amount: number;
    created_at: string;
    updated_at: string;
}

export interface ImportLogsResponse extends ApiResponse<BudgetImportLog[]> {}

export interface CategoryWithActivity {
    id: string;
    name: string;
    budgeted: number;
    activity: number;
    available: number;
    previous_balance: number;
    goal_amount: number;
    rollover_enabled: boolean;
}

export interface CategoryGroupWithActivity {
    id: string;
    name: string;
    is_income: boolean;
    categories: CategoryWithActivity[];
    total_budgeted: number;
    total_activity: number;
    total_available: number;
}

export interface MonthBudgetView {
    month: string;
    year: number;
    month_num: number;
    category_groups: CategoryGroupWithActivity[];
    ready_to_assign: number;
    totals: {
        budgeted: number;
        activity: number;
        available: number;
        income: number;
    };
}

export interface MonthBudgetSummary {
    month: string;
    total_budgeted: number;
    total_income: number;
    total_spent: number;
    to_budget: number;
}

// API Functions

/**
 * Get all category groups with their categories
 */
export async function getCategoryGroups(token: string): Promise<ApiResponse<CategoryGroupWithCategories[]>> {
    return apiFetch<CategoryGroupWithCategories[]>("/api/budget/categories/groups", { token });
}

/**
 * Get all categories (optionally filtered by group)
 */
export async function getCategories(token: string, groupId?: string): Promise<ApiResponse<BudgetCategory[]>> {
    const path = groupId 
        ? `/api/budget/categories/?group_id=${groupId}`
        : "/api/budget/categories/";
    return apiFetch<BudgetCategory[]>(path, { token });
}

/**
 * Create a new category group
 */
export async function createCategoryGroup(
    token: string,
    data: {
        name: string;
        is_income?: boolean;
        sort_order?: number;
    }
): Promise<ApiResponse<BudgetCategoryGroup>> {
    return apiFetch<BudgetCategoryGroup>("/api/budget/categories/groups", {
        token,
        method: "POST",
        body: JSON.stringify(data),
    });
}

/**
 * Update a category group
 */
export async function updateCategoryGroup(
    token: string,
    id: string,
    data: Partial<{
        name: string;
        is_income: boolean;
        hidden: boolean;
        sort_order: number;
    }>
): Promise<ApiResponse<BudgetCategoryGroup>> {
    return apiFetch<BudgetCategoryGroup>(`/api/budget/categories/groups/${id}`, {
        token,
        method: "PUT",
        body: JSON.stringify(data),
    });
}

/**
 * Delete a category group
 */
export async function deleteCategoryGroup(token: string, id: string): Promise<ApiResponse<void>> {
    return apiFetch<void>(`/api/budget/categories/groups/${id}`, {
        token,
        method: "DELETE",
    });
}

/**
 * Create a new category
 */
export async function createCategory(
    token: string,
    data: {
        name: string;
        group_id: string;
        rollover_enabled?: boolean;
        goal_amount?: number;
        sort_order?: number;
    }
): Promise<ApiResponse<BudgetCategory>> {
    return apiFetch<BudgetCategory>("/api/budget/categories/", {
        token,
        method: "POST",
        body: JSON.stringify(data),
    });
}

/**
 * Update a category
 */
export async function updateCategory(
    token: string,
    id: string,
    data: Partial<{
        name: string;
        group_id: string;
        rollover_enabled: boolean;
        goal_amount: number;
        hidden: boolean;
        sort_order: number;
    }>
): Promise<ApiResponse<BudgetCategory>> {
    return apiFetch<BudgetCategory>(`/api/budget/categories/${id}`, {
        token,
        method: "PUT",
        body: JSON.stringify(data),
    });
}

/**
 * Delete a category
 */
export async function deleteCategory(token: string, id: string): Promise<ApiResponse<void>> {
    return apiFetch<void>(`/api/budget/categories/${id}`, {
        token,
        method: "DELETE",
    });
}

/**
 * Get all budget accounts
 */
export async function getAccounts(token: string, options?: {
    type?: string;
    budgetOnly?: boolean;
    includeClosed?: boolean;
}): Promise<ApiResponse<BudgetAccount[]>> {
    const params = new URLSearchParams();
    if (options?.type) params.set("type", options.type);
    if (options?.budgetOnly !== undefined) params.set("budget_only", options.budgetOnly.toString());
    if (options?.includeClosed !== undefined) params.set("include_closed", options.includeClosed.toString());
    
    const path = params.toString() 
        ? `/api/budget/accounts/?${params.toString()}`
        : "/api/budget/accounts/";
    return apiFetch<BudgetAccount[]>(path, { token });
}

/**
 * Get a single account by ID
 */
export async function getAccount(token: string, id: string): Promise<ApiResponse<BudgetAccount>> {
    return apiFetch<BudgetAccount>(`/api/budget/accounts/${id}`, { token });
}

/**
 * Create a new account
 */
export async function createAccount(
    token: string,
    account: {
        name: string;
        type: "checking" | "savings" | "credit" | "investment" | "other";
        offbudget?: boolean;
        notes?: string;
        starting_balance?: number;
    }
): Promise<ApiResponse<BudgetAccount>> {
    return apiFetch<BudgetAccount>("/api/budget/accounts/", {
        token,
        method: "POST",
        body: JSON.stringify(account),
    });
}

/**
 * Update an account
 */
export async function updateAccount(
    token: string,
    id: string,
    account: Partial<{
        name: string;
        type: "checking" | "savings" | "credit" | "investment" | "other";
        offbudget: boolean;
        closed: boolean;
        notes: string;
    }>
): Promise<ApiResponse<BudgetAccount>> {
    return apiFetch<BudgetAccount>(`/api/budget/accounts/${id}`, {
        token,
        method: "PUT",
        body: JSON.stringify(account),
    });
}

/**
 * Delete an account
 */
export async function deleteAccount(token: string, id: string): Promise<ApiResponse<void>> {
    return apiFetch<void>(`/api/budget/accounts/${id}`, {
        token,
        method: "DELETE",
    });
}

/**
 * Get account balance
 */
export async function getAccountBalance(token: string, id: string): Promise<ApiResponse<{
    total: number;
    cleared: number;
    uncleared: number;
}>> {
    return apiFetch<{ total: number; cleared: number; uncleared: number }>(
        `/api/budget/accounts/${id}/balance`,
        { token }
    );
}

/**
 * Get all payees
 */
export async function getPayees(token: string): Promise<ApiResponse<BudgetPayee[]>> {
    return apiFetch<BudgetPayee[]>("/api/budget/payees/", { token });
}

/**
 * Get transactions (optionally filtered)
 */
export async function getTransactions(token: string, options?: {
    accountId?: string;
    categoryId?: string;
    startDate?: string;
    endDate?: string;
    limit?: number;
    offset?: number;
}): Promise<ApiResponse<BudgetTransaction[]>> {
    const params = new URLSearchParams();
    if (options?.accountId) params.set("account_id", options.accountId);
    if (options?.categoryId) params.set("category_id", options.categoryId);
    if (options?.startDate) params.set("start_date", options.startDate);
    if (options?.endDate) params.set("end_date", options.endDate);
    if (options?.limit) params.set("limit", options.limit.toString());
    if (options?.offset) params.set("offset", options.offset.toString());
    
    const path = params.toString()
        ? `/api/budget/transactions/?${params.toString()}`
        : "/api/budget/transactions/";
    return apiFetch<BudgetTransaction[]>(path, { token });
}

/**
 * Create a new transaction
 */
export async function createTransaction(
    token: string,
    transaction: {
        account_id: string;
        date: string;
        amount: number;
        payee_id?: string;
        category_id?: string;
        notes?: string;
        cleared?: boolean;
    }
): Promise<ApiResponse<BudgetTransaction>> {
    return apiFetch<BudgetTransaction>("/api/budget/transactions/", {
        token,
        method: "POST",
        body: JSON.stringify(transaction),
    });
}

/**
 * Update a transaction
 */
export async function updateTransaction(
    token: string,
    id: string,
    transaction: Partial<{
        account_id: string;
        date: string;
        amount: number;
        payee_id: string;
        category_id: string;
        notes: string;
        cleared: boolean;
    }>
): Promise<ApiResponse<BudgetTransaction>> {
    return apiFetch<BudgetTransaction>(`/api/budget/transactions/${id}`, {
        token,
        method: "PUT",
        body: JSON.stringify(transaction),
    });
}

/**
 * Delete a transaction
 */
export async function deleteTransaction(token: string, id: string): Promise<ApiResponse<void>> {
    return apiFetch<void>(`/api/budget/transactions/${id}`, {
        token,
        method: "DELETE",
    });
}

/**
 * Reconcile transactions for an account
 */
export async function reconcileAccount(
    token: string,
    accountId: string,
    transactionIds: string[]
): Promise<ApiResponse<{ updated_count: number }>> {
    return apiFetch<{ updated_count: number }>(
        `/api/budget/accounts/${accountId}/reconcile`,
        {
            token,
            method: "POST",
            body: JSON.stringify({ transaction_ids: transactionIds }),
        }
    );
}

/**
 * Get monthly budget view with all calculations
 */
export async function getMonthBudget(
    token: string,
    year: number,
    month: number
): Promise<ApiResponse<MonthBudgetView>> {
    return apiFetch<MonthBudgetView>(`/api/budget/month/${year}/${month}`, { token });
}

/**
 * Get monthly budget summary
 */
export async function getMonthSummary(
    token: string,
    year: number,
    month: number
): Promise<ApiResponse<MonthBudgetSummary>> {
    return apiFetch<MonthBudgetSummary>(`/api/budget/month/${year}/${month}/summary`, { token });
}

/**
 * Set budget allocation for a category and month
 */
export async function setBudgetAllocation(
    token: string,
    categoryId: string,
    month: string,
    amount: number
): Promise<ApiResponse<BudgetAllocation>> {
    return apiFetch<BudgetAllocation>("/api/budget/allocations/set", {
        token,
        method: "POST",
        body: JSON.stringify({
            category_id: categoryId,
            month,
            amount,
        }),
    });
}

/**
 * Format amount in cents to currency string
 */
export function formatCurrency(cents: number, currency: string = "MXN"): string {
    const amount = cents / 100;
    return new Intl.NumberFormat("es-MX", {
        style: "currency",
        currency,
        minimumFractionDigits: 0,
        maximumFractionDigits: 0,
    }).format(amount);
}

/**
 * Get month name in Spanish
 */
export function getMonthName(monthNum: number, lang: string = "es"): string {
    const date = new Date(2000, monthNum - 1, 1);
    return new Intl.DateTimeFormat(lang === "es" ? "es-MX" : "en-US", { month: "long" }).format(date);
}

/**
 * Format date for display
 */
export function formatDate(dateStr: string, lang: string = "es"): string {
    const date = new Date(dateStr);
    return new Intl.DateTimeFormat(lang === "es" ? "es-MX" : "en-US", {
        year: "numeric",
        month: "short",
        day: "numeric",
    }).format(date);
}

/**
 * Get spending report
 */
export async function getSpendingReport(
    token: string,
    startDate: string,
    endDate: string,
    groupBy: "category" | "group" | "month" | "payee" = "category"
): Promise<ApiResponse<any>> {
    const params = new URLSearchParams({
        start_date: startDate,
        end_date: endDate,
        group_by: groupBy,
    });
    return apiFetch<any>(`/api/budget/reports/spending?${params.toString()}`, { token });
}

/**
 * Get income vs expense report
 */
export async function getIncomeVsExpenseReport(
    token: string,
    startDate: string,
    endDate: string,
    groupBy: "month" | "week" | "day" = "month"
): Promise<ApiResponse<any>> {
    const params = new URLSearchParams({
        start_date: startDate,
        end_date: endDate,
        group_by: groupBy,
    });
    return apiFetch<any>(`/api/budget/reports/income-vs-expense?${params.toString()}`, { token });
}

/**
 * Get net worth report
 */
export async function getNetWorthReport(
    token: string,
    asOfDate?: string
): Promise<ApiResponse<any>> {
    const params = asOfDate ? new URLSearchParams({ as_of_date: asOfDate }) : new URLSearchParams();
    const query = params.toString() ? `?${params.toString()}` : '';
    return apiFetch<any>(`/api/budget/reports/net-worth${query}`, { token });
}

/**
 * Get import history
 */
export async function getImportLogs(token: string): Promise<ApiResponse<BudgetImportLog[]>> {
    return apiFetch<BudgetImportLog[]>("/api/budget/imports", { token });
}

// ─── Recurring Transactions ───────────────────────────────────────────────────

export interface RecurringTransaction {
    id: string;
    family_id: string;
    account_id: string;
    category_id?: string;
    payee_id?: string;
    description: string;
    amount: number;
    transaction_type: "income" | "expense";
    frequency: "daily" | "weekly" | "biweekly" | "monthly" | "quarterly" | "annual";
    next_due_date: string;
    is_active: boolean;
    created_at: string;
    updated_at: string;
}

export async function getRecurringTransactions(
    token: string,
    options?: { accountId?: string; activeOnly?: boolean }
): Promise<ApiResponse<RecurringTransaction[]>> {
    const params = new URLSearchParams();
    if (options?.accountId) params.set("account_id", options.accountId);
    if (options?.activeOnly !== undefined) params.set("active_only", options.activeOnly.toString());
    const query = params.toString() ? `?${params.toString()}` : "";
    return apiFetch<RecurringTransaction[]>(`/api/budget/recurring-transactions/${query}`, { token });
}

export async function createRecurringTransaction(
    token: string,
    data: {
        description: string;
        amount: number;
        transaction_type: "income" | "expense";
        account_id: string;
        category_id?: string;
        frequency: string;
        next_due_date: string;
    }
): Promise<ApiResponse<RecurringTransaction>> {
    return apiFetch<RecurringTransaction>("/api/budget/recurring-transactions/", {
        token,
        method: "POST",
        body: JSON.stringify(data),
    });
}

export async function updateRecurringTransaction(
    token: string,
    id: string,
    data: Partial<{
        description: string;
        amount: number;
        transaction_type: "income" | "expense";
        account_id: string;
        category_id: string;
        frequency: string;
        next_due_date: string;
        is_active: boolean;
    }>
): Promise<ApiResponse<RecurringTransaction>> {
    return apiFetch<RecurringTransaction>(`/api/budget/recurring-transactions/${id}`, {
        token,
        method: "PUT",
        body: JSON.stringify(data),
    });
}

export async function deleteRecurringTransaction(token: string, id: string): Promise<ApiResponse<void>> {
    return apiFetch<void>(`/api/budget/recurring-transactions/${id}`, {
        token,
        method: "DELETE",
    });
}

export async function postRecurringTransaction(
    token: string,
    id: string,
    transactionDate?: string
): Promise<ApiResponse<BudgetTransaction>> {
    const query = transactionDate ? `?transaction_date=${transactionDate}` : "";
    return apiFetch<BudgetTransaction>(`/api/budget/recurring-transactions/${id}/post${query}`, {
        token,
        method: "POST",
    });
}

// ─── Categorization Rules ─────────────────────────────────────────────────────

export interface CategorizationRule {
    id: string;
    family_id: string;
    pattern: string;
    match_field: "payee" | "description" | "both";
    rule_type: "exact" | "contains" | "startswith" | "regex";
    category_id: string;
    priority: number;
    enabled: boolean;
    created_at: string;
    updated_at: string;
    category?: BudgetCategory;
}

export async function getCategorizationRules(token: string): Promise<ApiResponse<CategorizationRule[]>> {
    return apiFetch<CategorizationRule[]>("/api/budget/categorization-rules/", { token });
}

export async function createCategorizationRule(
    token: string,
    data: {
        pattern: string;
        match_field: "payee" | "description" | "both";
        rule_type: "exact" | "contains" | "startswith" | "regex";
        category_id: string;
        priority?: number;
        enabled?: boolean;
    }
): Promise<ApiResponse<CategorizationRule>> {
    return apiFetch<CategorizationRule>("/api/budget/categorization-rules/", {
        token,
        method: "POST",
        body: JSON.stringify({ enabled: true, priority: 0, ...data }),
    });
}

export async function updateCategorizationRule(
    token: string,
    id: string,
    data: Partial<{
        pattern: string;
        match_field: "payee" | "description" | "both";
        rule_type: "exact" | "contains" | "startswith" | "regex";
        category_id: string;
        priority: number;
        enabled: boolean;
    }>
): Promise<ApiResponse<CategorizationRule>> {
    return apiFetch<CategorizationRule>(`/api/budget/categorization-rules/${id}`, {
        token,
        method: "PUT",
        body: JSON.stringify(data),
    });
}

export async function deleteCategorizationRule(token: string, id: string): Promise<ApiResponse<void>> {
    return apiFetch<void>(`/api/budget/categorization-rules/${id}`, {
        token,
        method: "DELETE",
    });
}

// ─── Goals ────────────────────────────────────────────────────────────────────

export interface BudgetGoal {
    id: string;
    family_id: string;
    category_id: string;
    goal_type: "spending_limit" | "savings_target";
    target_amount: number;
    period: "monthly" | "quarterly" | "annual";
    name: string;
    notes?: string;
    start_date: string;
    end_date?: string;
    is_active: boolean;
    created_at: string;
    updated_at: string;
}

export interface GoalProgress {
    goal_id: string;
    goal_type: string;
    target_amount: number;
    current_amount: number;
    progress_percentage: number;
    period: string;
    is_on_track: boolean;
}

export async function getGoals(
    token: string,
    options?: { categoryId?: string; activeOnly?: boolean }
): Promise<ApiResponse<BudgetGoal[]>> {
    const params = new URLSearchParams();
    if (options?.categoryId) params.set("category_id", options.categoryId);
    if (options?.activeOnly !== undefined) params.set("active_only", options.activeOnly.toString());
    const query = params.toString() ? `?${params.toString()}` : "";
    return apiFetch<BudgetGoal[]>(`/api/budget/goals/${query}`, { token });
}

export async function createGoal(
    token: string,
    data: {
        category_id: string;
        goal_type: "spending_limit" | "savings_target";
        target_amount: number;
        period: "monthly" | "quarterly" | "annual";
        name: string;
        notes?: string;
        start_date: string;
        end_date?: string;
        is_active?: boolean;
    }
): Promise<ApiResponse<BudgetGoal>> {
    return apiFetch<BudgetGoal>("/api/budget/goals/", {
        token,
        method: "POST",
        body: JSON.stringify({ is_active: true, ...data }),
    });
}

export async function updateGoal(
    token: string,
    id: string,
    data: Partial<{
        goal_type: "spending_limit" | "savings_target";
        target_amount: number;
        period: "monthly" | "quarterly" | "annual";
        name: string;
        notes: string;
        start_date: string;
        end_date: string;
        is_active: boolean;
    }>
): Promise<ApiResponse<BudgetGoal>> {
    return apiFetch<BudgetGoal>(`/api/budget/goals/${id}`, {
        token,
        method: "PUT",
        body: JSON.stringify(data),
    });
}

export async function deleteGoal(token: string, id: string): Promise<ApiResponse<void>> {
    return apiFetch<void>(`/api/budget/goals/${id}`, {
        token,
        method: "DELETE",
    });
}

export async function getGoalProgress(token: string, id: string): Promise<ApiResponse<GoalProgress>> {
    return apiFetch<GoalProgress>(`/api/budget/goals/${id}/progress`, { token });
}

// ─── Month Locking ────────────────────────────────────────────────────────────

export interface MonthStatus {
    year: number;
    month: number;
    is_locked: boolean;
    locked_at?: string;
}

export interface ClosedMonth {
    year: number;
    month: number;
    locked_at: string;
}

export async function getMonthStatus(
    token: string,
    year: number,
    month: number
): Promise<ApiResponse<MonthStatus>> {
    return apiFetch<MonthStatus>(`/api/budget/months/${year}/${month}/status`, { token });
}

export async function closeMonth(
    token: string,
    year: number,
    month: number
): Promise<ApiResponse<{ message: string }>> {
    return apiFetch<{ message: string }>(`/api/budget/months/${year}/${month}/close`, {
        token,
        method: "POST",
    });
}

export async function reopenMonth(
    token: string,
    year: number,
    month: number
): Promise<ApiResponse<{ message: string }>> {
    return apiFetch<{ message: string }>(`/api/budget/months/${year}/${month}/reopen`, {
        token,
        method: "POST",
    });
}

export async function getClosedMonths(
    token: string,
    limit: number = 50,
    offset: number = 0
): Promise<ApiResponse<ClosedMonth[]>> {
    return apiFetch<ClosedMonth[]>(
        `/api/budget/months/closed?limit=${limit}&offset=${offset}`,
        { token }
    );
}

// ─── Account Transfers ────────────────────────────────────────────────────────

export async function transferBetweenAccounts(
    token: string,
    data: {
        from_account_id: string;
        to_account_id: string;
        amount: number;
        date: string;
        notes?: string;
    }
): Promise<ApiResponse<BudgetTransaction[]>> {
    return apiFetch<BudgetTransaction[]>("/api/budget/transfers/accounts", {
        token,
        method: "POST",
        body: JSON.stringify(data),
    });
}
