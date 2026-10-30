/**
 * A Radarr or Sonarr, reduced to the endpoints Deduparr calls.
 *
 * Deduparr talks to the *arr APIs over httpx directly, so this only has to be
 * faithful to the v3 shapes it reads. State is in memory and a POST /reset
 * puts it back, so a test can assert on what Deduparr did.
 *
 * Deleting a file removes it from disk, as the real ones do.
 *
 * Env: PORT, FLAVOUR=radarr|sonarr, API_KEY, MEDIA_DIR
 */

import fs from "fs";
import http from "http";

const PORT = Number(process.env.PORT ?? 7878);
const FLAVOUR = process.env.FLAVOUR ?? "radarr";
const API_KEY = process.env.API_KEY ?? "fake-arr-key";
const MEDIA_DIR = process.env.MEDIA_DIR ?? "/tmp/fake-media";

/** Everything the server pretends to hold, and what Deduparr asked of it. */
let state = {};

/** The fake Jellyfin's default duplicate; /reset can name another title. */
const DEFAULT_TITLE = "Fake Duplicate (2024)";

function reset(title = DEFAULT_TITLE) {
  const movieDir = `${MEDIA_DIR}/Movies/${title}`;
  const seasonDir = `${MEDIA_DIR}/Shows/Fake Show/Season 1`;
  state = {
    movies: [
      {
        id: 1,
        title,
        qualityProfileId: 1,
        path: movieDir,
        movieFile: { id: 11, path: `${movieDir}/${title} 720p.mkv` },
      },
    ],
    movieFiles: [
      {
        id: 11,
        movieId: 1,
        path: `${movieDir}/${title} 720p.mkv`,
        quality: { quality: { id: 1, name: "720p" }, revision: { version: 1, real: 0 } },
        customFormatScore: 0,
      },
      {
        id: 12,
        movieId: 1,
        path: `${movieDir}/${title} 1080p.mkv`,
        quality: { quality: { id: 2, name: "1080p" }, revision: { version: 1, real: 0 } },
        customFormatScore: 10,
      },
    ],
    series: [
      { id: 1, title: "Fake Show", qualityProfileId: 1, path: `${MEDIA_DIR}/Shows/Fake Show` },
    ],
    episodeFiles: [
      {
        id: 21,
        seriesId: 1,
        seasonNumber: 1,
        path: `${seasonDir}/Fake Show - S01E02 480p.mkv`,
        quality: { quality: { id: 1, name: "480p" }, revision: { version: 1, real: 0 } },
      },
      {
        id: 22,
        seriesId: 1,
        seasonNumber: 1,
        path: `${seasonDir}/Fake Show - S01E02 1080p.mkv`,
        quality: { quality: { id: 2, name: "1080p" }, revision: { version: 1, real: 0 } },
      },
    ],
    qualityProfiles: [
      {
        id: 1,
        name: "Any",
        items: [
          { quality: { id: 1, name: "480p" } },
          { quality: { id: 2, name: "1080p" } },
          { quality: { id: 3, name: "2160p" } },
        ],
        formatItems: [],
      },
    ],
    // What Deduparr did, for a test to assert on
    deletedMovieFiles: [],
    deletedEpisodeFiles: [],
    commands: [],
  };
}
reset();

function json(res, status, body) {
  const payload = JSON.stringify(body);
  res.writeHead(status, {
    "Content-Type": "application/json",
    "Content-Length": Buffer.byteLength(payload),
  });
  res.end(payload);
}

function readBody(req) {
  return new Promise((resolve) => {
    let raw = "";
    req.on("data", (c) => (raw += c));
    req.on("end", () => {
      try {
        resolve(raw ? JSON.parse(raw) : {});
      } catch {
        resolve({});
      }
    });
  });
}

/** Drop a file from the catalogue and from disk. */
function removeFile(files, id) {
  const index = files.findIndex((f) => f.id === id);
  if (index === -1) return;
  fs.rmSync(files[index].path, { force: true });
  files.splice(index, 1);
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);
  const route = url.pathname.replace(/\/$/, "");

  if (route === "/reset" && req.method === "POST") {
    reset((await readBody(req)).title);
    return json(res, 200, { ok: true });
  }
  if (route === "/state") {
    return json(res, 200, state);
  }

  // Everything else needs the api key, as a real *arr does
  const key = req.headers["x-api-key"] ?? url.searchParams.get("apikey");
  if (key !== API_KEY) {
    return json(res, 401, { message: "Unauthorized" });
  }

  const v3 = route.replace(/^\/api\/v3/, "");

  if (v3 === "/system/status") {
    return json(res, 200, { version: "5.0.0.0", appName: FLAVOUR, instanceName: FLAVOUR });
  }
  if (v3 === "/rootfolder") {
    // Picked in the *arr's folder browser, a root folder keeps a trailing slash
    const folder = FLAVOUR === "sonarr" ? "Shows" : "Movies";
    return json(res, 200, [{ id: 1, path: `${MEDIA_DIR}/${folder}/` }]);
  }
  if (v3 === "/movie") {
    return json(res, 200, state.movies);
  }
  if (/^\/movie\/\d+$/.test(v3)) {
    const id = Number(v3.split("/").pop());
    const movie = state.movies.find((m) => m.id === id);
    if (req.method === "PUT") return json(res, 200, await readBody(req));
    return movie ? json(res, 200, movie) : json(res, 404, { message: "Not found" });
  }
  if (v3 === "/moviefile") {
    const movieId = Number(url.searchParams.get("movieId"));
    return json(
      res,
      200,
      state.movieFiles.filter((f) => !movieId || f.movieId === movieId)
    );
  }
  if (/^\/moviefile\/\d+$/.test(v3) && req.method === "DELETE") {
    const id = Number(v3.split("/").pop());
    removeFile(state.movieFiles, id);
    state.deletedMovieFiles.push(id);
    for (const movie of state.movies) {
      if (movie.movieFile?.id === id) delete movie.movieFile;
    }
    res.writeHead(200).end();
    return undefined;
  }
  if (v3 === "/series") {
    return json(res, 200, state.series);
  }
  if (/^\/series\/\d+$/.test(v3)) {
    const id = Number(v3.split("/").pop());
    if (req.method === "PUT") return json(res, 200, await readBody(req));
    const show = state.series.find((s) => s.id === id);
    return show ? json(res, 200, show) : json(res, 404, { message: "Not found" });
  }
  if (v3 === "/episodefile") {
    const seriesId = Number(url.searchParams.get("seriesId"));
    return json(
      res,
      200,
      state.episodeFiles.filter((f) => !seriesId || f.seriesId === seriesId)
    );
  }
  if (/^\/episodefile\/\d+$/.test(v3) && req.method === "DELETE") {
    const id = Number(v3.split("/").pop());
    removeFile(state.episodeFiles, id);
    state.deletedEpisodeFiles.push(id);
    res.writeHead(200).end();
    return undefined;
  }
  if (/^\/qualityprofile\/\d+$/.test(v3)) {
    const id = Number(v3.split("/").pop());
    const profile = state.qualityProfiles.find((p) => p.id === id);
    return profile ? json(res, 200, profile) : json(res, 404, { message: "Not found" });
  }
  if (v3 === "/parse") {
    const title = url.searchParams.get("title") ?? "";
    const index = ["480p", "1080p", "2160p"].findIndex((name) => title.includes(name));
    const quality = { id: index + 1, name: index < 0 ? "Unknown" : title.match(/\d+p/)[0] };
    return json(res, 200, {
      title,
      [FLAVOUR === "radarr" ? "parsedMovieInfo" : "parsedEpisodeInfo"]: {
        quality: { quality, revision: { version: 1, real: 0 } },
      },
      customFormats: [],
      customFormatScore: 0,
    });
  }
  if (v3 === "/command" && req.method === "POST") {
    const body = await readBody(req);
    state.commands.push(body);
    return json(res, 201, { id: state.commands.length, name: body.name, status: "queued" });
  }

  return json(res, 404, { message: `No fake route for ${route}` });
});

server.listen(PORT, "127.0.0.1", () => {
  process.stdout.write(`fake-${FLAVOUR} listening on http://127.0.0.1:${PORT}\n`);
});
