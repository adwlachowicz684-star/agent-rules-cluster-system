export class A extends Component {
    onLoad() {
        this.label.cacheMode = Label.CacheMode.CHAR;
        this.label.string = 'x';
    }
}
