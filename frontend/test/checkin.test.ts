import { describe, expect, it } from "vitest";

import {
    CHECKIN_COPY, NOTE_MAX, NOTE_REASONS, REASONS, answerBody, chatHref, checkinView, dismissBody, reasonLabel,
    takesNote, tipFor,
} from "../src/lib/checkin";

describe("reasons", () => {
    it("are the seven the backend accepts, in order", () => {
        expect([...REASONS]).toEqual(["too_hard", "not_clear", "no_time", "not_fair", "forgot", "app_problem", "other"]);
        expect([...NOTE_REASONS]).toEqual(["app_problem", "other"]);
        expect(NOTE_MAX).toBe(200);
    });
    it("every reason has a label and a tip in both languages", () => {
        for (const r of REASONS) {
            for (const lang of ["es", "en"] as const) {
                expect(reasonLabel(r, lang).length).toBeGreaterThan(3);
                expect(tipFor(r, lang).length).toBeGreaterThan(10);
            }
        }
        expect(reasonLabel("not_clear", "es")).toBe("No sé bien qué hacer");
        expect(reasonLabel("app_problem", "en")).toBe("The app won't let me");
        expect(tipFor("too_hard", "en")).toBe("Split it: set a 5-minute timer and do only the first part.");
        expect(tipFor("not_fair", "es")).toBe("Díselo a tus papás: en la app pueden volver a repartir las tareas de la semana.");
    });
    it("only the two open reasons take a note", () => {
        expect(REASONS.filter(takesNote)).toEqual(["app_problem", "other"]);
    });
});

describe("card copy", () => {
    it("asks, offers a way out, and says where a note goes — in both languages", () => {
        expect(CHECKIN_COPY.question).toEqual({ es: "¿Atorado con", en: "Stuck on" });
        expect(CHECKIN_COPY.yes).toEqual({ es: "Sí, ayúdame", en: "Yes, help me" });
        expect(CHECKIN_COPY.notNow).toEqual({ es: "Ahora no", en: "Not now" });
        expect(CHECKIN_COPY.noteHint).toEqual({
            es: "Tu nota llega al equipo de la app, sin tu nombre.",
            en: "Your note goes to the app's team, without your name.",
        });
        expect(CHECKIN_COPY.chat).toEqual({ es: "Hablarlo con Jarvis", en: "Talk it through with Jarvis" });
    });
    it("never promises that parents cannot see the answer", () => {
        const all = JSON.stringify(CHECKIN_COPY);
        expect(all).not.toMatch(/tus pap[aá]s no|your parents (won't|will not|can't|cannot)/i);
    });
});

describe("checkinView", () => {
    const offer = { assignment_id: "a1", title: "Take out the trash", title_es: "Saca la basura", trigger: "late", days_late: 2 };
    it("is null without an offer", () => {
        for (const v of [null, undefined, {}, { offer: null }, { offer: {} }, { offer: { title: "x" } }, "nope"]) {
            expect(checkinView(v, "es")).toBeNull();
        }
    });
    it("uses the Spanish title when there is one", () => {
        expect(checkinView({ offer, can_chat: true }, "es")).toEqual({ assignmentId: "a1", title: "Saca la basura", canChat: true });
        expect(checkinView({ offer, can_chat: false }, "en")).toEqual({ assignmentId: "a1", title: "Take out the trash", canChat: false });
        expect(checkinView({ offer: { ...offer, title_es: null } }, "es")?.title).toBe("Take out the trash");
    });
    it("treats a missing can_chat as no chat", () => {
        expect(checkinView({ offer }, "en")?.canChat).toBe(false);
    });
});

describe("request bodies", () => {
    it("an answer for a chore reason never carries a note", () => {
        expect(answerBody("a1", "too_hard", "my brother never does his")).toEqual({ assignment_id: "a1", outcome: "answered", reason: "too_hard" });
    });
    it("an open reason carries a trimmed note, capped, or none when blank", () => {
        expect(answerBody("a1", "other", "  hi there ")).toEqual({ assignment_id: "a1", outcome: "answered", reason: "other", note: "hi there" });
        expect(answerBody("a1", "app_problem", "   ")).toEqual({ assignment_id: "a1", outcome: "answered", reason: "app_problem" });
        expect((answerBody("a1", "other", "x".repeat(300)) as { note: string }).note).toHaveLength(200);
    });
    it("a dismissal is just that", () => {
        expect(dismissBody("a1")).toEqual({ assignment_id: "a1", outcome: "dismissed" });
    });
});

describe("chatHref", () => {
    it("opens Jarvis with a first message typed, in the teen's language", () => {
        const es = chatHref("Saca la basura", "not_clear", "es");
        expect(es.startsWith("/parent/jarvis?q=")).toBe(true);
        expect(decodeURIComponent(es.split("q=")[1])).toBe("Estoy atorado con «Saca la basura»: no sé bien qué hacer. ¿Me ayudas?");
        expect(decodeURIComponent(chatHref("Take out the trash", "too_hard", "en").split("q=")[1]))
            .toBe('I\'m stuck on "Take out the trash": it\'s too hard. Can you help?');
    });
    it("encodes a title with special characters", () => {
        const href = chatHref("Tidy & sweep?", "forgot", "en");
        expect(href).not.toContain("&");
        expect(decodeURIComponent(href.split("q=")[1])).toContain("Tidy & sweep?");
    });
});
