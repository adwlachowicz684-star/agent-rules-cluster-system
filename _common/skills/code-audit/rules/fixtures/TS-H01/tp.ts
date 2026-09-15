export class Stats {
    value = 0;

    setStat(v: number): void {
        if (!Number.isFinite(v)) throw new Error('bad');
        this.value = v;
    }

    addStat(v: number): void {
        this.value += v;
    }
}
