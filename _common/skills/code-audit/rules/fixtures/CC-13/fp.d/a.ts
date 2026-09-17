import { _decorator, Component, tween, Tween, Node } from 'cc';
const { ccclass } = _decorator;

@ccclass('Spinner')
export class Spinner extends Component {
    private _t: Tween<Node> | null = null;
    start() {
        this._t = tween(this.node).repeatForever(tween().to(1, {})).start();
    }
    onDestroy() {
        if (this._t) { this._t.stop(); this._t = null; }
    }
}
