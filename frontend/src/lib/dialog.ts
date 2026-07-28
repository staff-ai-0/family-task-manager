/**
 * Modal behaviour for the hand-rolled page-level dialogs.
 *
 * The component modals (FABModal, TaskCreateModal, MoreSheet, DrawerMenu,
 * AccountCreateModal) each grew their own copy of the same four things: close
 * on Escape, move focus inside on open, send it back to the opener on close,
 * and keep Tab from wandering behind the overlay. The page-level ones (bank,
 * gigs, parent/gigs, family-bank, parent/tasks, parent/assignments) only
 * toggled a `hidden` class, so a keyboard or screen-reader user who opened one
 * was left tabbing through the page underneath it with no way out but the
 * mouse. This is that logic in one place.
 *
 * Behaviour only — the `role="dialog"` / `aria-modal="true"` / labelling
 * attributes live in the markup so they are correct before this ever runs.
 *
 *   const dlg = createDialog(modal, {
 *       closeTriggers: [document.getElementById("gig-modal-close")],
 *       initialFocus: () => titleInput,
 *       onClose: () => form.reset(),
 *   });
 *   openBtn.addEventListener("click", () => dlg.open());
 */

const FOCUSABLE = [
    "a[href]",
    "button:not([disabled])",
    "input:not([disabled])",
    "select:not([disabled])",
    "textarea:not([disabled])",
    '[tabindex]:not([tabindex="-1"])',
].join(", ");

export interface DialogOptions {
    /** Separate backdrop element, for dialogs that don't paint their own. */
    backdrop?: HTMLElement | null;
    /**
     * Focused when the dialog opens. Pass a thunk when the element is only
     * known at open time (or is swapped per action).
     */
    initialFocus?: HTMLElement | null | (() => HTMLElement | null);
    /** Elements whose click closes the dialog: the × , a Cancel button, … */
    closeTriggers?: (Element | null | undefined)[];
    /** Clicking the dialog's own overlay area closes it. Default true. */
    closeOnOutsideClick?: boolean;
    onOpen?: () => void;
    onClose?: () => void;
}

export interface Dialog {
    el: HTMLElement;
    isOpen: () => boolean;
    open: () => void;
    close: () => void;
}

export function createDialog(el: HTMLElement, opts: DialogOptions = {}): Dialog {
    const backdrop = opts.backdrop ?? null;
    let opener: HTMLElement | null = null;

    const isOpen = () => !el.classList.contains("hidden");

    const focusables = () =>
        Array.from(el.querySelectorAll<HTMLElement>(FOCUSABLE))
            // Dialogs hide sections per action (bank's "what for?" field, the
            // jar row on a settle) — display:none elements are not tabbable.
            .filter((f) => f.getClientRects().length > 0);

    // On document, not on the dialog: focus can sit outside it (nothing here is
    // inert), and Escape must still work from there.
    const onEscape = (e: KeyboardEvent) => {
        if (e.key === "Escape" && isOpen()) close();
    };

    // Manual Tab wrap for the same reason — the page behind stays focusable.
    const onTab = (e: KeyboardEvent) => {
        if (e.key !== "Tab") return;
        const f = focusables();
        if (!f.length) return;
        const first = f[0];
        const last = f[f.length - 1];
        if (e.shiftKey && document.activeElement === first) {
            e.preventDefault();
            last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
            e.preventDefault();
            first.focus();
        }
    };

    function open() {
        if (isOpen()) return;
        opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
        backdrop?.classList.remove("hidden");
        el.classList.remove("hidden");
        document.addEventListener("keydown", onEscape);
        opts.onOpen?.();
        // Next frame: focus() is a no-op while the element is still hidden.
        requestAnimationFrame(() => {
            const wanted = typeof opts.initialFocus === "function" ? opts.initialFocus() : opts.initialFocus;
            const target = wanted ?? focusables()[0];
            if (target) {
                target.focus();
            } else {
                // Nothing focusable inside: park focus on the dialog itself so
                // the reading cursor still lands in it.
                el.tabIndex = -1;
                el.focus();
            }
        });
    }

    function close() {
        if (!isOpen()) return;
        document.removeEventListener("keydown", onEscape);
        el.classList.add("hidden");
        backdrop?.classList.add("hidden");
        opts.onClose?.();
        // Back to whatever opened it, or the trigger is unreachable by keyboard
        // after a single open/close cycle.
        if (opener?.isConnected) opener.focus();
        opener = null;
    }

    el.addEventListener("keydown", onTab);
    if (opts.closeOnOutsideClick !== false) {
        // The dialog element spans the viewport and paints the overlay itself;
        // a click that lands on it (not on the card) is an outside click.
        el.addEventListener("click", (e) => {
            if (e.target === el) close();
        });
        backdrop?.addEventListener("click", () => close());
    }
    for (const trigger of opts.closeTriggers ?? []) {
        trigger?.addEventListener("click", () => close());
    }

    return { el, isOpen, open, close };
}
