import { afterEach, describe, expect, it, vi } from "vitest";

import { FetchTimeoutError, fetchWithTimeout } from "../src/lib/fetchTimeout";
import { compressImage, fitWithin, type ImageDeps } from "../src/lib/imageCompress";

const file = (bytes: number, type = "image/jpeg", name = "IMG_0001.jpeg") =>
    new File([new Uint8Array(bytes)], name, { type });

const fakeDeps = (over: Partial<ImageDeps> = {}): ImageDeps & { closed: boolean; sizes: any[] } => {
    const state = { closed: false, sizes: [] as any[] };
    return Object.assign(state, {
        decode: async () => ({ width: 4032, height: 3024, close: () => void (state.closed = true) }),
        encode: async (_i: any, size: any) => {
            state.sizes.push(size);
            return new Blob([new Uint8Array(300_000)], { type: "image/jpeg" });
        },
        ...over,
    });
};

describe("fitWithin", () => {
    it("scales the long edge down and keeps the aspect ratio", () => {
        expect(fitWithin(4032, 3024, 1600)).toEqual({ width: 1600, height: 1200 });
        expect(fitWithin(3024, 4032, 1600)).toEqual({ width: 1200, height: 1600 });
    });
    it("never upscales", () => {
        expect(fitWithin(800, 600, 1600)).toEqual({ width: 800, height: 600 });
    });
});

describe("compressImage", () => {
    it("re-encodes a big camera photo as a smaller jpeg at the capped size", async () => {
        const deps = fakeDeps();
        const out = await compressImage(file(4_500_000), {}, deps);
        expect(out.size).toBe(300_000);
        expect(out.type).toBe("image/jpeg");
        expect(out.name).toBe("IMG_0001.jpg");
        expect(deps.sizes[0]).toEqual({ width: 1600, height: 1200 });
        expect(deps.closed).toBe(true);
    });

    it("leaves a small file alone without decoding it", async () => {
        const decode = vi.fn();
        const f = file(200_000);
        expect(await compressImage(f, {}, fakeDeps({ decode }))).toBe(f);
        expect(decode).not.toHaveBeenCalled();
    });

    it("passes through types it cannot shrink", async () => {
        const f = file(4_000_000, "image/heic", "a.heic");
        expect(await compressImage(f, {}, fakeDeps())).toBe(f);
    });

    it("falls back to the original when decoding throws", async () => {
        const f = file(4_000_000);
        const out = await compressImage(f, {}, fakeDeps({ decode: async () => { throw new Error("boom"); } }));
        expect(out).toBe(f);
    });

    it("falls back to the original when encoding yields nothing", async () => {
        const f = file(4_000_000);
        expect(await compressImage(f, {}, fakeDeps({ encode: async () => null }))).toBe(f);
    });

    it("falls back to the original when the re-encode is not smaller", async () => {
        const f = file(600_000);
        const bigger = fakeDeps({ encode: async () => new Blob([new Uint8Array(900_000)]) });
        expect(await compressImage(f, {}, bigger)).toBe(f);
    });
});

describe("fetchWithTimeout", () => {
    afterEach(() => {
        vi.useRealTimers();
        vi.unstubAllGlobals();
    });

    it("returns the response when the server answers in time", async () => {
        vi.stubGlobal("fetch", vi.fn(async () => new Response("ok")));
        const r = await fetchWithTimeout("/x", undefined, 1000);
        expect(await r.text()).toBe("ok");
    });

    it("aborts a stalled request and rejects with FetchTimeoutError", async () => {
        vi.useFakeTimers();
        vi.stubGlobal(
            "fetch",
            vi.fn(
                (_u: unknown, init: RequestInit) =>
                    new Promise((_res, rej) => {
                        init.signal!.addEventListener("abort", () => rej(new DOMException("aborted", "AbortError")));
                    }),
            ),
        );
        const p = fetchWithTimeout("/x", undefined, 5000);
        const assertion = expect(p).rejects.toBeInstanceOf(FetchTimeoutError);
        await vi.advanceTimersByTimeAsync(5001);
        await assertion;
    });

    it("lets a plain network failure through unchanged", async () => {
        vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
        await expect(fetchWithTimeout("/x", undefined, 1000)).rejects.toBeInstanceOf(TypeError);
    });
});
