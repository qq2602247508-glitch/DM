import { useQuery } from "@tanstack/react-query";
import { useEffect, type ReactElement, type ReactNode } from "react";

import { listCampaigns } from "../api/campaigns";
import { useCurrentCampaign } from "../hooks/appContexts";
import { navigate } from "../hooks/useHashRoute";
import { Button, EmptyState, LoadingBlock } from "../ui/primitives";

/**
 * Gates a page behind having a selected campaign. Renders creation /
 * selection guidance instead of broken empty screens.
 */
export function RequireCampaign({
  children,
}: {
  children: (campaignId: string) => ReactNode;
}): ReactElement {
  const { campaignId, selectCampaign } = useCurrentCampaign();
  const campaigns = useQuery({
    queryKey: ["campaigns"],
    queryFn: ({ signal }) => listCampaigns(signal),
  });

  useEffect(() => {
    if (campaignId === null && campaigns.data && campaigns.data.length > 0) {
      selectCampaign(campaigns.data[0].id);
    }
  }, [campaignId, campaigns.data, selectCampaign]);

  if (campaigns.isLoading) {
    return <LoadingBlock />;
  }

  if (campaigns.data !== undefined && campaigns.data.length === 0) {
    return (
      <div className="p-6">
        <EmptyState
          action={
            <Button icon="plus" onClick={() => navigate("/campaigns")} variant="primary">
              创建第一个战役
            </Button>
          }
          hint="战役是角色、NPC、任务、线索与战斗的容器。创建后即可使用主控制台与 AI 助手。"
          icon="scroll"
          title="还没有任何战役"
        />
      </div>
    );
  }

  if (campaignId === null) {
    return (
      <div className="p-6">
        <EmptyState
          action={
            <Button onClick={() => navigate("/campaigns")} variant="ghost">
              前往战役管理
            </Button>
          }
          hint="使用顶部下拉框切换当前战役，或在战役管理中新建。"
          icon="scroll"
          title="尚未选择战役"
        />
      </div>
    );
  }

  return <>{children(campaignId)}</>;
}
