import { useEffect, useState } from "react";

const query = "(orientation: landscape) and (min-width: 960px)";

/** True on a tablet held sideways (or a desktop window); false in portrait / narrow. */
export function useLandscape(): boolean {
  const [on, setOn] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const mq = window.matchMedia(query);
    const f = () => setOn(mq.matches);
    mq.addEventListener("change", f);
    return () => mq.removeEventListener("change", f);
  }, []);
  return on;
}
