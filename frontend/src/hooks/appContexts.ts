import { createContext, useContext } from "react";

export const CAMPAIGN_STORAGE_KEY = "dnd.currentCampaignId";

export type CampaignContextValue = {
  campaignId: string | null;
  selectCampaign: (id: string | null) => void;
};

export const CampaignContext = createContext<CampaignContextValue | null>(null);

export function readStoredCampaignId(): string | null {
  try {
    return window.localStorage.getItem(CAMPAIGN_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function persistCampaignId(id: string | null): void {
  try {
    if (id === null) {
      window.localStorage.removeItem(CAMPAIGN_STORAGE_KEY);
    } else {
      window.localStorage.setItem(CAMPAIGN_STORAGE_KEY, id);
    }
  } catch {
    // localStorage may be unavailable; selection still works in memory.
  }
}

export function useCurrentCampaign(): CampaignContextValue {
  const context = useContext(CampaignContext);
  if (context === null) {
    throw new Error("useCurrentCampaign must be used inside CampaignProvider");
  }
  return context;
}

// ---------------------------------------------------------------------------
// Assistant prefill: lets other pages (e.g. rules search) hand a drafted
// prompt to the assistant page without coupling the components.
// ---------------------------------------------------------------------------

export type AssistantPrefillContextValue = {
  prefill: string | null;
  setPrefill: (text: string) => void;
  clearPrefill: () => void;
};

export const AssistantPrefillContext = createContext<AssistantPrefillContextValue | null>(null);

export function useAssistantPrefill(): AssistantPrefillContextValue {
  const context = useContext(AssistantPrefillContext);
  if (context === null) {
    throw new Error("useAssistantPrefill must be used inside AssistantPrefillProvider");
  }
  return context;
}
