export function importState(base: object, importedData: object): object {
    return Object.assign({}, base, importedData);
}
