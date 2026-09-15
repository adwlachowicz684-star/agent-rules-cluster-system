export class Repo {
    get(id: string): Item | null {
        return null;
    }

    active(ids: string[]): Item[] {
        return ids.filter((id) => this.get(id) !== null) as Item[];
    }
}
