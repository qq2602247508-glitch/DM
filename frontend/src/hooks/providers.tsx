import {
  useCallback,
  useMemo,
  useState,
  type PropsWithChildren,
  type ReactElement,
} from "react";

import {
  AssistantPrefillContext,
  CampaignContext,
  persistCampaignId,
  readStoredCampaignId,
} from "./appContexts";

export function CampaignProvider({ children }: PropsWithChildren): ReactElement {
  const [campaignId, setCampaignId] = useState<string | null>(readStoredCampaignId);

  const selectCampaign = useCallback((id: string | null) => {
    setCampaignId(id);
    persistCampaignId(id);
  }, []);

  const value = useMemo(
    () => ({ campaignId, selectCampaign }),
    [campaignId, selectCampaign],
  );

  return <CampaignContext.Provider value={value}>{children}</CampaignContext.Provider>;
}

export function AssistantPrefillProvider({ children }: PropsWithChildren): ReactElement {
  const [prefill, setPrefillState] = useState<string | null>(null);

  const setPrefill = useCallback((text: string) => setPrefillState(text), []);
  const clearPrefill = useCallback(() => setPrefillState(null), []);

  const value = useMemo(
    () => ({ prefill, setPrefill, clearPrefill }),
    [prefill, setPrefill, clearPrefill],
  );

  return (
    <AssistantPrefillContext.Provider value={value}>
      {children}
    </AssistantPrefillContext.Provider>
  );
}
