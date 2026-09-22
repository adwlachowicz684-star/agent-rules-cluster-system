export function withDefaults(opts: Partial<Opts>): Opts {
    return Object.assign({}, defaults, opts);
}
