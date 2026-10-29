/**
 * A Jellyfin server, reduced to the endpoints Deduparr calls.
 *
 * It exists so the e2e suite can exercise the Jellyfin adapter for real -
 * authentication, library listing, duplicate detection and refresh - without a
 * Jellyfin install. Responses are shaped after a live Jellyfin 12.4.0.
 *
 * Env:
 *   PORT              port to listen on (default 8097)
 *   MEDIA_DIR         directory the reported file paths live in
 *   ADMIN_API_KEY     the only key accepted (default "fake-admin-key")
 */

import crypto from "crypto";
import http from "http";
import path from "path";

const PORT = Number(process.env.PORT ?? 8097);
const MEDIA_DIR = process.env.MEDIA_DIR ?? "/tmp/fake-jellyfin-media";
const ADMIN_API_KEY = process.env.ADMIN_API_KEY ?? "fake-admin-key";
const USER_ID = "11111111111111111111111111111111";
const LIBRARY_ID = "22222222222222222222222222222222";
const SHOW_LIBRARY_ID = "55555555555555555555555555555555";

/** Items the server pretends to hold. Mutated by /reset so specs can vary it. */
let items = [];

/**
 * A stable id per title.
 *
 * Hashed rather than hex-encoded: hex of the title truncated to 32 characters
 * only covers the first 16 characters, so titles sharing a prefix collided and
 * a spec kept matching the set an earlier run had left behind.
 */
function itemId(title) {
  return crypto.createHash("sha1").update(title).digest("hex").slice(0, 32);
}

function movieDir(title) {
  return path.join(MEDIA_DIR, "Movies", title);
}

function mediaSource(filePath, { size, bitrate, codec, width, height }) {
  return {
    Id: Buffer.from(filePath).toString("hex").slice(0, 32),
    Path: filePath,
    Protocol: "File",
    Size: size,
    Bitrate: bitrate,
    Container: "mkv",
    MediaStreams: [
      { Type: "Video", Codec: codec, Width: width, Height: height, BitRate: bitrate },
      { Type: "Audio", Codec: "aac", BitRate: 128000 },
    ],
  };
}

/** One movie stored twice: a 1080p HEVC copy and a 720p H264 copy. */
function duplicateMovie(title, id) {
  const dir = movieDir(title);
  return {
    Id: id ?? itemId(title),
    Name: title,
    Type: "Movie",
    ProductionYear: 2024,
    Path: dir,
    MediaSources: [
      mediaSource(path.join(dir, `${title} 1080p.mkv`), {
        size: 8_000_000,
        bitrate: 12_000_000,
        codec: "hevc",
        width: 1920,
        height: 1080,
      }),
      mediaSource(path.join(dir, `${title} 720p.mkv`), {
        size: 2_000_000,
        bitrate: 4_000_000,
        codec: "h264",
        width: 1280,
        height: 720,
      }),
    ],
  };
}

/**
 * One episode stored twice.
 *
 * Jellyfin returns episodes as their own items carrying SeriesName and the
 * season and episode numbers, with each stored file as a MediaSource.
 */
function duplicateEpisode(series, season, number, name) {
  const dir = path.join(MEDIA_DIR, "Shows", series, `Season ${season}`);
  const stem = `${series} - S${String(season).padStart(2, "0")}E${String(number).padStart(2, "0")}`;
  return {
    Id: itemId(stem),
    Name: name,
    Type: "Episode",
    SeriesName: series,
    ParentIndexNumber: season,
    IndexNumber: number,
    Path: dir,
    MediaSources: [
      mediaSource(path.join(dir, `${stem} 1080p.mkv`), {
        size: 4_000_000,
        bitrate: 10_000_000,
        codec: "hevc",
        width: 1920,
        height: 1080,
      }),
      mediaSource(path.join(dir, `${stem} 480p.mkv`), {
        size: 700_000,
        bitrate: 1_500_000,
        codec: "mpeg4",
        width: 854,
        height: 480,
      }),
    ],
  };
}

/** A movie held once, which is not a duplicate. */
function singleMovie(title, id) {
  const dir = movieDir(title);
  return {
    Id: id ?? itemId(title),
    Name: title,
    Type: "Movie",
    ProductionYear: 2024,
    Path: dir,
    MediaSources: [
      mediaSource(path.join(dir, `${title} 1080p.mkv`), {
        size: 5_000_000,
        bitrate: 9_000_000,
        codec: "h264",
        width: 1920,
        height: 1080,
      }),
    ],
  };
}

function defaultItems() {
  return [
    duplicateMovie("Fake Duplicate (2024)", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"),
    singleMovie("Fake Single (2024)", "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"),
    duplicateEpisode("Fake Show", 1, 2, "The Second One"),
  ];
}

items = defaultItems();

function isAdmin(req) {
  const header = req.headers.authorization ?? "";
  const token = /Token="?([^",]+)"?/.exec(header)?.[1] ?? req.headers["x-emby-token"];
  return token === ADMIN_API_KEY;
}

/**
 * Read a query parameter without caring about case.
 *
 * ASP.NET binds query parameters case-insensitively, and the SDK relies on it:
 * it sends IncludeItemTypes and StartIndex in PascalCase.
 */
function param(url, name) {
  const wanted = name.toLowerCase();
  for (const [key, value] of url.searchParams) {
    if (key.toLowerCase() === wanted) return value;
  }
  return null;
}

function json(res, status, body) {
  const payload = JSON.stringify(body);
  res.writeHead(status, {
    "Content-Type": "application/json",
    "Content-Length": Buffer.byteLength(payload),
  });
  res.end(payload);
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);
  // Jellyfin runs on ASP.NET, whose routing is case-insensitive, and the SDK
  // relies on that: it asks for "system/info/public" in lower case.
  const route = url.pathname.replace(/\/$/, "").toLowerCase();

  // Public, so it answers without a key - as Jellyfin does
  if (route === "/system/info/public") {
    return json(res, 200, {
      ServerName: "Fake Jellyfin",
      Version: "12.4.0",
      Id: "fake",
      StartupWizardCompleted: true,
    });
  }

  // Lets a spec swap in a different library state. A spec may also name the
  // title it wants, so it is unaffected by sets earlier specs left behind in
  // the shared database.
  if (route === "/reset" && req.method === "POST") {
    let body = "";
    req.on("data", (chunk) => (body += chunk));
    return req.on("end", () => {
      const { mode = "default", title } = body ? JSON.parse(body) : {};
      const name = title ?? "Fake Duplicate (2024)";
      const id = itemId(name);

      if (mode === "empty") {
        items = [];
      } else if (mode === "no-duplicates") {
        items = [singleMovie(name, id)];
      } else if (mode === "episodes") {
        items = [duplicateEpisode("Fake Show", 1, 2, name)];
      } else {
        items = [
          duplicateMovie(name, id),
          singleMovie("Fake Single (2024)", "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"),
        ];
      }
      json(res, 200, { ok: true, items: items.length, title: name });
    });
  }

  // Everything else is admin-only, which is what Deduparr requires
  if (!isAdmin(req)) {
    return json(res, 401, { Message: "Invalid token" });
  }

  if (route === "/system/info") {
    // The SDK reads Id and ServerName off this to identify the server
    return json(res, 200, {
      Id: "fake-server-id",
      ServerName: "Fake Jellyfin",
      Version: "12.4.0",
      OperatingSystem: "",
      LocalAddress: `http://127.0.0.1:${PORT}`,
    });
  }

  // The SDK reads this during connect
  if (route === "/system/configuration") {
    return json(res, 200, { ServerName: "Fake Jellyfin", IsStartupWizardCompleted: true });
  }

  if (route === "/users") {
    return json(res, 200, [
      { Id: USER_ID, Name: "admin", Policy: { IsAdministrator: true } },
      { Id: "33333333333333333333333333333333", Name: "viewer", Policy: { IsAdministrator: false } },
    ]);
  }

  if (route === "/library/virtualfolders") {
    return json(res, 200, [
      {
        Name: "Fake Movies",
        CollectionType: "movies",
        ItemId: LIBRARY_ID,
        Locations: [path.join(MEDIA_DIR, "Movies")],
      },
      {
        Name: "Fake Shows",
        CollectionType: "tvshows",
        ItemId: SHOW_LIBRARY_ID,
        Locations: [path.join(MEDIA_DIR, "Shows")],
      },
      {
        Name: "Fake Music",
        CollectionType: "music",
        ItemId: "44444444444444444444444444444444",
        Locations: [path.join(MEDIA_DIR, "Music")],
      },
    ]);
  }

  if (route === `/users/${USER_ID.toLowerCase()}/items` || route === "/items") {
    const types = (param(url, "IncludeItemTypes") ?? "").split(",");
    const parentId = param(url, "ParentId");
    const startIndex = Number(param(url, "StartIndex") ?? 0);
    const limit = Number(param(url, "Limit") ?? 500);
    const libraryOf = (item) => (item.Type === "Episode" ? SHOW_LIBRARY_ID : LIBRARY_ID);
    const matching = items.filter(
      (item) =>
        types.includes(item.Type) && (!parentId || libraryOf(item) === parentId)
    );
    return json(res, 200, {
      Items: matching.slice(startIndex, startIndex + limit),
      TotalRecordCount: matching.length,
      StartIndex: startIndex,
    });
  }

  if (/^\/items\/[^/]+\/refresh$/.test(route) && req.method === "POST") {
    return json(res, 204, {});
  }

  if (route === "/library/refresh" && req.method === "POST") {
    return json(res, 204, {});
  }

  return json(res, 404, { Message: `No fake route for ${route}` });
});

server.listen(PORT, "127.0.0.1", () => {
  process.stdout.write(`fake-jellyfin listening on http://127.0.0.1:${PORT}\n`);
});
