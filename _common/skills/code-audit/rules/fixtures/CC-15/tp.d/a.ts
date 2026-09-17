export class A extends Component {
    onLoad() {
        this.node.on('click', this.h, this);
        this.schedule(this.tick, 1);
    }
    h() {}
    tick() {}
    onDestroy() {
    }
}
