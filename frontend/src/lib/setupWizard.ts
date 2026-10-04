/** UX-E3 guided family setup — copy and the pure pieces of /parent/setup. */
import { errorDetail, fill, type PostResult } from "./chartScan";

export { errorDetail, fill, type PostResult };

export type Lang = "es" | "en";
export type Band = "3-5" | "6-8" | "9-12" | "13+";
export const BANDS: Band[] = ["3-5", "6-8", "9-12", "13+"];
export const PRIORITIES = ["routine", "school", "home", "kitchen", "pets", "self_care"] as const;
export const REWARD_STYLES = ["screen_time", "treats", "activities", "privileges", "toys"] as const;
/** Mirror of backend/app/core/modules.py TOGGLABLE_MODULES (parity test). */
export const TOGGLABLE_MODULES = ["meals", "shopping", "calendar", "pet", "chat", "budget", "gigs"] as const;

export const SETUP_COPY = {
    title: { es: "Configura tu familia", en: "Set up your family" },
    subtitle: { es: "Tres preguntas y te proponemos tareas, premios y chambitas", en: "Three questions and we propose chores, rewards and gigs" },
    stepKids: { es: "¿Quiénes son tus hijos?", en: "Who are your kids?" },
    stepKidsHint: { es: "Los que ya se unieron aparecen aquí. Agrega a los que faltan.", en: "Kids who already joined are listed. Add the ones who haven't." },
    kidName: { es: "Nombre", en: "Name" },
    kidBand: { es: "Edad", en: "Age" },
    addKid: { es: "+ Agregar hijo/a", en: "+ Add a kid" },
    removeKid: { es: "Quitar", en: "Remove" },
    skipKid: { es: "Incluir en esta configuración", en: "Include in this setup" },
    browsePacks: { es: "¿Prefieres ver paquetes listos?", en: "Prefer to browse ready-made packs?" },
    stepPriorities: { es: "¿Qué es lo más importante?", en: "What matters most?" },
    stepPrioritiesHint: { es: "Elige las que quieras (o ninguna).", en: "Pick any (or none)." },
    noteLabel: { es: "¿Algo más que debamos saber? (opcional)", en: "Anything else we should know? (optional)" },
    stepRewards: { es: "Premios y dinero", en: "Rewards & cash" },
    stepRewardsHint: { es: "¿Qué tipo de premios funcionan en tu casa?", en: "What kind of rewards work at home?" },
    wantsGigs: { es: "Un tablero de chambitas con dinero para trabajos extra", en: "A cash gig board for extra jobs" },
    back: { es: "Atrás", en: "Back" },
    next: { es: "Siguiente", en: "Next" },
    build: { es: "Armar mi plan", en: "Build my plan" },
    building: { es: "Armando el plan de tu familia…", en: "Building your family's plan…" },
    stepReview: { es: "Revisa y crea", en: "Review and create" },
    aiFailed: { es: "La IA no estuvo disponible; aquí tienes un set inicial según tus respuestas.", en: "AI was not available; here is a starter set for your answers." },
    joined: { es: "Ya usa la app", en: "Already uses the app" },
    notJoined: { es: "Aún no se ha unido", en: "Hasn't joined yet" },
    joinCodeHint: { es: "Comparte este código; {name} elige «Hijo/a» al registrarse.", en: "Share this code; {name} picks “Child” when signing up." },
    noJoinCode: { es: "Generar código", en: "Generate code" },
    rotationHint: { es: "Hasta que {name} se una, sus tareas van a la rotación compartida. Asígnalas desde Tareas cuando esté dentro.", en: "Until {name} joins, these chores go into the shared rotation. Assign them from Tasks once {name} is in." },
    createAccount: { es: "Crear su cuenta ahora", en: "Create the account now" },
    autoCreated: { es: "{n} tareas ya se crearon en la rotación compartida. Asígnalas a {name} desde Tareas.", en: "{n} chores were already created in the shared rotation. Assign them to {name} from Tasks." },
    email: { es: "Correo", en: "Email" },
    password: { es: "Contraseña (mínimo 8)", en: "Password (8+ characters)" },
    createAccountBtn: { es: "Crear cuenta", en: "Create account" },
    accountCreated: { es: "Cuenta creada", en: "Account created" },
    accountFailed: { es: "No se pudo crear la cuenta.", en: "Could not create the account." },
    chores: { es: "Tareas", en: "Chores" },
    rewards: { es: "Premios", en: "Rewards" },
    gigs: { es: "Chambitas (dinero)", en: "Gigs (cash)" },
    points: { es: "puntos", en: "points" },
    pesos: { es: "$ MXN", en: "$ MXN" },
    bonus: { es: "Extra", en: "Bonus" },
    exists: { es: "Ya existe: {title}", en: "Already exists: {title}" },
    difficulty: { es: ["Fácil", "Media", "Difícil"], en: ["Easy", "Medium", "Hard"] },
    create: { es: "Crear {n}", en: "Create {n}" },
    creating: { es: "Creando {i} de {n}…", en: "Creating {i} of {n}…" },
    retry: { es: "Reintentar los fallidos", en: "Retry failed" },
    createFailed: { es: "No se pudo crear. Intenta de nuevo.", en: "Could not create. Try again." },
    draftFailed: { es: "No pudimos armar el plan. Intenta de nuevo.", en: "We couldn't build the plan. Try again." },
    done: { es: "Listo: {chores} tareas, {rewards} premios, {gigs} chambitas", en: "Done: {chores} chores, {rewards} rewards, {gigs} gigs" },
    refine: { es: "Afinar con Jarvis", en: "Refine with Jarvis" },
    goHub: { es: "Ir a mi inicio", en: "Go to my hub" },
    leaveTitle: { es: "¿Salir de la configuración?", en: "Leave setup?" },
    leaveBody: { es: "Lo que ya creaste se queda; las respuestas no se guardan.", en: "What you already created stays; your answers are not saved." },
    leaveConfirm: { es: "Salir", en: "Leave" },
} as const;

export const BAND_LABELS: Record<Band, { es: string; en: string }> = {
    "3-5": { es: "3 a 5", en: "3–5" }, "6-8": { es: "6 a 8", en: "6–8" }, "9-12": { es: "9 a 12", en: "9–12" }, "13+": { es: "13+", en: "13+" },
};
export const PRIORITY_LABELS: Record<(typeof PRIORITIES)[number], { es: string; en: string }> = {
    routine: { es: "Rutinas (mañana y noche)", en: "Routines (mornings & bedtime)" },
    school: { es: "Escuela (tarea y lectura)", en: "School (homework & reading)" },
    home: { es: "Casa (orden y limpieza)", en: "Home (tidying & cleaning)" },
    kitchen: { es: "Cocina (comida y mesa)", en: "Kitchen (meals & table)" },
    pets: { es: "Mascotas", en: "Pets" },
    self_care: { es: "Cuidado personal", en: "Self-care" },
};
export const REWARD_STYLE_LABELS: Record<(typeof REWARD_STYLES)[number], { es: string; en: string }> = {
    screen_time: { es: "Tiempo de pantalla", en: "Screen time" },
    treats: { es: "Antojos", en: "Treats" },
    activities: { es: "Actividades y salidas", en: "Activities & outings" },
    privileges: { es: "Privilegios", en: "Privileges" },
    toys: { es: "Juguetes y cositas", en: "Toys & small things" },
};

export type KidRow = { key: string; name: string; band: Band | null; memberId: string | null; locked: boolean; included: boolean };
export type WizardState = { kids: KidRow[]; priorities: string[]; note: string; rewardStyles: string[]; wantsGigs: boolean };

const str = (v: unknown) => (typeof v === "string" ? v : "");

export function bandForBirthdate(iso: string, today: Date): Band {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
    if (!m) return "6-8";
    const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
    let age = today.getFullYear() - y;
    if (today.getMonth() + 1 < mo || (today.getMonth() + 1 === mo && today.getDate() < d)) age -= 1;
    if (age < 6) return "3-5";
    if (age <= 8) return "6-8";
    if (age <= 12) return "9-12";
    return "13+";
}

/** Active, approved CHILD/TEEN members → locked rows; band from a birthdate
 *  when the payload carries one (it does not today), else by role. */
export function kidRowsFromMembers(members: unknown, today: Date = new Date()): KidRow[] {
    if (!Array.isArray(members)) return [];
    const out: KidRow[] = [];
    for (const m of members as Array<Record<string, unknown>>) {
        if (!m || typeof m.id !== "string" || typeof m.name !== "string") continue;
        const role = String(m.role ?? "").toLowerCase();
        if (role !== "child" && role !== "teen") continue;
        if (m.is_active === false) continue;
        if (typeof m.approval_status === "string" && m.approval_status !== "approved") continue;
        const band: Band = typeof m.birthdate === "string" ? bandForBirthdate(m.birthdate, today) : role === "teen" ? "13+" : "6-8";
        out.push({ key: `m-${m.id}`, name: m.name, band, memberId: m.id, locked: true, included: true });
    }
    return out;
}

export function canAdvanceKids(state: WizardState): boolean {
    return state.kids.some((k) => k.included && k.name.trim().length > 0 && k.band !== null);
}

export function draftRequest(state: WizardState, lang: Lang) {
    return {
        kids: state.kids.filter((k) => k.included && k.name.trim() && k.band).map((k) => ({ name: k.name.trim(), age_band: k.band, member_id: k.memberId })),
        priorities: [...state.priorities],
        note: state.note.trim() || null,
        reward_styles: [...state.rewardStyles],
        wants_gigs: state.wantsGigs,
        lang,
    };
}

export type RowStatus = "idle" | "creating" | "done" | "error";
type RowBase = { key: string; title: string; duplicateOf: string | null; included: boolean; status: RowStatus; error: string | null };
export type ChoreRow = RowBase & { points: number; days: number[]; isBonus: boolean; description: string | null;
    /** Created while the kid had no account: it went to the shared rotation, not to her. */
    createdAuto: boolean };
export type RewardRow = RowBase & { pointsCost: number; category: string; description: string | null };
export type GigRow = RowBase & { points: number; difficulty: number; category: string };
export type KidReview = { key: string; name: string; band: Band; memberId: string | null; chores: ChoreRow[] };
export type Review = { kids: KidReview[]; rewards: RewardRow[]; gigs: GigRow[] };

const base = (key: string, o: Record<string, unknown>): RowBase | null => {
    const title = str(o.title).trim();
    if (!title) return null;
    const duplicateOf = str(o.duplicate_of) || null;
    return { key, title, duplicateOf, included: !duplicateOf, status: "idle", error: null };
};
const num = (v: unknown, d: number) => (typeof v === "number" && Number.isFinite(v) ? v : d);

export function reviewRows(draft: unknown): Review {
    const d = (draft ?? {}) as Record<string, unknown>;
    const kids: KidReview[] = [];
    (Array.isArray(d.kids) ? d.kids : []).forEach((k: Record<string, unknown>, ki: number) => {
        if (!k || typeof k.name !== "string") return;
        const chores: ChoreRow[] = [];
        (Array.isArray(k.chores) ? k.chores : []).forEach((c: Record<string, unknown>, ci: number) => {
            const b = c && base(`k${ki}c${ci}`, c);
            if (!b) return;
            chores.push({ ...b, points: num(c.points, 10), isBonus: c.is_bonus === true,
                days: Array.isArray(c.days) ? c.days.filter((x): x is number => Number.isInteger(x) && x >= 0 && x <= 6) : [],
                description: str(c.description).trim() || null, createdAuto: false });
        });
        kids.push({ key: `k${ki}`, name: k.name, band: (BANDS.includes(k.age_band as Band) ? k.age_band : "6-8") as Band,
            memberId: typeof k.member_id === "string" ? k.member_id : null, chores });
    });
    const rewards: RewardRow[] = [];
    (Array.isArray(d.rewards) ? d.rewards : []).forEach((r: Record<string, unknown>, i: number) => {
        const b = r && base(`r${i}`, r);
        if (b) rewards.push({ ...b, pointsCost: num(r.points_cost, 50), category: str(r.category) || "privileges", description: str(r.description).trim() || null });
    });
    const gigs: GigRow[] = [];
    (Array.isArray(d.gigs) ? d.gigs : []).forEach((g: Record<string, unknown>, i: number) => {
        const b = g && base(`g${i}`, g);
        if (b) gigs.push({ ...b, points: num(g.points, 20), difficulty: Math.min(3, Math.max(1, num(g.difficulty, 1))), category: str(g.category) || "other" });
    });
    return { kids, rewards, gigs };
}

/** POST /api/task-templates/ — FIXED to the kid when bound, AUTO (shared rotation) otherwise. */
export function choreBody(row: ChoreRow, memberId: string | null, lang: Lang) {
    const title = row.title.trim();
    const description = row.description && row.description.trim() ? row.description.trim() : null;
    const body: Record<string, unknown> = {
        title,
        points: Math.max(0, Math.min(1000, Math.round(Number(row.points) || 0))),
        is_bonus: row.isBonus,
        days_of_week: row.days.length ? [...row.days].sort((a, b) => a - b) : null,
        interval_days: 1,
        assignment_type: memberId ? "fixed" : "auto",
        assigned_user_ids: memberId ? [memberId] : null,
        description,
    };
    if (lang === "es") { body.title_es = title; body.description_es = description; }
    return body;
}

export function rewardBody(row: RewardRow) {
    return { title: row.title.trim(), points_cost: Math.max(1, Math.min(10000, Math.round(Number(row.pointsCost) || 1))), category: row.category, description: row.description };
}

export function gigBody(row: GigRow) {
    return { title: row.title.trim(), points: Math.max(1, Math.round(Number(row.points) || 1)), difficulty: row.difficulty, category: row.category };
}

export function registerBody(kid: { name: string; band: Band | null }, email: string, password: string) {
    return { name: kid.name.trim(), email: email.trim(), password, role: kid.band === "13+" ? "teen" : "child" };
}

export function modulesBodyWithoutGigs(current: unknown) {
    const list = Array.isArray(current) ? current.filter((m): m is string => typeof m === "string") : [...TOGGLABLE_MODULES];
    return { enabled_modules: list.filter((m) => m !== "gigs") };
}

export type Poster = (path: string, body: Record<string, unknown>) => Promise<PostResult>;
export type Counts = { chores: number; rewards: number; gigs: number };

/** One ordinary create per ticked row, chores → rewards → gigs. A failed row
 *  keeps `error`/`status = "error"` and is re-posted next time; a done row is
 *  never posted again. */
export async function createAll(review: Review, lang: Lang, post: Poster, onProgress?: (i: number, n: number) => void): Promise<Counts> {
    type Job = { row: RowBase; path: string; body: Record<string, unknown>; kind: keyof Counts; auto?: boolean };
    const jobs: Job[] = [];
    for (const kid of review.kids) for (const c of kid.chores) if (c.included && c.status !== "done") jobs.push({ row: c, path: "/api/task-templates/", body: choreBody(c, kid.memberId, lang), kind: "chores", auto: !kid.memberId });
    for (const r of review.rewards) if (r.included && r.status !== "done") jobs.push({ row: r, path: "/api/rewards/", body: rewardBody(r), kind: "rewards" });
    for (const g of review.gigs) if (g.included && g.status !== "done") jobs.push({ row: g, path: "/api/gigs/offerings", body: gigBody(g), kind: "gigs" });
    const counts: Counts = { chores: 0, rewards: 0, gigs: 0 };
    for (let i = 0; i < jobs.length; i++) {
        const job = jobs[i];
        onProgress?.(i + 1, jobs.length);
        job.row.status = "creating";
        try {
            const result = await post(job.path, job.body);
            if (result.ok) {
                job.row.status = "done"; job.row.error = null; counts[job.kind] += 1;
                if (job.kind === "chores") (job.row as ChoreRow).createdAuto = job.auto === true;
            }
            else { job.row.status = "error"; job.row.error = result.detail || SETUP_COPY.createFailed[lang]; }
        } catch {
            job.row.status = "error"; job.row.error = SETUP_COPY.createFailed[lang];
        }
    }
    return counts;
}

export function jarvisPrefill(state: WizardState, counts: Counts, lang: Lang): string {
    const kids = state.kids.filter((k) => k.included && k.name.trim()).map((k) => `${k.name.trim()} (${k.band ?? "?"})`).join(", ");
    const prio = state.priorities.join(", ") || (lang === "es" ? "sin prioridades" : "no priorities");
    const note = state.note.trim();
    const text = lang === "es"
        ? `Acabo de configurar mi familia con el asistente: ${kids}. Prioridades: ${prio}. Creé ${counts.chores} tareas, ${counts.rewards} premios y ${counts.gigs} chambitas.${note ? ` Nota: ${note}.` : ""} Ayúdame a ajustarlas — por ejemplo, revisa que los puntos sean parejos entre hermanos.`
        : `I just set up my family with the wizard: ${kids}. Priorities: ${prio}. I created ${counts.chores} chores, ${counts.rewards} rewards and ${counts.gigs} gigs.${note ? ` Note: ${note}.` : ""} Help me adjust them — for example, check the points are fair between siblings.`;
    return text.slice(0, 2000);
}
