import { describe, expect, it } from "vitest";

import { formatActionLabel } from "../src/lib/jarvis-actions";

describe("formatActionLabel", () => {
    it("humanizes an ok action", () => {
        expect(formatActionLabel("budget_spending_report(ok)")).toBe("budget spending report ✓");
    });
    it("marks pending actions", () => {
        expect(formatActionLabel("calendar_create_event(pending)")).toBe("calendar create event ⏳");
    });
    it("marks failed actions", () => {
        expect(formatActionLabel("shopping_add_item(err)")).toBe("shopping add item ⚠");
    });
    it("degrades gracefully on an unexpected shape", () => {
        expect(formatActionLabel("  weird_label ")).toBe("weird label");
    });
});
