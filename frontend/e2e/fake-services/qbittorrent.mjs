/**
 * A qBittorrent, reduced to what Deduparr calls through qbittorrent-api.
 *
 * Deduparr uses auth_log_in, app_version, torrents_info, torrents_files and
 * torrents_delete, so only those have to behave. qbittorrent-api POSTs its
 * parameters as a form, and deleting with deleteFiles removes the data from
 * disk. A POST /reset restores the state and GET /state reports what Deduparr
 * did.
 *
 * Env: PORT, USERNAME, PASSWORD, MEDIA_DIR
 */

import fs from "fs";
import http from "http";
import path from "path";

const PORT = Number(process.env.PORT ?? 8080);
const USERNAME = process.env.USERNAME ?? "admin";
const PASSWORD = process.env.PASSWORD ?? "adminadmin";
const MEDIA_DIR = process.env.MEDIA_DIR ?? "/tmp/fake-media";
const COOKIE = "SID=fake-session";

let state = {};

/** The fake Jellyfin's default duplicate; /reset can name another title. */
const DEFAULT_TITLE = "Fake Duplicate (2024)";

/**
 * The unwanted 720p copy still seeds. The kept 1080p's torrent is long gone,
 * as is usual once a better copy has been imported.
 */
function reset(title = DEFAULT_TITLE) {
  state = {
    torrents: [
      {
        hash: "aaaa1111",
        name: `${title} 720p`,
        save_path: `${MEDIA_DIR}/Movies/${title}`,
        content_path: `${MEDIA_DIR}/Movies/${title}/${title} 720p.mkv`,
        state: "pausedUP",
        progress: 1,
      },
      {
        // A season pack: deleting one episode must not take the others
        hash: "cccc3333",
        name: "Fake Show S01 480p",
        save_path: `${MEDIA_DIR}/Shows/Fake Show`,
        content_path: `${MEDIA_DIR}/Shows/Fake Show/Season 1`,
        state: "pausedUP",
        progress: 1,
      },
    ],
    files: {
      aaaa1111: [{ name: `${title} 720p.mkv`, size: 2_000_000, index: 0, progress: 1 }],
      cccc3333: [
        { name: "Season 1/Fake Show - S01E02 480p.mkv", size: 700_000, index: 0, progress: 1 },
        { name: "Season 1/Fake Show - S01E03 480p.mkv", size: 700_000, index: 1, progress: 1 },
      ],
    },
    // What Deduparr did
    deleted: [],
  };
}
reset();

function send(res, status, body, headers = {}) {
  const payload = typeof body === "string" ? body : JSON.stringify(body);
  res.writeHead(status, {
    "Content-Type": typeof body === "string" ? "text/plain" : "application/json",
    "Content-Length": Buffer.byteLength(payload),
    ...headers,
  });
  res.end(payload);
}

function readRaw(req) {
  return new Promise((resolve) => {
    let raw = "";
    req.on("data", (c) => (raw += c));
    req.on("end", () => resolve(raw));
  });
}

async function readBody(req) {
  return new URLSearchParams(await readRaw(req));
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);
  const route = url.pathname.replace(/\/$/, "");

  if (route === "/reset" && req.method === "POST") {
    const raw = await readRaw(req);
    reset(raw ? JSON.parse(raw).title : undefined);
    return send(res, 200, { ok: true });
  }
  if (route === "/state") {
    return send(res, 200, state);
  }

  if (route === "/api/v2/auth/login") {
    const form = await readBody(req);
    if (form.get("username") !== USERNAME || form.get("password") !== PASSWORD) {
      return send(res, 200, "Fails.");
    }
    return send(res, 200, "Ok.", { "Set-Cookie": `${COOKIE}; path=/` });
  }

  // Everything past login needs the session cookie, as qBittorrent requires
  if (!(req.headers.cookie ?? "").includes("SID=")) {
    return send(res, 403, "Forbidden");
  }

  if (route === "/api/v2/app/version") {
    return send(res, 200, "v4.6.0");
  }
  if (route === "/api/v2/app/webapiVersion") {
    return send(res, 200, "2.9.3");
  }
  if (route === "/api/v2/app/preferences") {
    return send(res, 200, { save_path: `${MEDIA_DIR}/Movies` });
  }
  if (route === "/api/v2/torrents/info") {
    return send(res, 200, state.torrents);
  }
  const params = req.method === "POST" ? await readBody(req) : url.searchParams;

  if (route === "/api/v2/torrents/files") {
    return send(res, 200, state.files[params.get("hash")] ?? []);
  }
  if (route === "/api/v2/torrents/delete") {
    const hashes = (params.get("hashes") ?? "").split("|").filter(Boolean);
    // qbittorrent-api sends Python's "True"; qBittorrent ignores the case
    const deleteFiles = (params.get("deleteFiles") ?? "").toLowerCase() === "true";
    for (const hash of hashes) {
      const torrent = state.torrents.find((t) => t.hash === hash);
      if (torrent && deleteFiles) {
        for (const file of state.files[hash] ?? []) {
          fs.rmSync(path.join(torrent.save_path, file.name), { force: true });
        }
      }
      state.deleted.push({ hash, deleteFiles });
      state.torrents = state.torrents.filter((t) => t.hash !== hash);
    }
    return send(res, 200, "");
  }

  return send(res, 404, `No fake route for ${route}`);
});

server.listen(PORT, "127.0.0.1", () => {
  process.stdout.write(`fake-qbittorrent listening on http://127.0.0.1:${PORT}\n`);
});
