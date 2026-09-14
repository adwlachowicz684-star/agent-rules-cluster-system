const buckets = new Map();
export function remove(k: string, id: string)
{
    buckets.delete(k);
}
