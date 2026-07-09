/**
 * Dependency-free celebration effects for the pet quest/evolution loop.
 * All effects respect prefers-reduced-motion (they no-op when it's set).
 */

function reduced(): boolean {
    return typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** Float a small emoji up-and-out from the centre of `anchor` (a care/quest reward cue). */
export function petHeart(anchor: Element, emoji = "❤️"): void {
    if (reduced()) return;
    const rect = anchor.getBoundingClientRect();
    const el = document.createElement("div");
    el.textContent = emoji;
    el.style.cssText = [
        "position:fixed",
        `left:${rect.left + rect.width / 2}px`,
        `top:${rect.top + rect.height / 2}px`,
        "transform:translate(-50%,-50%)",
        "font-size:28px",
        "pointer-events:none",
        "z-index:9999",
        "will-change:transform,opacity",
    ].join(";");
    document.body.appendChild(el);
    const dx = (Math.random() - 0.5) * 60;
    el.animate(
        [
            { transform: "translate(-50%,-50%) scale(0.6)", opacity: 1 },
            { transform: `translate(calc(-50% + ${dx}px), -140%) scale(1.4)`, opacity: 0 },
        ],
        { duration: 900, easing: "ease-out" },
    ).onfinish = () => el.remove();
}

/** A one-shot confetti burst from the upper third of the viewport. */
export function celebrate(): void {
    if (reduced()) return;
    if (document.getElementById("pet-confetti-canvas")) return;
    const canvas = document.createElement("canvas");
    canvas.id = "pet-confetti-canvas";
    canvas.style.cssText = "position:fixed;inset:0;width:100%;height:100%;pointer-events:none;z-index:9998";
    document.body.appendChild(canvas);
    const ctx = canvas.getContext("2d");
    if (!ctx) { canvas.remove(); return; }
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
    const colors = ["#4FB8E6", "#FFC857", "#5DD4A8", "#FF8A65", "#A78BFA"];
    const N = 90;
    const parts = Array.from({ length: N }, () => ({
        x: canvas.width / 2,
        y: canvas.height / 3,
        vx: (Math.random() - 0.5) * 14,
        vy: Math.random() * -15 - 4,
        size: Math.random() * 7 + 4,
        color: colors[Math.floor(Math.random() * colors.length)],
        rot: Math.random() * Math.PI,
        vr: (Math.random() - 0.5) * 0.3,
    }));
    let frame = 0;
    const tick = () => {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        parts.forEach((p) => {
            p.vy += 0.4;
            p.x += p.vx; p.y += p.vy; p.rot += p.vr;
            ctx.save();
            ctx.translate(p.x, p.y); ctx.rotate(p.rot);
            ctx.fillStyle = p.color;
            ctx.fillRect(-p.size / 2, -p.size / 2, p.size, p.size);
            ctx.restore();
        });
        frame++;
        if (frame < 110) requestAnimationFrame(tick);
        else canvas.remove();
    };
    requestAnimationFrame(tick);
}
