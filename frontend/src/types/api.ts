/**
 * TypeScript type definitions for API responses
 */

export interface User {
    id: string;
    email: string;
    name: string;
    role: "PARENT" | "CHILD" | "TEEN";
    points: number;
    family_id: string;
    is_active: boolean;
}

export interface LoginResponse {
    access_token: string;
    token_type: string;
}

export interface Assignment {
    id: string;
    template_id: string;
    assigned_to_id: string;
    scheduled_date: string;
    status: "pending" | "completed" | "cancelled" | "overdue";
    completed_at?: string;
    template_title: string;
    template_title_es?: string;
    template_description?: string;
    template_description_es?: string;
    template_points: number;
    template_is_bonus: boolean;
    can_complete: boolean;
}

export interface DailyProgress {
    required_total: number;
    required_completed: number;
    bonus_total: number;
    bonus_completed: number;
    bonus_unlocked: boolean;
    assignments: Assignment[];
}

export interface ApiResponse<T> {
    data: T | null;
    ok: boolean;
    status: number;
    error?: string;
}

export interface ApiError {
    detail: string;
}
