import { rng } from './rng';

export function makeSeed(opts: { seed: number }): number {
    if (!Number.isFinite(opts.seed)) throw new Error('bad seed');
    return rng.seed(opts.seed);
}
