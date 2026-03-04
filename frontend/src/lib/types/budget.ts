export interface BudgetImportLog {
    id: string;
    family_id?: string;
    account_id?: string;
    account_name?: string;
    filename?: string;
    total_rows?: number;
    successful_imports?: number;
    skipped_rows?: number;
    status?: "success" | "failed" | "partial";
    created_at?: string;
    created_payees?: number;
    created_categories?: number;
    created_accounts?: number;
    created_transactions?: number;
    created_import_rules?: number;
    created_budgets?: number;
    created_envelopes?: number;
    created_users?: number;
}
