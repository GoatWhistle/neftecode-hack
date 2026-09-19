import { useEffect, useState } from "react";
import { STAGES } from "./stages";

export function useActiveStage(enabled: boolean): string {
  const [active, setActive] = useState<string>("config");

  useEffect(() => {
    if (!enabled) {
      setActive("config");
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
        if (visible) setActive(visible.target.id);
      },
      { rootMargin: "-20% 0px -60% 0px", threshold: 0 }
    );

    const ids = ["config", ...STAGES.map((stage) => stage.id)];
    const attach = (): void => {
      for (const id of ids) {
        const node = document.getElementById(id);
        if (node) observer.observe(node);
      }
    };
    attach();
    const retry = window.setTimeout(attach, 600);

    return () => {
      window.clearTimeout(retry);
      observer.disconnect();
    };
  }, [enabled]);

  return active;
}
