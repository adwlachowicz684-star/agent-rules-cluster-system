export function makeUrl(blob: Blob): string {
    return URL.createObjectURL(blob);
}
