/**
 * Jarvis records each tool it ran as "tool_name(status)", status one of
 * ok | err | pending. Chips show a readable label instead of the raw name.
 */
const MARK: Record<string, string> = { ok: "✓", pending: "⏳" };

export function formatActionLabel(raw: string): string {
    const trimmed = raw.trim();
    const match = /^([\w.-]+)\((\w+)\)$/.exec(trimmed);
    if (!match) return trimmed.replace(/_/g, " ");
    const [, name, status] = match;
    return `${name.replace(/_/g, " ")} ${MARK[status] ?? "⚠"}`;
}
