"use client";

import { getApiBase, readToken } from "@agrayian/sdk";

export function subscribeAutonomyEvents(onMessage: () => void): () => void {
  const token = readToken();
  if (!token || typeof window === "undefined") {
    return () => undefined;
  }
  const controller = new AbortController();
  void fetch(`${getApiBase()}/api/v1/autonomy/events`, {
    headers: { Authorization: `Bearer ${token}`, Accept: "text/event-stream" },
    credentials: "include",
    signal: controller.signal,
  })
    .then(async (response) => {
      if (!response.ok || !response.body) {
        return;
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (!controller.signal.aborted) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        if (buffer.includes("data:")) {
          onMessage();
          buffer = "";
        }
      }
    })
    .catch(() => undefined);
  return () => controller.abort();
}
