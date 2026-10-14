import { ApprovalDetail } from "@/components/approval-detail";

export default async function ApprovalPage({
  params,
}: Readonly<{ params: Promise<{ approvalId: string }> }>) {
  const { approvalId } = await params;
  return <ApprovalDetail approvalId={approvalId} />;
}
