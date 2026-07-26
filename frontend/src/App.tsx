import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactElement } from "react";

import { AppShell } from "./components/AppShell";
import { useHashRoute } from "./hooks/useHashRoute";
import { AssistantPrefillProvider, CampaignProvider } from "./hooks/providers";
import { DashboardPage } from "./pages/DashboardPage";
import { AssistantPage } from "./pages/AssistantPage";
import { RulesPage } from "./pages/RulesPage";
import { ProposalsPage } from "./pages/ProposalsPage";
import { ManagementPage } from "./pages/ManagementPage";
import { CombatPage } from "./pages/CombatPage";
import { StoryManagementPage } from "./pages/StoryManagementPage";
import { ToastProvider } from "./components/ToastProvider";
import { SettingsPage } from "./pages/SettingsPage";
import { NpcPage } from "./pages/NpcPage";
import { LocationsPage } from "./pages/LocationsPage";
import { InventoryPage } from "./pages/InventoryPage";
import { ScenesPage } from "./pages/ScenesPage";
import { GameTablePage } from "./pages/GameTablePage";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      retry: 1,
    },
  },
});

function RoutedPage(): ReactElement {
  const route = useHashRoute();
  switch (route) {
    case "/assistant":
      return <AssistantPage />;
    case "/game-table":
      return <GameTablePage />;
    case "/rules":
      return <RulesPage />;
    case "/proposals":
      return <ProposalsPage />;
    case "/campaigns":
      return <ManagementPage kind="campaigns" />;
    case "/characters":
      return <ManagementPage kind="characters" />;
    case "/npcs":
      return <NpcPage />;
    case "/locations":
      return <LocationsPage />;
    case "/inventory":
      return <InventoryPage />;
    case "/scenes":
      return <ScenesPage />;
    case "/events":
      return <ManagementPage kind="events" />;
    case "/quests":
      return <StoryManagementPage />;
    case "/combat":
      return <CombatPage />;
    case "/settings":
      return <SettingsPage />;
    default:
      return <DashboardPage />;
  }
}

export function App(): ReactElement {
  return (
    <QueryClientProvider client={queryClient}>
      <CampaignProvider>
        <ToastProvider>
          <AssistantPrefillProvider>
            <AppShell>
              <RoutedPage />
            </AppShell>
          </AssistantPrefillProvider>
        </ToastProvider>
      </CampaignProvider>
    </QueryClientProvider>
  );
}
