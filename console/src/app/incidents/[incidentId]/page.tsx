import { Suspense } from "react";

import { IncidentDetail } from "@/components/incident-detail";

export default async function IncidentDetailPage(
  props: PageProps<"/incidents/[incidentId]">,
) {
  const { incidentId } = await props.params;
  return (
    <Suspense
      fallback={
        <p aria-busy="true" role="status">
          Loading authorized incident details…
        </p>
      }
    >
      <IncidentDetail incidentId={incidentId} />
    </Suspense>
  );
}
