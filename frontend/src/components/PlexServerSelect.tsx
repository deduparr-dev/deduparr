import { Label } from "@/components/ui/label";
import { type PlexServer } from "@/services/api";

interface PlexServerSelectProps {
  servers: PlexServer[];
  value: string;
  onChange: (name: string) => void;
  disabled?: boolean;
}

export function PlexServerSelect({ servers, value, onChange, disabled }: PlexServerSelectProps) {
  return (
    <div>
      <Label htmlFor="server">Select Plex Server</Label>
      <select
        id="server"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="mt-2 w-full rounded-lg border border-border bg-card px-3 py-2 text-sm text-foreground focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
        disabled={disabled}
      >
        <option value="">Choose a server...</option>
        {servers.map((server) => (
          <option key={server.client_identifier} value={server.name}>
            {server.name} ({server.platform})
          </option>
        ))}
      </select>
    </div>
  );
}
