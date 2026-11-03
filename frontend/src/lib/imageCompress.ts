/**
 * Shrink a camera photo in the browser before it is uploaded.
 *
 * An iPhone 13 mini JPEG is 3–6 MB (prod proofs run up to 11 MB). Sent raw
 * over mobile data it makes the "done" tap look frozen. 1600 px on the long
 * side at q0.8 is ~250–400 KB — still plenty for a parent to judge a bed and
 * for the AI check, which downsizes again server-side.
 *
 * Never throws and never makes things worse: any failure, or an output that is
 * not smaller, returns the ORIGINAL file so the upload still works.
 */

export const MAX_EDGE = 1600;
export const JPEG_QUALITY = 0.8;
/** Below this the file is already cheap to send — skip the re-encode. */
export const SKIP_BELOW_BYTES = 500 * 1024;

const COMPRESSIBLE = new Set(["image/jpeg", "image/png", "image/webp"]);

export function fitWithin(width: number, height: number, maxEdge: number): { width: number; height: number } {
    const longest = Math.max(width, height);
    if (longest <= maxEdge) return { width, height };
    const scale = maxEdge / longest;
    return { width: Math.round(width * scale), height: Math.round(height * scale) };
}

/** Browser primitives, injectable so the logic is testable without a DOM. */
export interface ImageDeps {
    /** Decode honoring EXIF orientation (iPhone photos are stored rotated). */
    decode(file: Blob): Promise<{ width: number; height: number; close?: () => void }>;
    /** Draw the decoded image at the target size and encode it as JPEG. */
    encode(
        image: { width: number; height: number },
        size: { width: number; height: number },
        quality: number,
    ): Promise<Blob | null>;
}

const browserDeps: ImageDeps = {
    decode: (file) => createImageBitmap(file, { imageOrientation: "from-image" }),
    encode: (image, size, quality) =>
        new Promise((resolve) => {
            const canvas = document.createElement("canvas");
            canvas.width = size.width;
            canvas.height = size.height;
            const ctx = canvas.getContext("2d");
            if (!ctx) return resolve(null);
            ctx.drawImage(image as ImageBitmap, 0, 0, size.width, size.height);
            canvas.toBlob((b) => resolve(b), "image/jpeg", quality);
        }),
};

export async function compressImage(
    file: File,
    opts: { maxEdge?: number; quality?: number } = {},
    deps: ImageDeps = browserDeps,
): Promise<File> {
    if (!COMPRESSIBLE.has(file.type) || file.size <= SKIP_BELOW_BYTES) return file;
    try {
        const bitmap = await deps.decode(file);
        try {
            const size = fitWithin(bitmap.width, bitmap.height, opts.maxEdge ?? MAX_EDGE);
            const blob = await deps.encode(bitmap, size, opts.quality ?? JPEG_QUALITY);
            if (!blob || blob.size === 0 || blob.size >= file.size) return file;
            const name = file.name.replace(/\.[^.]+$/, "") || "photo";
            return new File([blob], `${name}.jpg`, { type: "image/jpeg" });
        } finally {
            bitmap.close?.();
        }
    } catch {
        return file;
    }
}
