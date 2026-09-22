import { invoke } from '@tauri-apps/api/tauri';

export async function read(): Promise<string> {
    return invoke('read_file');
}
