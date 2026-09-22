const buckets = new Map();
export function remove(k: string, id: string)
{
    if (buckets.get(k).size === 0) buckets.delete(k);
}
