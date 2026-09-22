import { normalize, defaults } from './theme'
import { render } from './render'

export function boot() {
  return render(normalize(defaults))
}
