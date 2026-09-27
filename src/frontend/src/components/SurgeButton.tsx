import { Button, Callout, Classes, PopoverNext } from "@blueprintjs/core";
import { useState } from "react";
import { api } from "../api";

// The demo's "new supply route" injection (scenario injection S1).
const INJECTION_ID = "S1";

export function SurgeButton() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const fire = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.surge(INJECTION_ID);
      setDone(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <PopoverNext
      placement="bottom-end"
      content={
        <div className="surge-pop">
          <p>
            Simulate a new cross-border supply route near the border: overdose admissions in a small
            cluster quadruple over five days. Seizures do not change.
          </p>
          {error && <Callout intent="danger">{error}</Callout>}
          <div className="surge-actions">
            <Button className={Classes.POPOVER_DISMISS} minimal text="Cancel" />
            <Button className={Classes.POPOVER_DISMISS} intent="danger" text="Inject" loading={busy} onClick={() => void fire()} />
          </div>
        </div>
      }
    >
      <Button intent="danger" icon="warning-sign" text={done ? "SURGE INJECTED" : "INJECT SURGE"} disabled={done} />
    </PopoverNext>
  );
}
