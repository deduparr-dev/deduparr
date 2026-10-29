import { useState, useRef, useTransition } from "react";
import { useNavigate } from "react-router-dom";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Loader2, Check, X, Film, Tv, Download, AlertCircle, Server } from "lucide-react";
import {
  MEDIA_SERVER_NAMES,
  setupAPI,
  type MediaLibrary,
  type ServiceTestResponse,
} from "@/services/api";
import { useQueryClient } from "@tanstack/react-query";

interface ConnectionTestResult {
  success: boolean;
  error?: string;
  version?: string;
  server_name?: string;
  username?: string;
  email?: string;
}

interface SelectedLibrary {
  /** "plex" or "jellyfin": the selection is per server, not a shared name */
  server: string;
  title: string;
}

type WizardStep =
  | "welcome"
  | "media-server"
  | "plex-auth"
  | "plex-server"
  | "jellyfin"
  | "libraries"
  | "required-services"
  | "complete";

/** Which media servers the user chose to set up. At least one is required. */
interface ServerChoice {
  plex: boolean;
  jellyfin: boolean;
}

/** The steps this run of the wizard will walk, given what was chosen. */
function stepsFor(choice: ServerChoice): WizardStep[] {
  return [
    "media-server",
    ...(choice.plex ? (["plex-auth", "plex-server"] as WizardStep[]) : []),
    ...(choice.jellyfin ? (["jellyfin"] as WizardStep[]) : []),
    "libraries",
    "required-services",
  ];
}

function ProgressIndicator({
  currentStep,
  choice,
}: {
  currentStep: WizardStep;
  choice: ServerChoice;
}) {
  const steps = stepsFor(choice);
  const currentIndex = steps.indexOf(currentStep);

  if (currentStep === "welcome" || currentStep === "complete") return null;

  return (
    <div data-testid="wizard-progress" className="mb-8 flex items-center justify-center gap-2">
      {steps.map((step, index) => (
        <div key={step} className="flex items-center gap-2">
          <div
            className={`w-3 h-3 rounded-full transition-colors ${
              index <= currentIndex ? "bg-primary" : "bg-border"
            }`}
          />
          {index < steps.length - 1 && <div className="w-8 h-1 bg-border rounded" />}
        </div>
      ))}
    </div>
  );
}

function TestResultDisplay({ result }: { result?: ConnectionTestResult }) {
  if (!result) return null;

  return (
    <div
      className={`mt-3 p-3 rounded-lg border flex items-start gap-2 ${
        result.success ? "bg-card border-border" : "bg-destructive-light border-destructive-border"
      }`}
    >
      {result.success ? (
        <Check className="w-4 h-4 text-primary flex-shrink-0 mt-0.5" />
      ) : (
        <X className="w-4 h-4 text-destructive flex-shrink-0 mt-0.5" />
      )}
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium">
          {result.success ? "Connection successful" : "Connection failed"}
        </p>
        {result.error && <p className="text-xs text-muted-foreground mt-1">{result.error}</p>}
        {result.username && (
          <p className="text-xs text-muted-foreground mt-1">User: {result.username}</p>
        )}
        {result.email && (
          <p className="text-xs text-muted-foreground mt-1">Email: {result.email}</p>
        )}
        {result.server_name && (
          <p className="text-xs text-muted-foreground mt-1">Server: {result.server_name}</p>
        )}
        {result.version && (
          <p className="text-xs text-muted-foreground mt-1">Version: {result.version}</p>
        )}
      </div>
    </div>
  );
}

export default function SetupWizard() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [currentStep, setCurrentStep] = useState<WizardStep>("welcome");
  const [isPending, startTransition] = useTransition();
  const [isLoadingLibraries, startLibrariesTransition] = useTransition();

  // Nothing is pre-selected: Deduparr does not assume which media server the
  // user runs, and either one on its own is enough.
  const [choice, setChoice] = useState<ServerChoice>({ plex: false, jellyfin: false });

  // Jellyfin state
  const [jellyfinUrl, setJellyfinUrl] = useState<string>("");
  const [jellyfinApiKey, setJellyfinApiKey] = useState<string>("");

  // Plex OAuth state
  const [plexAuthToken, setPlexAuthToken] = useState<string>("");
  const [plexServerName, setPlexServerName] = useState<string>("");
  const [libraries, setLibraries] = useState<MediaLibrary[]>([]);
  const [selectedLibraries, setSelectedLibraries] = useState<SelectedLibrary[]>([]);
  const [pinCode, setPinCode] = useState<string>("");
  const plexAuthWindowRef = useRef<Window | null>(null);

  // Services state
  const [radarrUrl, setRadarrUrl] = useState("");
  const [radarrApiKey, setRadarrApiKey] = useState("");
  const [sonarrUrl, setSonarrUrl] = useState("");
  const [sonarrApiKey, setSonarrApiKey] = useState("");
  const [qbitUrl, setQbitUrl] = useState("");
  const [qbitUsername, setQbitUsername] = useState("");
  const [qbitPassword, setQbitPassword] = useState("");

  // UI state
  const [isPolling, setIsPolling] = useState(false);
  const [error, setError] = useState<string>("");
  const [testResults, setTestResults] = useState<Record<string, ConnectionTestResult>>({});

  /** A result only holds for the details it was tested with. */
  function forgetTest(service: string) {
    setTestResults((prev) => {
      const next = { ...prev };
      delete next[service];
      return next;
    });
  }

  function closeAuthWindow() {
    if (plexAuthWindowRef.current && !plexAuthWindowRef.current.closed) {
      plexAuthWindowRef.current.close();
      plexAuthWindowRef.current = null;
    }
  }

  function handleCancelAuth() {
    setIsPolling(false);
    setPinCode("");
    setError("");
    closeAuthWindow();
    setCurrentStep("welcome");
  }

  function handleGetStarted() {
    setError("");
    setCurrentStep("media-server");
  }

  /** Continue from the server choice into the first server's own step. */
  function handleServerChoice() {
    setError("");
    if (choice.plex) {
      startPlexAuth();
    } else {
      setCurrentStep("jellyfin");
    }
  }

  function startPlexAuth() {
    setError("");

    startTransition(async () => {
      try {
        // Initiate Plex OAuth
        const authResponse = await setupAPI.initiatePlexAuth();
        setPinCode(authResponse.pin_id);
        setCurrentStep("plex-auth");

        // Open Plex auth popup
        if (authResponse.auth_url) {
          const popup = window.open(
            authResponse.auth_url,
            "plex-auth",
            "width=600,height=700,toolbar=no,menubar=no,location=no,status=no"
          );
          plexAuthWindowRef.current = popup;
        }

        // Start polling for authentication
        setIsPolling(true);
        pollForAuth(authResponse.pin_id);
      } catch {
        setError("Failed to start authentication");
        setIsPolling(false);
      }
    });
  }

  async function pollForAuth(pinId: string) {
    const maxAttempts = 60; // Poll for up to 5 minutes
    let attempts = 0;

    const poll = async () => {
      if (attempts >= maxAttempts) {
        setError("Authentication timed out. Please try again.");
        setIsPolling(false);
        closeAuthWindow();
        return;
      }

      try {
        const result = await setupAPI.checkPlexAuth(pinId);
        if (result.success && result.encrypted_token) {
          setPlexAuthToken(result.encrypted_token);
          setIsPolling(false);

          // Close the Plex auth popup window on success
          closeAuthWindow();

          // Fetch available servers
          try {
            const response = await fetch(`/api/setup/plex/servers`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ auth_token: result.encrypted_token }),
            });
            const data = await response.json();

            if (data.servers && data.servers.length > 0) {
              // Auto-select first server (or only server)
              const firstServer = data.servers[0];
              setPlexServerName(firstServer.name);

              // Move to libraries step and load them
              setCurrentStep("libraries");
              loadPlexLibraries(result.encrypted_token, firstServer.name);
            } else {
              setError("No Plex servers found for your account");
            }
          } catch (err) {
            console.error("Failed to fetch servers:", err);
            setError("Failed to fetch Plex servers");
          }
        } else {
          attempts++;
          setTimeout(poll, 5000); // Poll every 5 seconds
        }
      } catch {
        attempts++;
        setTimeout(poll, 5000);
      }
    };

    poll();
  }

  async function loadPlexLibraries(authToken: string, serverName: string) {
    setError(""); // Clear any previous errors

    startLibrariesTransition(async () => {
      try {
        const plexLibs = await setupAPI.getPlexLibrariesWithAuth(authToken, serverName);
        setLibraries((prev) => [
          ...prev.filter((lib) => lib.server !== "plex"),
          ...plexLibs.map((lib) => ({ ...lib, count: 0, server: "plex" })),
        ]);
      } catch (err) {
        console.error("Failed to load libraries:", err);
        const errorMessage = err instanceof Error ? err.message : "Failed to load Plex libraries";
        setError(`Failed to load libraries from ${serverName}: ${errorMessage}`);
      }
    });
  }

  async function testPlexConnection() {
    if (selectedLibraries.length === 0) {
      setError("Please select at least one library");
      return;
    }

    setTestResults((prev) => ({
      ...prev,
      plex: { success: false, loading: true },
    }));

    try {
      const result = await setupAPI.testPlex();
      setTestResults((prev) => ({
        ...prev,
        plex: {
          success: result.success,
          error: result.success ? undefined : result.message,
        },
      }));
      if (result.success) {
        setCurrentStep("required-services");
      }
    } catch {
      setTestResults((prev) => ({
        ...prev,
        plex: {
          success: false,
          error: "Connection failed",
        },
      }));
    }
  }

  /** Run a connection test and keep its outcome under the service's name. */
  function runTest(service: string, test: () => Promise<ServiceTestResponse>) {
    setError("");
    startTransition(async () => {
      let result: ConnectionTestResult;
      try {
        const response = await test();
        result = {
          success: response.success,
          error: response.success ? undefined : (response.error ?? response.message),
          server_name: response.server_name,
          version: response.version,
        };
      } catch (err) {
        result = {
          success: false,
          error: err instanceof Error ? err.message : "Connection failed",
        };
      }
      setTestResults((prev) => ({ ...prev, [service]: result }));
    });
  }

  function handleTestJellyfin() {
    runTest("jellyfin", () => setupAPI.testJellyfin({ url: jellyfinUrl, api_key: jellyfinApiKey }));
  }

  const scannableLibraries = libraries.filter(
    (library) => library.type === "movie" || library.type === "show"
  );

  function isSelected(server: string, title: string) {
    return selectedLibraries.some((lib) => lib.server === server && lib.title === title);
  }

  function toggleLibrary(server: string, title: string, selected: boolean) {
    setSelectedLibraries((prev) =>
      selected
        ? [...prev, { server, title }]
        : prev.filter((lib) => !(lib.server === server && lib.title === title))
    );
  }

  function loadJellyfinLibraries() {
    setError("");
    setCurrentStep("libraries");

    startLibrariesTransition(async () => {
      try {
        const jellyfinLibs = await setupAPI.getJellyfinLibraries({
          url: jellyfinUrl,
          api_key: jellyfinApiKey,
        });
        setLibraries((prev) => [
          ...prev.filter((lib) => lib.server !== "jellyfin"),
          ...jellyfinLibs,
        ]);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load Jellyfin libraries");
      }
    });
  }

  function testService(service: "radarr" | "sonarr" | "qbittorrent") {
    const tests = {
      radarr: () => setupAPI.testRadarr({ url: radarrUrl, api_key: radarrApiKey }),
      sonarr: () => setupAPI.testSonarr({ url: sonarrUrl, api_key: sonarrApiKey }),
      qbittorrent: () =>
        setupAPI.testQBittorrent({ url: qbitUrl, username: qbitUsername, password: qbitPassword }),
    };
    runTest(service, tests[service]);
  }

  function completeSetup() {
    startTransition(async () => {
      try {
        // Build config object, only including non-empty values
        const config: Record<string, string> = {};

        // The selection is stored per server, under the key that names it
        for (const server of ["plex", "jellyfin"]) {
          const chosen = selectedLibraries
            .filter((lib) => lib.server === server)
            .map((lib) => lib.title);
          if (chosen.length > 0) {
            config[`${server}_libraries`] = chosen.join(",");
          }
        }

        // Only the servers that were actually set up are saved, since their
        // presence is what marks a server as configured.
        if (choice.plex && plexAuthToken) {
          config.plex_auth_token = plexAuthToken;
          config.plex_server_name = plexServerName;
        }
        if (choice.jellyfin && jellyfinUrl && jellyfinApiKey) {
          config.jellyfin_url = jellyfinUrl;
          config.jellyfin_api_key = jellyfinApiKey;
        }

        // Add optional services only if configured
        if (radarrUrl && radarrApiKey) {
          config.radarr_url = radarrUrl;
          config.radarr_api_key = radarrApiKey;
        }
        if (sonarrUrl && sonarrApiKey) {
          config.sonarr_url = sonarrUrl;
          config.sonarr_api_key = sonarrApiKey;
        }
        if (qbitUrl && qbitUsername && qbitPassword) {
          config.qbittorrent_url = qbitUrl;
          config.qbittorrent_username = qbitUsername;
          config.qbittorrent_password = qbitPassword;
        }

        // Save configuration to database
        const response = await fetch("/api/setup/save", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ config }),
        });

        if (!response.ok) {
          const error = await response.json();
          throw new Error(error.detail || "Failed to save configuration");
        }

        // Mark setup as complete
        await fetch("/api/setup/complete", {
          method: "POST",
        });

        // The app sends anyone without a media server back here, so it has
        // to see the new configuration before the dashboard loads.
        await queryClient.invalidateQueries({ queryKey: ["config"] });
        queryClient.invalidateQueries({ queryKey: ["mediaLibraries"] });
        queryClient.invalidateQueries({ queryKey: ["dashboardStats"] });
        navigate("/");
      } catch (error) {
        console.error("Setup failed:", error);
        setError(error instanceof Error ? error.message : "Failed to save configuration");
      }
    });
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-muted/30 to-muted/50 py-6 md:py-12 px-4">
      <div className="max-w-4xl mx-auto">
        <ProgressIndicator currentStep={currentStep} choice={choice} />

        {error && (
          <Card className="mb-4 md:mb-6 p-3 md:p-4 bg-destructive-light border-destructive-border">
            <div className="flex items-start gap-2">
              <AlertCircle className="w-4 h-4 text-destructive flex-shrink-0 mt-0.5" />
              <p className="text-xs md:text-sm text-destructive-foreground">{error}</p>
            </div>
          </Card>
        )}

        <Card className="p-4 md:p-8 animate-fade-in">
          {/* Welcome Step */}
          {currentStep === "welcome" && (
            <div className="text-center max-w-2xl mx-auto space-y-4 md:space-y-6">
              <div className="w-16 h-16 md:w-20 md:h-20 mx-auto rounded-2xl bg-gradient-to-br from-primary to-secondary text-primary-foreground flex items-center justify-center text-2xl md:text-3xl font-bold shadow-lg">
                DD
              </div>
              <h1 className="text-2xl md:text-3xl font-bold">Welcome to deduparr!</h1>
              <p className="text-sm md:text-lg text-muted-foreground">
                Your media server shows Deduparr what you have more than one copy of. Radarr and
                Sonarr do the deleting, and qBittorrent removes the matching downloads as well.
              </p>

              <Card className="p-4 md:p-6 bg-card border-border text-left">
                <h3 className="font-semibold mb-3 text-sm md:text-base">What you'll need:</h3>
                <div className="space-y-2 text-xs md:text-sm">
                  <div className="flex items-start gap-2">
                    <Check className="w-4 h-4 text-primary flex-shrink-0 mt-0.5" />
                    <span>Plex or Jellyfin - either one, or both</span>
                  </div>
                  <div className="flex items-start gap-2">
                    <Check className="w-4 h-4 text-primary flex-shrink-0 mt-0.5" />
                    <span>A Plex account, or a Jellyfin server URL and admin API key</span>
                  </div>
                  <div className="flex items-start gap-2 opacity-60">
                    <Check className="w-4 h-4 text-primary flex-shrink-0 mt-0.5" />
                    <span>qBittorrent (optional - for automated deletion)</span>
                  </div>
                  <div className="flex items-start gap-2 opacity-60">
                    <Check className="w-4 h-4 text-primary flex-shrink-0 mt-0.5" />
                    <span>Radarr/Sonarr (optional - for automated deletion)</span>
                  </div>
                </div>
              </Card>

              <Button
                size="lg"
                onClick={handleGetStarted}
                disabled={isPending}
                className="w-full sm:w-auto"
              >
                {isPending ? (
                  <>
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                    Starting...
                  </>
                ) : (
                  "Get Started"
                )}
              </Button>
            </div>
          )}

          {/* Plex Auth Step */}
          {currentStep === "plex-auth" && (
            <div className="text-center max-w-2xl mx-auto space-y-4 md:space-y-6">
              <div className="w-16 h-16 md:w-20 md:h-20 mx-auto rounded-2xl bg-gradient-to-br from-primary to-secondary text-primary-foreground flex items-center justify-center text-2xl md:text-3xl font-bold shadow-lg">
                P
              </div>
              <h2 className="text-xl md:text-2xl font-bold">Authenticate with Plex</h2>

              {isPolling && (
                <Card className="p-4 md:p-6 bg-card border-border">
                  <div className="flex flex-col items-center gap-4">
                    <Loader2 className="w-10 h-10 md:w-12 md:h-12 text-primary animate-spin" />
                    <div>
                      <p className="font-medium mb-1 text-sm md:text-base">
                        Waiting for authorization...
                      </p>
                      <p className="text-xs md:text-sm text-muted-foreground">
                        Please complete the authentication in the popup window
                      </p>
                    </div>
                    <div className="p-3 md:p-4 bg-background rounded-lg border">
                      <p className="text-xs text-muted-foreground mb-1">PIN Code:</p>
                      <p className="text-xl md:text-2xl font-mono font-bold">{pinCode}</p>
                    </div>
                    <Button
                      variant="outline"
                      onClick={handleCancelAuth}
                      className="mt-2 w-full sm:w-auto"
                    >
                      Cancel
                    </Button>
                  </div>
                </Card>
              )}
            </div>
          )}

          {/* Plex Server Step */}
          {currentStep === "plex-server" && (
            <div className="max-w-2xl mx-auto space-y-4 md:space-y-6">
              <div className="text-center">
                <div className="w-16 h-16 md:w-20 md:h-20 mx-auto mb-4 rounded-2xl bg-gradient-to-br from-primary to-secondary text-primary-foreground flex items-center justify-center text-2xl md:text-3xl font-bold shadow-lg">
                  S
                </div>
                <h2 className="text-xl md:text-2xl font-bold mb-2">Connect to Plex</h2>
                <p className="text-sm md:text-base text-muted-foreground">
                  Test your connection to verify everything is working
                </p>
              </div>

              {!plexAuthToken || plexAuthToken === "" ? (
                <div className="flex flex-col items-center gap-4">
                  <Button
                    size="lg"
                    onClick={startPlexAuth}
                    disabled={isPending}
                    className="w-full sm:w-auto"
                  >
                    {isPending ? (
                      <>
                        <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                        Starting...
                      </>
                    ) : (
                      "Authenticate with Plex"
                    )}
                  </Button>
                </div>
              ) : (
                <>
                  <TestResultDisplay result={testResults.plex} />

                  <div className="flex flex-col sm:flex-row gap-3">
                    <Button
                      variant="outline"
                      onClick={() => setCurrentStep("welcome")}
                      className="flex-1"
                    >
                      Back
                    </Button>
                    <Button onClick={testPlexConnection} disabled={isPending} className="flex-1">
                      {isPending ? (
                        <>
                          <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                          Testing...
                        </>
                      ) : (
                        "Test Connection"
                      )}
                    </Button>
                    {testResults.plex?.success && (
                      <Button
                        onClick={() => setCurrentStep(choice.jellyfin ? "jellyfin" : "libraries")}
                        className="flex-1"
                      >
                        Next: Libraries
                      </Button>
                    )}
                  </div>
                </>
              )}
            </div>
          )}

          {/* Libraries Step */}
          {currentStep === "media-server" && (
            <div className="max-w-2xl mx-auto space-y-4 md:space-y-6">
              <div className="text-center">
                <div className="w-16 h-16 md:w-20 md:h-20 mx-auto mb-4 rounded-2xl bg-gradient-to-br from-primary to-secondary text-primary-foreground flex items-center justify-center shadow-lg">
                  <Server className="w-8 h-8 md:w-10 md:h-10" />
                </div>
                <h2 className="text-xl md:text-2xl font-bold mb-2">Choose your media server</h2>
                <p className="text-sm md:text-base text-muted-foreground">
                  Deduparr reads your libraries from here. Pick both if you run both over the same
                  media.
                </p>
              </div>

              <div className="space-y-2 md:space-y-3">
                <label
                  htmlFor="choose-plex"
                  className="flex items-start gap-3 p-4 rounded-lg border border-border bg-card cursor-pointer hover:bg-accent/50 transition-colors"
                >
                  <Checkbox
                    id="choose-plex"
                    checked={choice.plex}
                    onCheckedChange={(checked) =>
                      setChoice((prev) => ({ ...prev, plex: checked === true }))
                    }
                    className="mt-0.5"
                  />
                  <div>
                    <div className="font-medium text-foreground">Plex</div>
                    <p className="text-xs md:text-sm text-muted-foreground mt-1">
                      Signs in through plex.tv, so no server URL or token is needed.
                    </p>
                  </div>
                </label>

                <label
                  htmlFor="choose-jellyfin"
                  className="flex items-start gap-3 p-4 rounded-lg border border-border bg-card cursor-pointer hover:bg-accent/50 transition-colors"
                >
                  <Checkbox
                    id="choose-jellyfin"
                    checked={choice.jellyfin}
                    onCheckedChange={(checked) =>
                      setChoice((prev) => ({ ...prev, jellyfin: checked === true }))
                    }
                    className="mt-0.5"
                  />
                  <div>
                    <div className="font-medium text-foreground">Jellyfin</div>
                    <p className="text-xs md:text-sm text-muted-foreground mt-1">
                      Needs the server URL and an API key from an administrator account.
                    </p>
                  </div>
                </label>
              </div>

              {!choice.plex && !choice.jellyfin && (
                <div className="flex items-start gap-2 text-sm text-muted-foreground">
                  <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
                  <span>Select at least one media server to continue.</span>
                </div>
              )}

              <div className="flex flex-col sm:flex-row gap-2">
                <Button
                  variant="outline"
                  onClick={() => setCurrentStep("welcome")}
                  className="flex-1"
                >
                  Back
                </Button>
                <Button
                  data-testid="server-choice-continue"
                  onClick={handleServerChoice}
                  disabled={(!choice.plex && !choice.jellyfin) || isPending}
                  className="flex-1"
                >
                  {isPending ? (
                    <>
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                      Starting...
                    </>
                  ) : (
                    "Continue"
                  )}
                </Button>
              </div>
            </div>
          )}

          {currentStep === "jellyfin" && (
            <div className="max-w-2xl mx-auto space-y-4 md:space-y-6">
              <div className="text-center">
                <div className="w-16 h-16 md:w-20 md:h-20 mx-auto mb-4 rounded-2xl bg-gradient-to-br from-primary to-secondary text-primary-foreground flex items-center justify-center shadow-lg">
                  <Server className="w-8 h-8 md:w-10 md:h-10" />
                </div>
                <h2 className="text-xl md:text-2xl font-bold mb-2">Connect Jellyfin</h2>
                <p className="text-sm md:text-base text-muted-foreground">
                  Create an API key under Dashboard &rarr; API Keys on an administrator account.
                </p>
              </div>

              <div className="space-y-3 md:space-y-4">
                <div>
                  <Label htmlFor="jellyfin-url">Server URL</Label>
                  <Input
                    id="jellyfin-url"
                    value={jellyfinUrl}
                    onChange={(e) => {
                      setJellyfinUrl(e.target.value);
                      forgetTest("jellyfin");
                    }}
                    placeholder="http://jellyfin:8096"
                    className="mt-1"
                  />
                </div>
                <div>
                  <Label htmlFor="jellyfin-api-key">API Key</Label>
                  <Input
                    id="jellyfin-api-key"
                    type="password"
                    value={jellyfinApiKey}
                    onChange={(e) => {
                      setJellyfinApiKey(e.target.value);
                      forgetTest("jellyfin");
                    }}
                    placeholder="Administrator API key"
                    className="mt-1"
                  />
                </div>

                <Button
                  variant="outline"
                  data-testid="jellyfin-test"
                  onClick={handleTestJellyfin}
                  disabled={!jellyfinUrl || !jellyfinApiKey || isPending}
                  className="w-full sm:w-auto"
                >
                  {isPending ? (
                    <>
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                      Testing...
                    </>
                  ) : (
                    "Test Connection"
                  )}
                </Button>

                <TestResultDisplay result={testResults.jellyfin} />
              </div>

              <div className="flex flex-col sm:flex-row gap-2">
                <Button
                  variant="outline"
                  onClick={() => setCurrentStep(choice.plex ? "plex-server" : "media-server")}
                  className="flex-1"
                >
                  Back
                </Button>
                <Button
                  data-testid="jellyfin-continue"
                  onClick={loadJellyfinLibraries}
                  disabled={!testResults.jellyfin?.success}
                  className="flex-1"
                >
                  Continue
                </Button>
              </div>
            </div>
          )}

          {currentStep === "libraries" && (
            <div className="max-w-2xl mx-auto space-y-4 md:space-y-6">
              <div className="text-center">
                <div className="w-16 h-16 md:w-20 md:h-20 mx-auto mb-4 rounded-2xl bg-gradient-to-br from-primary to-secondary text-primary-foreground flex items-center justify-center text-2xl md:text-3xl font-bold shadow-lg">
                  L
                </div>
                <h2 className="text-xl md:text-2xl font-bold mb-2">Select Libraries to Scan</h2>
                <p className="text-sm md:text-base text-muted-foreground">
                  Choose which libraries to scan for duplicates
                </p>
              </div>

              {isLoadingLibraries ? (
                <div className="flex flex-col items-center justify-center py-12 space-y-4">
                  <Loader2 className="w-10 h-10 md:w-12 md:h-12 animate-spin text-primary" />
                  <p className="text-base md:text-lg font-medium text-foreground">
                    Loading your libraries...
                  </p>
                  <p className="text-xs md:text-sm text-muted-foreground">
                    This may take a few moments
                  </p>
                </div>
              ) : libraries.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-12 space-y-4">
                  <AlertCircle className="w-10 h-10 md:w-12 md:h-12 text-destructive" />
                  <p className="text-base md:text-lg font-medium text-foreground">
                    No libraries found
                  </p>
                  <p className="text-xs md:text-sm text-muted-foreground">
                    Make sure your media server has movie or TV show libraries
                  </p>
                </div>
              ) : (
                <div className="space-y-2 md:space-y-3">
                  {scannableLibraries.map((library) => (
                    <label
                      key={`${library.server}:${library.key}`}
                      htmlFor={`library-${library.server}-${library.key}`}
                      className="flex items-center p-3 md:p-4 border-2 rounded-lg cursor-pointer hover:border-muted-foreground transition-colors"
                    >
                      <Checkbox
                        id={`library-${library.server}-${library.key}`}
                        checked={isSelected(library.server, library.title)}
                        onCheckedChange={(checked) =>
                          toggleLibrary(library.server, library.title, checked === true)
                        }
                      />
                      <div className="ml-3 flex-1">
                        <span className="font-semibold text-sm md:text-base">{library.title}</span>
                        <span className="text-xs md:text-sm text-muted-foreground ml-2">
                          ({library.type})
                        </span>
                        <span className="text-xs text-muted-foreground ml-2">
                          on {MEDIA_SERVER_NAMES[library.server] ?? library.server}
                        </span>
                      </div>
                    </label>
                  ))}
                </div>
              )}

              {!isLoadingLibraries && libraries.length > 0 && (
                <Card className="p-3 md:p-4 bg-card border-border">
                  <p className="text-xs md:text-sm text-muted-foreground">
                    Tip: You can change this selection on the Scan page
                  </p>
                </Card>
              )}

              <div className="flex flex-col sm:flex-row gap-3">
                <Button
                  variant="outline"
                  onClick={() => setCurrentStep("plex-server")}
                  className="flex-1"
                  disabled={isLoadingLibraries}
                >
                  Back
                </Button>
                <Button
                  onClick={() => setCurrentStep("required-services")}
                  className="flex-1"
                  disabled={isLoadingLibraries || selectedLibraries.length === 0}
                >
                  Next: Services
                </Button>
              </div>
            </div>
          )}

          {/* Required Services Step */}
          {currentStep === "required-services" && (
            <div className="max-w-3xl mx-auto space-y-4 md:space-y-6">
              <div className="text-center">
                <div className="w-16 h-16 md:w-20 md:h-20 mx-auto mb-4 rounded-2xl bg-gradient-to-br from-primary to-secondary text-primary-foreground flex items-center justify-center text-2xl md:text-3xl font-bold shadow-lg">
                  C
                </div>
                <h2 className="text-xl md:text-2xl font-bold mb-2">
                  Configure Services (Optional)
                </h2>
                <p className="text-sm md:text-base text-muted-foreground">
                  Add services to enable automated duplicate deletion
                </p>
              </div>

              <Card className="p-3 md:p-4 bg-card border-border">
                <div className="flex items-start gap-2">
                  <AlertCircle className="w-4 h-4 text-primary flex-shrink-0 mt-0.5" />
                  <div className="text-xs md:text-sm">
                    <p className="font-semibold mb-1">These services are optional:</p>
                    <ul className="space-y-1 text-muted-foreground">
                      <li>
                        • <strong>Without them:</strong> Deduparr deletes the files itself
                      </li>
                      <li>
                        • <strong>With qBittorrent:</strong> a deleted file's torrent is removed
                        when nothing else needs it
                      </li>
                      <li>
                        • <strong>With Radarr/Sonarr:</strong> files are deleted through them, so
                        they are not downloaded again
                      </li>
                      <li>• You can configure these later in Settings</li>
                    </ul>
                  </div>
                </div>
              </Card>

              {/* Radarr */}
              <Card className="p-4 md:p-6">
                <div className="flex items-center gap-2 mb-4">
                  <Film className="w-5 h-5 text-primary" />
                  <h3 className="text-base md:text-lg font-semibold">Radarr (Movies)</h3>
                </div>
                <div className="space-y-4">
                  <div>
                    <Label htmlFor="radarr-url" className="text-xs md:text-sm">
                      URL
                    </Label>
                    <Input
                      id="radarr-url"
                      type="url"
                      value={radarrUrl}
                      onChange={(e) => {
                        setRadarrUrl(e.target.value);
                        forgetTest("radarr");
                      }}
                      placeholder="http://localhost:7878"
                      className="mt-2 text-sm"
                    />
                  </div>
                  <div>
                    <Label htmlFor="radarr-key" className="text-xs md:text-sm">
                      API Key
                    </Label>
                    <Input
                      id="radarr-key"
                      type="password"
                      value={radarrApiKey}
                      onChange={(e) => {
                        setRadarrApiKey(e.target.value);
                        forgetTest("radarr");
                      }}
                      placeholder="Enter your Radarr API key"
                      className="mt-2 text-sm"
                    />
                  </div>
                  <Button
                    onClick={() => testService("radarr")}
                    disabled={!radarrUrl || !radarrApiKey || isPending}
                    className="w-full sm:w-auto text-xs md:text-sm"
                  >
                    Test Connection
                  </Button>
                  <TestResultDisplay result={testResults.radarr} />
                </div>
              </Card>

              {/* Sonarr */}
              <Card className="p-4 md:p-6">
                <div className="flex items-center gap-2 mb-4">
                  <Tv className="w-5 h-5 text-primary" />
                  <h3 className="text-base md:text-lg font-semibold">Sonarr (TV Shows)</h3>
                </div>
                <div className="space-y-4">
                  <div>
                    <Label htmlFor="sonarr-url" className="text-xs md:text-sm">
                      URL
                    </Label>
                    <Input
                      id="sonarr-url"
                      type="url"
                      value={sonarrUrl}
                      onChange={(e) => {
                        setSonarrUrl(e.target.value);
                        forgetTest("sonarr");
                      }}
                      placeholder="http://localhost:8989"
                      className="mt-2 text-sm"
                    />
                  </div>
                  <div>
                    <Label htmlFor="sonarr-key" className="text-xs md:text-sm">
                      API Key
                    </Label>
                    <Input
                      id="sonarr-key"
                      type="password"
                      value={sonarrApiKey}
                      onChange={(e) => {
                        setSonarrApiKey(e.target.value);
                        forgetTest("sonarr");
                      }}
                      placeholder="Enter your Sonarr API key"
                      className="mt-2 text-sm"
                    />
                  </div>
                  <Button
                    onClick={() => testService("sonarr")}
                    disabled={!sonarrUrl || !sonarrApiKey || isPending}
                    className="w-full sm:w-auto text-xs md:text-sm"
                  >
                    Test Connection
                  </Button>
                  <TestResultDisplay result={testResults.sonarr} />
                </div>
              </Card>

              {/* qBittorrent */}
              <Card className="p-4 md:p-6">
                <div className="flex items-center gap-2 mb-4">
                  <Download className="w-5 h-5 text-primary" />
                  <h3 className="text-base md:text-lg font-semibold">qBittorrent</h3>
                </div>
                <div className="space-y-4">
                  <div>
                    <Label htmlFor="qbit-url" className="text-xs md:text-sm">
                      URL
                    </Label>
                    <Input
                      id="qbit-url"
                      type="url"
                      value={qbitUrl}
                      onChange={(e) => {
                        setQbitUrl(e.target.value);
                        forgetTest("qbittorrent");
                      }}
                      placeholder="http://localhost:8080"
                      className="mt-2 text-sm"
                    />
                  </div>
                  <div>
                    <Label htmlFor="qbit-user" className="text-xs md:text-sm">
                      Username
                    </Label>
                    <Input
                      id="qbit-user"
                      value={qbitUsername}
                      onChange={(e) => {
                        setQbitUsername(e.target.value);
                        forgetTest("qbittorrent");
                      }}
                      placeholder="admin"
                      className="mt-2 text-sm"
                    />
                  </div>
                  <div>
                    <Label htmlFor="qbit-pass" className="text-xs md:text-sm">
                      Password
                    </Label>
                    <Input
                      id="qbit-pass"
                      type="password"
                      value={qbitPassword}
                      onChange={(e) => {
                        setQbitPassword(e.target.value);
                        forgetTest("qbittorrent");
                      }}
                      placeholder="Enter your qBittorrent password"
                      className="mt-2 text-sm"
                    />
                  </div>
                  <Button
                    onClick={() => testService("qbittorrent")}
                    disabled={!qbitUrl || !qbitUsername || !qbitPassword || isPending}
                    className="w-full sm:w-auto text-xs md:text-sm"
                  >
                    Test Connection
                  </Button>
                  <TestResultDisplay result={testResults.qbittorrent} />
                </div>
              </Card>

              <div className="flex flex-col sm:flex-row gap-3">
                <Button
                  variant="outline"
                  onClick={() => setCurrentStep("libraries")}
                  className="flex-1"
                >
                  Back
                </Button>
                <Button onClick={completeSetup} disabled={isPending} className="flex-1">
                  {isPending ? (
                    <>
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                      Saving...
                    </>
                  ) : (
                    "Complete Setup"
                  )}
                </Button>
              </div>
            </div>
          )}

          {/* Complete Step */}
          {currentStep === "complete" && (
            <div className="text-center max-w-2xl mx-auto space-y-4 md:space-y-6">
              <div className="w-16 h-16 md:w-20 md:h-20 mx-auto rounded-2xl bg-primary text-primary-foreground flex items-center justify-center text-2xl md:text-3xl font-bold shadow-lg">
                ✓
              </div>
              <h1 className="text-2xl md:text-3xl font-bold">Setup Complete!</h1>
              <p className="text-sm md:text-lg text-muted-foreground">
                Your deduparr installation is now configured and ready to use.
                <br />
                Redirecting to dashboard in a moment...
              </p>

              <Card className="p-4 md:p-6 bg-card border-border text-left">
                <h3 className="font-semibold mb-3 text-sm md:text-base">What's configured:</h3>
                <div className="space-y-2 text-xs md:text-sm">
                  <div className="flex items-center gap-2">
                    <Check className="w-4 h-4 text-primary" />
                    <span>Plex authenticated</span>
                  </div>
                  {testResults.radarr?.success && (
                    <div className="flex items-center gap-2">
                      <Check className="w-4 h-4 text-primary" />
                      <span>Radarr connected</span>
                    </div>
                  )}
                  {testResults.sonarr?.success && (
                    <div className="flex items-center gap-2">
                      <Check className="w-4 h-4 text-primary" />
                      <span>Sonarr connected</span>
                    </div>
                  )}
                  {testResults.qbittorrent?.success && (
                    <div className="flex items-center gap-2">
                      <Check className="w-4 h-4 text-primary" />
                      <span>qBittorrent connected</span>
                    </div>
                  )}
                </div>
              </Card>

              <Card className="p-4 md:p-6 bg-card border-border text-left">
                <h3 className="font-semibold mb-3 text-sm md:text-base">Next steps:</h3>
                <ol className="space-y-2 text-xs md:text-sm text-muted-foreground list-decimal list-inside">
                  <li>Head to the Dashboard to view your media statistics</li>
                  <li>Configure duplicate detection rules in Settings</li>
                  <li>Run your first scan to find duplicates</li>
                  <li>Review and approve deletions in dry-run mode</li>
                </ol>
              </Card>

              <Button size="lg" onClick={() => navigate("/")} className="w-full sm:w-auto">
                Go to Dashboard
              </Button>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
