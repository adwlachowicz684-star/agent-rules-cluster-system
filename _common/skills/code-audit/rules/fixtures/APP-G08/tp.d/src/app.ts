import { normalize } from './theme'
import * as theme from './theme'
import { render } from './render'

export function boot() {
  return render(normalize(theme.defaults))
}
