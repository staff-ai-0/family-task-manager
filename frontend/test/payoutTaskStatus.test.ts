import { describe, expect, it } from "vitest";
import { payoutTaskStatusLabel } from "../src/lib/payoutTaskStatus";
import { t } from "../src/lib/i18n";

describe("payoutTaskStatusLabel", () => {
    it("labels a graded credit with its partial percent", () => {
        expect(payoutTaskStatusLabel({ status: "credited" }, "en")).toBe("Completed ✓");
        expect(payoutTaskStatusLabel({ status: "credited", grade: "partial", partial_credit_pct: 50 }, "es"))
            .toBe("Completada ✓ · parcial 50%");
    });
    it("uses the shared status copy for a taken chore", () => {
        expect(payoutTaskStatusLabel({ status: "taken" }, "es")).toBe(t("es", "pac_status_taken"));
        expect(payoutTaskStatusLabel({ status: "taken" }, "en")).toBe(t("en", "pac_status_taken"));
    });
    it("covers review, missed and not-done", () => {
        expect(payoutTaskStatusLabel({ status: "pending_review" }, "en")).toBe("Awaiting review");
        expect(payoutTaskStatusLabel({ status: "missed" }, "es")).toBe("No cumplida");
        expect(payoutTaskStatusLabel({ status: "not_done" }, "en")).toBe("Not done yet");
    });
});
