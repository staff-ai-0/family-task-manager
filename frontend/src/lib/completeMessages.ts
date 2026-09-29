/**
 * Kid-facing copy for completing an assignment. Never surface the raw backend
 * `detail` (English, technical); map known cases to bilingual copy. Shared by
 * the form (302 + flash) and JSON (deck) modes of /api/assignments/complete.
 */
export function completeErrorMessage(status: number, detail: string, es: boolean): string {
    if (detail.includes(" / ")) {
        // Backend already ships bilingual "es / en" copy — pick a side.
        const [esPart, enPart] = detail.split(" / ");
        return es ? esPart : (enPart ?? esPart);
    }
    if (/cannot be completed/i.test(detail) && /completed/i.test(detail)) {
        return es
            ? "¡Esa tarea ya estaba registrada! Tus puntos ya cuentan."
            : "That task was already saved! Your points are already counted.";
    }
    if (/mandatory/i.test(detail)) {
        return es
            ? "Primero termina tus tareas obligatorias (incluye las atrasadas)."
            : "Finish your required chores first (including overdue ones).";
    }
    if (/proof text/i.test(detail)) {
        return es ? "Cuéntanos qué hiciste para enviar este gig." : "Tell us what you did to submit this gig.";
    }
    if (status >= 400 && status < 500) {
        return es ? "No se pudo guardar la tarea. Intenta de nuevo." : "Couldn't save the task. Please try again.";
    }
    return es ? "Algo salió mal. Intenta de nuevo en un momento." : "Something went wrong. Please try again in a moment.";
}

export function completeSuccessMessage(assignment: any, es: boolean): string {
    const title = (es && assignment?.template_title_es) || assignment?.template_title || "";
    // approval_status alone is authoritative: auto-approved gigs (trust
    // streak / AI validation) come back "approved" with points credited.
    if (!title) return "🎉";
    return assignment?.approval_status === "pending"
        ? (es ? `"${title}" enviada para aprobación 🎉` : `"${title}" submitted for approval 🎉`)
        : (es ? `¡"${title}" completada! 🎉` : `"${title}" completed! 🎉`);
}
