import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactElement } from "react";

import { isApiError } from "../api/client";
import { confirmProposal, rejectProposal } from "../api/assistant";
import { getProposalEntity } from "../api/entities";
import type { StateChangeProposal } from "../api/types";
import { formatDateTime, formatValue } from "../ui/format";
import { Icon } from "../ui/icons";
import { Badge, Button, ErrorState } from "../ui/primitives";
import {
  ENTITY_TYPE_LABELS,
  FIELD_LABELS,
  OPERATION_LABELS,
  PROPOSAL_STATUS_LABELS,
  PROPOSAL_STATUS_TONES,
} from "../ui/styles";
import { AiTag, ConfirmDialog } from "../ui/widgets";
import { useToast } from "../hooks/toastContext";

const OPERATION_TONES = { create: "ok", update: "warn", delete: "danger" } as const;

function fieldLabel(field: string): string {
  return FIELD_LABELS[field] ?? field;
}

/**
 * Before/after comparison for a proposal. `current` is the live entity fetched
 * from the campaign API (undefined = still loading, null = already missing).
 */
function DiffTable({
  proposal,
  current,
}: {
  proposal: StateChangeProposal;
  current: Record<string, unknown> | null | undefined;
}): ReactElement {
  const fields = Object.keys(proposal.payload);

  if (proposal.operation === "create") {
    return (
      <dl className="m-0 divide-y divide-ink-700/60">
        {fields.map((field) => (
          <div className="grid grid-cols-[7rem_1fr] gap-3 py-1.5" key={field}>
            <dt className="text-xs text-stone-500">{fieldLabel(field)}</dt>
            <dd className="m-0 break-words text-sm text-emerald-200/90">
              {formatValue(proposal.payload[field])}
            </dd>
          </div>
        ))}
      </dl>
    );
  }

  if (proposal.operation === "delete") {
    return (
      <p className="m-0 rounded border border-red-900/60 bg-red-950/30 px-3 py-2 text-xs leading-5 text-red-200/90">
        确认后此{ENTITY_TYPE_LABELS[proposal.entity_type]}将被永久删除。
        {current === null
          ? "（该实体当前已不存在，可能已被删除。）"
          : current === undefined
            ? "（正在加载当前状态…）"
            : `当前名称：${formatValue(current.name ?? current.title)}`}
      </p>
    );
  }

  // update: field-by-field before/after
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="text-left text-2xs uppercase tracking-wider text-stone-600">
            <th className="pb-1.5 pr-3 font-medium">字段</th>
            <th className="pb-1.5 pr-3 font-medium">当前值</th>
            <th className="pb-1.5 font-medium">提案值</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-ink-700/60">
          {fields.map((field) => {
            const before = current?.[field];
            const after = proposal.payload[field];
            const changed = current !== undefined && formatValue(before) !== formatValue(after);
            return (
              <tr key={field}>
                <td className="py-1.5 pr-3 align-top text-xs text-stone-500">{fieldLabel(field)}</td>
                <td className="py-1.5 pr-3 align-top text-stone-400">
                  {current === undefined ? "加载中…" : current === null ? "（不存在）" : formatValue(before)}
                </td>
                <td
                  className={`py-1.5 align-top ${
                    changed ? "font-medium text-amber-200" : "text-parchment-100"
                  }`}
                >
                  {formatValue(after)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function ProposalCard({
  proposal,
  campaignId,
}: {
  proposal: StateChangeProposal;
  campaignId: string;
}): ReactElement {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [decisionError, setDecisionError] = useState<unknown>(null);
  const isPending = proposal.status === "pending";

  const currentEntity = useQuery({
    queryKey: ["proposal-entity", campaignId, proposal.entity_type, proposal.entity_id],
    queryFn: ({ signal }) =>
      getProposalEntity(campaignId, proposal.entity_type, proposal.entity_id ?? "", signal),
    enabled: proposal.entity_id !== null && proposal.operation !== "create",
    retry: (failureCount, error) => !isApiError(error, 404) && failureCount < 2,
  });

  const entityMissing = isApiError(currentEntity.error, 404);

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["proposals", campaignId] });
    void queryClient.invalidateQueries({ queryKey: ["campaign-state", campaignId] });
    void queryClient.invalidateQueries({ queryKey: ["campaigns"] });
    for (const key of ["characters", "npcs", "quests", "events", "locations"]) {
      void queryClient.invalidateQueries({ queryKey: [key, campaignId] });
    }
  };

  const decide = useMutation({
    mutationFn: (action: "confirm" | "reject") =>
      action === "confirm"
        ? confirmProposal(campaignId, proposal.id)
        : rejectProposal(campaignId, proposal.id),
    onSuccess: (_data, action) => {
      setDecisionError(null);
      invalidate();
      showToast(action === "confirm" ? "提案已确认并写入" : "提案已拒绝");
    },
    onError: (error) => {
      setDecisionError(error);
      showToast(isApiError(error, 409) ? "提案发生版本冲突" : "提案处理失败", "error");
      // A 409 means the entity moved on: refresh the underlying data so the DM
      // sees the current state before deciding again.
      if (isApiError(error, 409)) {
        invalidate();
      }
    },
  });

  const busy = decide.isPending;

  return (
    <article className="rounded-lg border border-ink-700 bg-ink-900/90">
      <header className="flex flex-wrap items-center gap-2 border-b border-ink-700/70 px-4 py-2.5">
        <Badge tone={OPERATION_TONES[proposal.operation]}>
          {OPERATION_LABELS[proposal.operation]}
        </Badge>
        <Badge tone="ember">{ENTITY_TYPE_LABELS[proposal.entity_type]}</Badge>
        <Badge tone={PROPOSAL_STATUS_TONES[proposal.status]}>
          {PROPOSAL_STATUS_LABELS[proposal.status]}
        </Badge>
        <span className="ml-auto text-2xs text-stone-600">
          {formatDateTime(proposal.created_at)} · 模型 {proposal.created_by_model}
        </span>
      </header>

      <div className="flex flex-col gap-3 px-4 py-3">
        <div className="rounded-md border border-violet-900/50 bg-violet-950/20 px-3 py-2">
          <AiTag>AI 修改理由</AiTag>
          <p className="prose-block mb-0 mt-1.5 text-sm text-parchment-100">{proposal.reason}</p>
        </div>

        <DiffTable
          proposal={proposal}
          current={
            proposal.operation === "create"
              ? undefined
              : entityMissing
                ? null
                : currentEntity.data
          }
        />

        {proposal.expected_version !== null ? (
          <p className="m-0 text-2xs text-stone-600">
            基于版本 v{proposal.expected_version} 提出
            {currentEntity.data?.version !== undefined &&
            typeof currentEntity.data.version === "number" &&
            currentEntity.data.version !== proposal.expected_version
              ? `，当前已是 v${currentEntity.data.version}（确认将产生冲突）`
              : ""}
          </p>
        ) : null}

        {decisionError !== null ? (
          <ErrorState
            error={decisionError}
            onRetry={
              isApiError(decisionError, 409)
                ? () => {
                    setDecisionError(null);
                    void currentEntity.refetch();
                    invalidate();
                  }
                : undefined
            }
          />
        ) : null}

        {isPending ? (
          <div className="flex items-center justify-end gap-2 border-t border-ink-700/60 pt-3">
            <Button
              disabled={busy}
              onClick={() => decide.mutate("reject")}
              size="sm"
              variant="ghost"
            >
              拒绝
            </Button>
            <Button
              icon="check"
              loading={busy}
              onClick={() => {
                if (proposal.operation === "delete") {
                  setConfirmingDelete(true);
                } else {
                  decide.mutate("confirm");
                }
              }}
              size="sm"
              variant="primary"
            >
              确认写入
            </Button>
          </div>
        ) : (
          <p className="m-0 flex items-center gap-1.5 border-t border-ink-700/60 pt-3 text-2xs text-stone-600">
            <Icon name="check" size={12} />
            已于 {formatDateTime(proposal.decided_at)} 处理
          </p>
        )}
      </div>

      <ConfirmDialog
        body={
          <span>
            此提案要求<span className="font-medium text-red-300">删除</span>一个
            {ENTITY_TYPE_LABELS[proposal.entity_type]}。确认后无法撤销，确定写入吗？
          </span>
        }
        confirmLabel="确认删除"
        loading={decide.isPending}
        onCancel={() => setConfirmingDelete(false)}
        onConfirm={() => {
          setConfirmingDelete(false);
          decide.mutate("confirm");
        }}
        open={confirmingDelete}
        title="确认删除提案"
      />
    </article>
  );
}
