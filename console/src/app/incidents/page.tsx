import { Suspense } from "react";

import { IncidentList } from "@/components/incident-list";

export default function IncidentsPage() {
  return (
    <Suspense
      fallback={
        <p aria-busy="true" role="status">
          Loading authorized incidents…
        </p>
      }
    >
      <IncidentList />
    </Suspense>
  );
}
