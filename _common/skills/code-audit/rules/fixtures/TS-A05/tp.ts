export function makeSeed(opts: { seed: number }): number {
    return opts.seed >>> 0;
}
