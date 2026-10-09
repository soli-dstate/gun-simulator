// How the page talks to Python. In the desktop app (pywebview) it calls
// window.pywebview.api directly; in the --browser fallback it uses the local
// HTTP server that served the page.

async function unwrap(promise) {
  const data = await promise;
  if (data && data.error) throw new Error(data.error);
  return data;
}

function desktopBackend(api) {
  return {
    desktop: true,
    schema: () => unwrap(api.schema()),
    simulate: (payload) => unwrap(api.simulate(payload)),
    cycle: (payload) => unwrap(api.cycle(payload)),
    synthesize: (payload) => unwrap(api.synthesize(payload)),
    plume: (payload) => unwrap(api.plume(payload)),
    trajectory: (payload) => unwrap(api.trajectory(payload)),
    parse: (text) => unwrap(api.parse(text)),
    /** Returns the saved path, or null if the user cancelled. */
    saveToml: async (text, filename) => (await unwrap(api.save_toml(text, filename))).path,
  };
}

async function http(path, body) {
  const res = await fetch(path, body === undefined ? undefined : { method: "POST", body });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error);
  return data;
}

const httpBackend = {
  desktop: false,
  schema: () => http("api/schema"),
  simulate: (payload) => http("api/simulate", JSON.stringify(payload)),
  cycle: (payload) => http("api/cycle", JSON.stringify(payload)),
  synthesize: (payload) => http("api/synthesize", JSON.stringify(payload)),
  plume: (payload) => http("api/plume", JSON.stringify(payload)),
  trajectory: (payload) => http("api/trajectory", JSON.stringify(payload)),
  parse: (text) => http("api/parse", text),
  saveToml: async (text, filename) => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type: "application/toml" }));
    a.download = filename;
    a.click();
    URL.revokeObjectURL(a.href);
    return filename;
  },
};

/** Resolves with whichever backend is present. */
export function connect() {
  if (window.pywebview?.api?.schema) return Promise.resolve(desktopBackend(window.pywebview.api));
  return new Promise((resolve, reject) => {
    window.addEventListener("pywebviewready", () => resolve(desktopBackend(window.pywebview.api)), { once: true });
    // Only the --browser server answers this; inside the desktop app it 404s and we keep waiting.
    fetch("api/schema")
      .then((r) => { if (r.ok) resolve(httpBackend); })
      .catch(() => {});
    setTimeout(() => reject(new Error("Could not reach the simulator. Is the app still running?")), 15000);
  });
}
