export class A extends Component {
    onLoad() {
        this.node.on('click', this.h, this);
    }
    h() {}
    onDestroy() {
        this.node.off('click', this.h, this);
    }
}
