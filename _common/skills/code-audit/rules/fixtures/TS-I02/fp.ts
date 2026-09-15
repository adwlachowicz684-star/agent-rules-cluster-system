export class Repo {
    active(ids: string[]): string[] {
        return ids.filter((id) => id.length > 0);
    }
}
