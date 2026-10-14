import { Suspense } from "react";

import { ApprovalList } from "@/components/approval-list";

export default function ApprovalsPage() {
  return (
    <Suspense fallback={<p aria-busy="true">Loading authorized approvals…</p>}>
      <ApprovalList />
    </Suspense>
  );
}
