import { useQuery } from "@tanstack/react-query";
import { useState, type ReactElement } from "react";

import { listProposals } from "../api/assistant";
import { ProposalCard } from "../components/ProposalCard";
import { Panel } from "../components/Panel";
import { RequireCampaign } from "../components/RequireCampaign";
import { PROPOSAL_STATUS_LABELS } from "../ui/styles";
import { Badge, EmptyState, LoadingBlock } from "../ui/primitives";
import type { ProposalStatus } from "../api/types";

const STATUSES: ProposalStatus[] = ["pending", "confirmed", "rejected", "conflict"];

function ProposalContent({ campaignId }: { campaignId: string }): ReactElement {
  const [status, setStatus] = useState<ProposalStatus>("pending");
  const proposals = useQuery({
    queryKey: ["proposals", campaignId, status],
    queryFn: ({ signal }) => listProposals(campaignId, status, signal),
    refetchInterval: status === "pending" ? 20_000 : false,
  });
  return (
    <div className="mx-auto max-w-[1100px] p-4 lg:p-6">
      <Panel eyebrow="DM 私密审核" title="AI 修改提案">
        <div className="flex flex-wrap gap-1.5">
          {STATUSES.map((item) => (
            <button className={`rounded-md border px-3 py-1.5 text-xs ${status === item ? "border-ember-500/60 bg-ember-500/10 text-ember-200" : "border-ink-600 text-stone-500 hover:text-stone-200"}`} key={item} onClick={() => setStatus(item)} type="button">
              {PROPOSAL_STATUS_LABELS[item]}
              {status === item && proposals.data ? <Badge tone="neutral">{proposals.data.length}</Badge> : null}
            </button>
          ))}
        </div>
      </Panel>
      <div className="mt-4 flex flex-col gap-3">
        {proposals.isLoading ? <Panel title="提案"><LoadingBlock /></Panel> : null}
        {proposals.isError ? <Panel title="提案"><p className="m-0 py-4 text-sm text-red-300">提案列表读取失败，请重试。</p></Panel> : null}
        {!proposals.isLoading && !proposals.isError && proposals.data?.length === 0 ? <Panel title="提案"><EmptyState title={`没有${PROPOSAL_STATUS_LABELS[status]}提案`} hint={status === "pending" ? "AI 不会自动写入战役数据，所有修改都会先出现在这里。" : undefined} /></Panel> : null}
        {proposals.data?.map((proposal) => <ProposalCard campaignId={campaignId} key={proposal.id} proposal={proposal} />)}
      </div>
    </div>
  );
}

export function ProposalsPage(): ReactElement {
  return <RequireCampaign>{(campaignId) => <ProposalContent campaignId={campaignId} />}</RequireCampaign>;
}
