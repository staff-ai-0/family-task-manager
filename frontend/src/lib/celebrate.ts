/**
 * Lightweight, dependency-free confetti burst + a short haptic buzz, used when
 * a member empties their deck (UX-C1). Both respect reduced-motion / missing
 * APIs and never throw.
 */
export function fireConfetti(): void {
    // Decoration only: it runs right after a successful save, so a canvas /
    // matchMedia failure must never surface as an error to the caller.
    try {
        if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
        if (document.getElementById("confetti-canvas")) return;
        const canvas = document.createElement("canvas");
        canvas.id = "confetti-canvas";
        canvas.style.cssText = "position:fixed;inset:0;width:100%;height:100%;pointer-events:none;z-index:9999";
        document.body.appendChild(canvas);
        const ctx = canvas.getContext("2d");
        if (!ctx) { canvas.remove(); return; }
        canvas.width = window.innerWidth;
        canvas.height = window.innerHeight;
        const colors = ["#4FB8E6", "#FFC857", "#6BCB77", "#FF6B6B", "#A78BFA"];
        const parts = Array.from({ length: 90 }, () => ({
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
                p.vy += 0.4; // gravity
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
    } catch {
        document.getElementById("confetti-canvas")?.remove();
    }
}

export function celebrate(): void {
    fireConfetti();
    try {
        if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) navigator.vibrate?.(30);
    } catch {
        // vibrate is optional (iOS Safari lacks it)
    }
}
