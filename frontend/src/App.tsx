import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Layout } from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import Scan from "./pages/Scan";
import System from "./pages/System";
import Settings from "./pages/Settings";
import SetupWizard from "./pages/SetupWizard";
import NotFound from "./pages/NotFound";

const queryClient = new QueryClient();

function AppRoutes() {
  // Check if Plex is configured
  const { data: config } = useQuery({
    queryKey: ["config"],
    queryFn: async () => {
      const response = await fetch("/api/config");
      if (!response.ok) return null;
      return response.json();
    },
    retry: false,
  });

  const plexConfigured = !!config?.plex_auth_token;

  return (
    <Routes>
      <Route path="/setup" element={<SetupWizard />} />
      <Route
        element={
          <Layout>
            <Dashboard />
          </Layout>
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
      {/* Redirect to setup if not configured */}
      {!plexConfigured && config !== undefined && (
        <Route path="/" element={<Navigate to="/setup" replace />} />
      )}
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
