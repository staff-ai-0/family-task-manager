/// <reference types="astro/client" />

interface Window {
    __budgetKeys?: boolean;
    __budgetUndo?: boolean;
    queueUndo?: (label: string, calls: any) => void;
}

declare namespace App {
    interface Locals {
        user?: import("./types/api").User;
        token?: string;
        plan?: Record<string, any>;
    }
}
