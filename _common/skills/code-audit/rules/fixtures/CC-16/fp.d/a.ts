export class A extends Component {
    private _n: Node | null = null;
    onLoad() {
        this._n = find('Canvas/Node');
    }
    update(dt: number) {
    }
}
