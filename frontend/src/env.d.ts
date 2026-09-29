/// <reference types="astro/client" />

interface Window {
    __budgetKeys?: boolean;
    __budgetUndo?: boolean;
    queueUndo?: (label: string, calls: any) => void;
    /** In-app dialogs for define:vars / is:inline scripts (UX-B1, set by AppDialog.astro). */
    ftmDialogs?: {
        confirmSheet: typeof import("./lib/dialogs").confirmSheet;
        promptSheet: typeof import("./lib/dialogs").promptSheet;
        toast: typeof import("./lib/toast").showToast;
        queueToast: typeof import("./lib/dialogs").queueToast;
    };
}

declare namespace App {
    interface Locals {
        user?: import("./types/api").User;
        token?: string;
        plan?: Record<string, any>;
    }
}
