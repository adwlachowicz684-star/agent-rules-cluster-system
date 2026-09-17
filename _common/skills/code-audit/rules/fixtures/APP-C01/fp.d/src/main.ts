import { usedHelper } from "./feat";
import { otherThing } from "./other";

export function boot() {
  return usedHelper() + otherThing();
}
