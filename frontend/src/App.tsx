import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { configAPI } from "./services/api";
import { Layout } from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import Scan from "./pages/Scan";
import System from "./pages/System";
import Settings from "./pages/Settings";
import SetupWizard from "./pages/SetupWizard";
import NotFound from "./pages/NotFound";

const queryClient = new QueryClient();

function AppRoutes() {
  // Deduparr needs a media server, not Plex specifically
  const { data: config } = useQuery({
    queryKey: ["config"],
    queryFn: () => configAPI.getAll(),
    retry: false,
  });

  // Mirrors the backend: a server counts as configured once its credentials
  // are present, so Jellyfin on its own is enough.
  const mediaServerConfigured =
    !!config?.plex_auth_token || !!(config?.jellyfin_url && config?.jellyfin_api_key);

  return (
    <Routes>
      <Route path="/setup" element={<SetupWizard />} />
      {/*
        Two <Route> elements for "/" cannot express this: React Router picks the
        first match on equal specificity, so a later redirect route is
        unreachable. The choice has to happen inside the one route's element.
        While config is still loading, render the dashboard rather than
        flashing the wizard.
      */}
      <Route
        element={
          !mediaServerConfigured && config !== undefined ? (
            <Navigate to="/setup" replace />
          ) : (
            <Layout>
              <Dashboard />
            </Layout>
          )
        }
        path="/"
      />
      <Route
        element={
          <Layout>
            <Scan />
          </Layout>
        }
        path="/scan"
      />
      <Route
        element={
          <Layout>
            <Settings />
          </Layout>
        }
        path="/settings"
      />
      <Route
        element={
          <Layout>
            <System />
          </Layout>
        }
        path="/system"
      />
      {/* ADD ALL CUSTOM ROUTES ABOVE THE CATCH-ALL "*" ROUTE */}
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}

const App = () => {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <Toaster />
        <Sonner />
        <BrowserRouter>
          <AppRoutes />
        </BrowserRouter>
      </TooltipProvider>
    </QueryClientProvider>
  );
};

export default App;
