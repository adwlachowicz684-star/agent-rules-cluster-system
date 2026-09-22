import { _decorator, Component, Mask } from 'cc';
const { ccclass } = _decorator;

@ccclass('Panel')
export class Panel extends Component {
    start() {
        const m = this.node.addComponent(Mask);
    }
}
