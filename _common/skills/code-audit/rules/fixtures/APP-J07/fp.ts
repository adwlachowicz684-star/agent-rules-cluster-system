export async function read(bridge: Bridge): Promise<string> {
    return bridge.call('readFile');
}
