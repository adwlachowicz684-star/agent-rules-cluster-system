export function jitter(rng: Rng): number {
    return rng.next() * 2 - 1;
}
