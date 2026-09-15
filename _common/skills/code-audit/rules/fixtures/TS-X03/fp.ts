export function load() {
  resources.load('prefabs/a', (err, asset) => {
    use(asset);
    asset.decRef();
  });
}
