import http from "node:http";

import { afterEach, describe, expect, it } from "vitest";

import {
  BootstrapControlError,
  connectBootstrapControlClient,
  connectBootstrapControlFromEnvironment,
} from "../src/update/bootstrapClient";

type ServerHandle = {
  origin: string;
  close: () => Promise<void>;
};

async function startServer(handler: http.RequestListener): Promise<ServerHandle> {
  const server = http.createServer(handler);
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", () => resolve()));
  const address = server.address();
  if (!address || typeof address === "string") {
    throw new Error("server address is unavailable");
  }
  return {
    origin: `http://127.0.0.1:${String(address.port)}`,
    close: async () => {
      await new Promise<void>((resolve, reject) => {
        server.close((error) => {
          if (error) {
            reject(error);
            return;
          }
          resolve();
        });
      });
    },
  };
}

describe("bootstrap control client", () => {
  const servers: Array<ServerHandle> = [];

  afterEach(async () => {
    while (servers.length > 0) {
      await servers.pop()?.close?.();
    }
  });

  it("negotiates /v1/meta and exposes bootstrap session metadata", async () => {
    const server = await startServer((request, response) => {
      if (request.method !== "GET" || request.url !== "/v1/meta") {
        response.statusCode = 404;
        response.end();
        return;
      }
      response.setHeader("Content-Type", "application/json");
      response.end(JSON.stringify({
        apiVersion: "v1",
        bootstrapVersion: "1.1.0",
        sessionId: "session-1",
      }));
    });
    servers.push(server);

    const client = await connectBootstrapControlClient({
      origin: server.origin,
      expectedAPIVersion: "v1",
      fetchImpl: fetch,
    });

    expect(client.apiVersion).toBe("v1");
    expect(client.bootstrapVersion).toBe("1.1.0");
    expect(client.sessionId).toBe("session-1");
  });

  it("forwards update and session event requests to bootstrap control API", async () => {
    const received: Array<{ method: string; url: string; body: string }> = [];
    const server = await startServer((request, response) => {
      if (request.url === "/v1/meta") {
        response.setHeader("Content-Type", "application/json");
        response.end(JSON.stringify({
          apiVersion: "v1",
          bootstrapVersion: "1.1.0",
          sessionId: "session-2",
        }));
        return;
      }

      let body = "";
      request.on("data", (chunk) => {
        body += String(chunk);
      });
      request.on("end", () => {
        received.push({
          method: request.method ?? "",
          url: request.url ?? "",
          body,
        });
        response.setHeader("Content-Type", "application/json");
        if (request.url === "/v1/update/check") {
          response.end(JSON.stringify({ status: "update-available", releaseId: "v0.0.2" }));
          return;
        }
        if (request.url === "/v1/session/ready") {
          response.end(JSON.stringify({ status: "session-ready" }));
          return;
        }
        response.statusCode = 404;
        response.end();
      });
    });
    servers.push(server);

    const client = await connectBootstrapControlClient({
      origin: server.origin,
      expectedAPIVersion: "v1",
      fetchImpl: fetch,
    });

    await expect(client.checkForUpdate({ channel: "stable", automatic: false })).resolves.toEqual({
      status: "update-available",
      releaseId: "v0.0.2",
    });
    await expect(client.reportSessionReady({ sessionId: "session-2" })).resolves.toEqual({
      status: "session-ready",
    });

    expect(received).toEqual([
      {
        method: "POST",
        url: "/v1/update/check",
        body: JSON.stringify({ channel: "stable", automatic: false }),
      },
      {
        method: "POST",
        url: "/v1/session/ready",
        body: JSON.stringify({ sessionId: "session-2" }),
      },
    ]);
  });

  it("returns null when bootstrap control origin is absent from environment", async () => {
    const client = await connectBootstrapControlFromEnvironment({
      env: {},
      fetchImpl: fetch,
    });

    expect(client).toBeNull();
  });

  it("throws api-version-mismatch when bootstrap meta version is incompatible", async () => {
    const server = await startServer((_request, response) => {
      response.setHeader("Content-Type", "application/json");
      response.end(JSON.stringify({
        apiVersion: "v2",
        bootstrapVersion: "2.0.0",
        sessionId: "session-3",
      }));
    });
    servers.push(server);

    await expect(connectBootstrapControlClient({
      origin: server.origin,
      expectedAPIVersion: "v1",
      fetchImpl: fetch,
    })).rejects.toMatchObject({
      code: "api-version-mismatch",
    } satisfies Partial<BootstrapControlError>);
  });
});
