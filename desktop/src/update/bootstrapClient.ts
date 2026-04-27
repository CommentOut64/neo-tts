export const DEFAULT_BOOTSTRAP_CONTROL_API_VERSION = "v1";

export interface BootstrapMetaResponse {
	apiVersion: string;
	bootstrapVersion: string;
	sessionId: string;
}

export interface CheckForUpdateRequest {
	channel: string;
	automatic: boolean;
}

export interface CheckForUpdateResponse {
	status: string;
	releaseId?: string;
	notesUrl?: string;
	changedPackages?: string[];
	estimatedDownloadBytes?: number;
	minBootstrapVersion?: string;
	progress?: {
		totalPackages: number;
		completedPackages: number;
		currentPackageId?: string;
		currentPackageVersion?: string;
		currentPackageBytes?: number;
		currentPackageTotal?: number;
	};
	errorCode?: string;
	errorMessage?: string;
}

export interface DownloadUpdateRequest {
	releaseId?: string;
}

export interface DownloadUpdateResponse {
	status: string;
	releaseId?: string;
	progress?: {
		totalPackages: number;
		completedPackages: number;
		currentPackageId?: string;
		currentPackageVersion?: string;
		currentPackageBytes?: number;
		currentPackageTotal?: number;
	};
	errorCode?: string;
	message?: string;
}

export interface RestartAndApplyUpdateRequest {
	releaseId?: string;
}

export interface RestartAndApplyUpdateResponse {
	status: string;
	releaseId?: string;
}

export interface SessionEventRequest {
	sessionId: string;
	code?: string;
	message?: string;
}

export interface SessionEventResponse {
	status: string;
}

export interface BootstrapControlClient {
	origin: string;
	apiVersion: string;
	bootstrapVersion: string;
	sessionId: string;
	checkForUpdate(request: CheckForUpdateRequest): Promise<CheckForUpdateResponse>;
	downloadUpdate(request: DownloadUpdateRequest): Promise<DownloadUpdateResponse>;
	restartAndApplyUpdate(request: RestartAndApplyUpdateRequest): Promise<RestartAndApplyUpdateResponse>;
	reportSessionReady(request: SessionEventRequest): Promise<SessionEventResponse>;
	reportSessionFailed(request: SessionEventRequest): Promise<SessionEventResponse>;
	reportRestartForUpdate(request: SessionEventRequest): Promise<SessionEventResponse>;
}

export interface ConnectBootstrapControlClientOptions {
	origin: string;
	expectedAPIVersion?: string;
	fetchImpl?: typeof fetch;
}

export interface ConnectBootstrapControlFromEnvironmentOptions {
	env?: NodeJS.ProcessEnv;
	fetchImpl?: typeof fetch;
}

export class BootstrapControlError extends Error {
	code: string;
	details?: Record<string, unknown>;
	statusCode?: number;

	constructor(options: {
		code: string;
		message: string;
		details?: Record<string, unknown>;
		statusCode?: number;
		cause?: unknown;
	}) {
		super(options.message, options.cause === undefined ? undefined : { cause: options.cause });
		this.name = "BootstrapControlError";
		this.code = options.code;
		this.details = options.details;
		this.statusCode = options.statusCode;
	}
}

export async function connectBootstrapControlFromEnvironment(
	options: ConnectBootstrapControlFromEnvironmentOptions = {},
): Promise<BootstrapControlClient | null> {
	const env = options.env ?? process.env;
	const origin = env.NEO_TTS_BOOTSTRAP_CONTROL_ORIGIN?.trim() ?? "";
	if (origin.length === 0) {
		return null;
	}

	return connectBootstrapControlClient({
		origin,
		expectedAPIVersion:
			env.NEO_TTS_BOOTSTRAP_API_VERSION?.trim() || DEFAULT_BOOTSTRAP_CONTROL_API_VERSION,
		fetchImpl: options.fetchImpl,
	});
}

export async function connectBootstrapControlClient(
	options: ConnectBootstrapControlClientOptions,
): Promise<BootstrapControlClient> {
	const fetchImpl = options.fetchImpl ?? fetch;
	const origin = normalizeOrigin(options.origin);
	const expectedAPIVersion =
		options.expectedAPIVersion?.trim() || DEFAULT_BOOTSTRAP_CONTROL_API_VERSION;

	const meta = await requestJSON<BootstrapMetaResponse>({
		fetchImpl,
		url: `${origin}/v1/meta`,
		method: "GET",
	});
	if (meta.apiVersion !== expectedAPIVersion) {
		throw new BootstrapControlError({
			code: "api-version-mismatch",
			message: `bootstrap api version mismatch: expected ${expectedAPIVersion}, got ${meta.apiVersion}`,
			details: {
				expected: expectedAPIVersion,
				actual: meta.apiVersion,
				origin,
			},
		});
	}

	return {
		origin,
		apiVersion: meta.apiVersion,
		bootstrapVersion: meta.bootstrapVersion,
		sessionId: meta.sessionId,
		checkForUpdate: (request) =>
			requestJSON<CheckForUpdateResponse>({
				fetchImpl,
				url: `${origin}/v1/update/check`,
				method: "POST",
				body: request,
			}),
		downloadUpdate: (request) =>
			requestJSON<DownloadUpdateResponse>({
				fetchImpl,
				url: `${origin}/v1/update/download`,
				method: "POST",
				body: request,
			}),
		restartAndApplyUpdate: (request) =>
			requestJSON<RestartAndApplyUpdateResponse>({
				fetchImpl,
				url: `${origin}/v1/update/restart`,
				method: "POST",
				body: request,
			}),
		reportSessionReady: (request) =>
			requestJSON<SessionEventResponse>({
				fetchImpl,
				url: `${origin}/v1/session/ready`,
				method: "POST",
				body: request,
			}),
		reportSessionFailed: (request) =>
			requestJSON<SessionEventResponse>({
				fetchImpl,
				url: `${origin}/v1/session/failed`,
				method: "POST",
				body: request,
			}),
		reportRestartForUpdate: (request) =>
			requestJSON<SessionEventResponse>({
				fetchImpl,
				url: `${origin}/v1/session/restart-for-update`,
				method: "POST",
				body: request,
			}),
	};
}

async function requestJSON<T>(options: {
	fetchImpl: typeof fetch;
	url: string;
	method: "GET" | "POST";
	body?: unknown;
}): Promise<T> {
	const response = await options.fetchImpl(options.url, {
		method: options.method,
		headers:
			options.method === "POST"
				? {
						"Content-Type": "application/json",
					}
				: undefined,
		body:
			options.method === "POST" && options.body !== undefined
				? JSON.stringify(options.body)
				: undefined,
	});

	const contentType = response.headers.get("content-type") ?? "";
	const payload =
		contentType.includes("application/json") && response.status !== 204
			? await response.json()
			: null;

	if (!response.ok) {
		const errorPayload =
			payload && typeof payload === "object" && !Array.isArray(payload)
				? (payload as Record<string, unknown>)
				: {};
		throw new BootstrapControlError({
			code:
				typeof errorPayload.code === "string" && errorPayload.code.length > 0
					? errorPayload.code
					: "bootstrap-control-request-failed",
			message:
				typeof errorPayload.message === "string" && errorPayload.message.length > 0
					? errorPayload.message
					: `bootstrap control request failed: ${response.status}`,
			details:
				errorPayload.details && typeof errorPayload.details === "object"
					? (errorPayload.details as Record<string, unknown>)
					: undefined,
			statusCode: response.status,
		});
	}

	return payload as T;
}

function normalizeOrigin(origin: string): string {
	return origin.trim().replace(/\/+$/, "");
}
