import { _decorator, Component, resources, Prefab } from 'cc';
const { ccclass } = _decorator;

@ccclass('Loader')
export class Loader extends Component {
    private _p: Prefab | null = null;
    start() {
        resources.load('prefabs/item', (e, a) => { this._p = a; });
    }
    onDestroy() {
        if (this._p) { this._p.decRef(); this._p = null; }
    }
}
