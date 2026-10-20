// Recordings waiting to upload (voice-dictation: a recording survives a lost connection).
// IndexedDB keeps them across reloads; without it (private mode, tests) they live in memory.
export type Pending = { key: string; chunks: Blob[]; mime: string; seconds: number };

export interface PendingStore {
  put(p: Pending): Promise<void>;
  all(): Promise<Pending[]>;
  remove(key: string): Promise<void>;
}

export function memoryStore(): PendingStore {
  const items = new Map<string, Pending>();
  return {
    put: async (p) => void items.set(p.key, p),
    all: async () => [...items.values()],
    remove: async (key) => void items.delete(key),
  };
}

function idbStore(): PendingStore {
  const open = () =>
    new Promise<IDBDatabase>((resolve, reject) => {
      const req = indexedDB.open("kb-dictations", 1);
      req.onupgradeneeded = () => req.result.createObjectStore("pending", { keyPath: "key" });
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  const run = async <T>(mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<T>) => {
    const db = await open();
    return new Promise<T>((resolve, reject) => {
      const req = fn(db.transaction("pending", mode).objectStore("pending"));
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  };
  return {
    put: async (p) => void (await run("readwrite", (s) => s.put(p))),
    all: () => run<Pending[]>("readonly", (s) => s.getAll() as IDBRequest<Pending[]>),
    remove: async (key) => void (await run("readwrite", (s) => s.delete(key))),
  };
}

let store: PendingStore | null = null;

export function pendingStore(): PendingStore {
  if (!store) store = typeof indexedDB === "undefined" ? memoryStore() : idbStore();
  return store;
}

export function setPendingStore(s: PendingStore | null) {
  store = s;
}

// Uploads one recording; the server answers with the dictation id.
export async function upload(p: Pending): Promise<number> {
  const r = await fetch(`/api/dictations?seconds=${Math.round(p.seconds * 10) / 10}`, {
    method: "POST",
    headers: { "X-KB-Request": "1", "Content-Type": p.mime },
    credentials: "same-origin",
    body: new Blob(p.chunks, { type: p.mime }),
  });
  const data = (await r.json().catch(() => ({}))) as { id?: number; detail?: string };
  if (!r.ok || !data.id) throw new Error(data.detail ?? `upload failed (${r.status})`);
  return data.id;
}

// Tries every waiting recording; returns the ids the server accepted (the rest stay) and the
// last error, so the owner sees why a recording is still waiting.
export async function flush(
  onUploaded?: (key: string, id: number) => void,
): Promise<{ ids: number[]; error: string | null }> {
  const s = pendingStore();
  const ids: number[] = [];
  let error: string | null = null;
  for (const p of await s.all()) {
    try {
      const id = await upload(p);
      await s.remove(p.key);
      ids.push(id);
      onUploaded?.(p.key, id);
    } catch (e) {
      // offline or server error: keep it for the next attempt
      error = e instanceof TypeError ? "offline" : (e as Error).message;
    }
  }
  return { ids, error };
}
