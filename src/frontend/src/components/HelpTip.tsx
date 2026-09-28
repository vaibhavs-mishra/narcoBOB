import { Tooltip } from "@blueprintjs/core";
import type { ReactNode } from "react";
import { HELP, type HelpId } from "../help";
import { useStore } from "../store";

/** In help mode, a small "?" marker with an explanation; otherwise just the children. */
export function HelpTip({ id, children, corner = false }: { id: HelpId; children?: ReactNode; corner?: boolean }) {
  const on = useStore((s) => s.helpMode);
  if (!on) return <>{children}</>;
  const marker = (
    <Tooltip content={<div className="help-text">{HELP[id]}</div>} placement="bottom" hoverOpenDelay={0}>
      <button type="button" className={corner ? "help-marker help-corner" : "help-marker"} aria-label={`Help: ${id}`}>
        ?
      </button>
    </Tooltip>
  );
  return (
    <span className={corner ? "help-anchor help-anchor-block" : "help-anchor"}>
      {children}
      {marker}
    </span>
  );
}
