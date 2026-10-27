/** Runs inside the page. Observe the actual UI fetch through a bounded clone,
 * independent of Chromium's DevTools response-body retention. No extra request. */
export function installVariantObservation() {
  const original = globalThis.fetch;
  globalThis.fetch = async function (...args) {
    const input = args[0];
    const url = new URL(typeof input === 'string' ? input : input.url ?? String(input), globalThis.location.href);
    if (url.pathname !== '/api/live-design/variants') return original.apply(this, args);
    const record = globalThis.__variantWire = { url: url.href, startedAtMs: performance.now(), done: false, outcome: null, error: null };
    try {
      const response = await original.apply(this, args);
      record.status = response.status;
      const copy = response.clone();
      void (async () => {
        let reader;
        try {
          if (!response.ok || !copy.body) throw new Error(`Stream HTTP ${response.status}`);
          reader = copy.body.getReader();
          const decoder = new TextDecoder('utf-8', { fatal: true });
          let pending = '', bytes = 0, count = 0;
          for (;;) {
            const next = await reader.read();
            if (next.done) { pending += decoder.decode(); break; }
            bytes += next.value.byteLength;
            if (bytes > 4 * 1024 * 1024) throw new Error('Observer stream byte limit');
            pending += decoder.decode(next.value, { stream: true });
            let end;
            while ((end = pending.indexOf('\n')) >= 0) {
              const line = pending.slice(0, end); pending = pending.slice(end + 1);
              if (!line) continue;
              if (++count > 32 || new TextEncoder().encode(line).length > 524288) throw new Error('Observer event limit');
              const event = JSON.parse(line);
              if (record.outcome) throw new Error('Event after completion');
              if (event.type === 'complete') record.outcome = event;
            }
            if (new TextEncoder().encode(pending).length > 524288) throw new Error('Observer event byte limit');
          }
          if (pending.trim() || !record.outcome) throw new Error('Observer stream interrupted before completion');
        } catch (error) {
          record.error = String(error);
          // Cancellation must not wait for the UI branch of the tee to finish.
          if (reader) void reader.cancel().catch(() => {});
        } finally { record.done = true; }
      })();
      return response;
    } catch (error) {
      record.error = String(error); record.done = true; throw error;
    }
  };
  globalThis.addEventListener('click', event => {
    if (event.target?.closest?.('.generate-button')) globalThis.__variantGenerateAt = performance.now();
  }, { capture: true });
}
