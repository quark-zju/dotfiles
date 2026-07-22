import type { Plugin } from "@opencode-ai/plugin";

/*
 * Secret patterns and behavior are derived from
 * https://github.com/casonadams/opencode-secret-redactor (version 0.5.1).
 *
 * MIT License
 * Copyright (c) 2026 Cason Adams
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in
 * all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 */

type SecretPattern = readonly [label: string, pattern: RegExp];

// Specific prefixes precede generic patterns so the placeholder stays useful.
const PATTERNS: readonly SecretPattern[] = [
	["gitlab_pat", /glpat-[A-Za-z0-9\-_]{20,}/g],
	["gitlab_pipeline_trigger", /glptt-[A-Za-z0-9\-_]{20,}/g],
	["gitlab_deploy_token", /gldt-[A-Za-z0-9\-_]{20,}/g],
	["gitlab_ci_job_token", /glcbt-[A-Za-z0-9\-_]{20,}/g],
	["gitlab_runner_token", /glrt-[A-Za-z0-9\-_]{20,}/g],
	["gitlab_service_account", /glsoat-[A-Za-z0-9\-_]{20,}/g],
	["gitlab_feed_token", /glft-[A-Za-z0-9\-_]{20,}/g],
	["gitlab_incoming_mail", /glimt-[A-Za-z0-9\-_]{20,}/g],
	["gitlab_oauth_secret", /gloas-[A-Za-z0-9\-_]{20,}/g],
	["gitlab_agent_token", /glagent-[A-Za-z0-9\-_]{20,}/g],
	["github_pat", /ghp_[A-Za-z0-9]{36,}/g],
	["github_oauth", /gho_[A-Za-z0-9]{36,}/g],
	["github_app_token", /ghu_[A-Za-z0-9]{36,}/g],
	["github_app_install", /ghs_[A-Za-z0-9]{36,}/g],
	["github_fine_grained", /github_pat_[A-Za-z0-9_]{22,}/g],
	["aws_access_key", /AKIA[0-9A-Z]{16}/g],
	[
		"aws_secret_key",
		/(?:aws_secret_access_key|AWS_SECRET_ACCESS_KEY|SecretAccessKey)[=:\s"']+([A-Za-z0-9/+=]{40})/g,
	],
	["anthropic_key", /sk-ant-[A-Za-z0-9\-_]{20,}/g],
	["openai_project_key", /sk-proj-[A-Za-z0-9\-_]{20,}/g],
	["openai_key", /sk-(?!ant-)(?!proj-)[A-Za-z0-9]{20,}/g],
	["cohere_key", /co-[A-Za-z0-9]{30,}/g],
	["huggingface_token", /hf_[A-Za-z0-9]{30,}/g],
	["google_api_key", /AIza[0-9A-Za-z\-_]{35}/g],
	["google_oauth_secret", /GOCSPX-[A-Za-z0-9\-_]{28}/g],
	["gcloud_access_token", /ya29\.[A-Za-z0-9\-_]{50,}/g],
	["google_refresh_token", /1\/\/[A-Za-z0-9\-_]{40,}/g],
	["digitalocean_pat", /dop_v1_[a-f0-9]{64}/g],
	["digitalocean_oauth", /doo_v1_[a-f0-9]{64}/g],
	["hashicorp_vault", /hvs\.[A-Za-z0-9]{24,}/g],
	[
		"heroku_api_key",
		/(?:HEROKU_API_KEY|heroku_api_key)[=:\s"']+([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/g,
	],
	["vercel_token", /vercel_[A-Za-z0-9]{24,}/g],
	["slack_token", /xox[bpors]-[A-Za-z0-9-]{10,}/g],
	[
		"slack_webhook",
		/hooks\.slack\.com\/services\/T[A-Z0-9]+\/B[A-Z0-9]+\/[A-Za-z0-9]+/g,
	],
	["twilio_api_key", /SK[a-f0-9]{32}/g],
	["sendgrid_key", /SG\.[A-Za-z0-9\-_]{22,}\.[A-Za-z0-9\-_]{22,}/g],
	["postman_key", /PMAK-[A-Za-z0-9-]{50,}/g],
	["datadog_api_key", /dd[a-z]{1,2}_[A-Za-z0-9]{32,40}/g],
	["stripe_secret", /sk_(?:test|live)_[A-Za-z0-9]{10,}/g],
	["stripe_restricted", /rk_(?:test|live)_[A-Za-z0-9]{10,}/g],
	["stripe_webhook", /whsec_[A-Za-z0-9]{32,}/g],
	["square_access_token", /sq0atp-[A-Za-z0-9\-_]{22,}/g],
	["square_oauth", /sq0csp-[A-Za-z0-9\-_]{43}/g],
	["npm_token", /npm_[A-Za-z0-9]{36,}/g],
	["pypi_token", /pypi-[A-Za-z0-9\-_]{50,}/g],
	["rubygems_key", /rubygems_[A-Za-z0-9]{48}/g],
	["jwt", /eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}/g],
	["bearer_token", /Bearer\s+[A-Za-z0-9\-._~+/]+=*/g],
	["basic_auth", /Basic\s+[A-Za-z0-9+/]{10,}={0,2}/g],
	[
		"private_key",
		/-----BEGIN\s+(?:RSA\s+|EC\s+|ED25519\s+|DSA\s+)?PRIVATE\s+KEY-----[\s\S]*?-----END\s+(?:RSA\s+|EC\s+|ED25519\s+|DSA\s+)?PRIVATE\s+KEY-----/g,
	],
	[
		"database_url",
		/(?:postgres|postgresql|mysql|mongodb|mongodb\+srv|redis):\/\/[^:\s]+:[^@\s]+@[^\s]+/g,
	],
	["sentry_dsn", /https:\/\/[a-f0-9]{32}@[^\s/]+\.ingest\.sentry\.io\/[0-9]+/g],
	["grafana_api_key", /glc_[A-Za-z0-9\-_]{32,}/g],
	["doppler_token", /dp\.st\.[A-Za-z0-9_-]{40,}/g],
	[
		"azure_connection_string",
		/DefaultEndpointsProtocol=https?;AccountName=[^;\s]+;AccountKey=[A-Za-z0-9+/]{86}==[^\s"']*/g,
	],
	["azure_storage_key", /AccountKey=([A-Za-z0-9+/]{86}==)/g],
	["azure_sas_token", /[?&]sig=([A-Za-z0-9%+/=]{40,})/g],
	["shopify_access_token", /shpat_[a-fA-F0-9]{20,}/g],
	["shopify_custom_app", /shpca_[a-fA-F0-9]{20,}/g],
	["shopify_private_app", /shppa_[a-fA-F0-9]{20,}/g],
	["shopify_shared_secret", /shpss_[a-fA-F0-9]{20,}/g],
	["mailgun_api_key", /key-[a-z0-9]{30,}/g],
	["mailchimp_api_key", /[a-f0-9]{32}-us\d{1,2}/g],
	["linear_api_key", /lin_api_[A-Za-z0-9]{40,}/g],
	["terraform_cloud_token", /[A-Za-z0-9]{14}\.atlasv1\.[A-Za-z0-9\-_]{60,}/g],
	["pulumi_token", /pul-[a-f0-9]{40}/g],
	["docker_pat", /dckr_pat_[A-Za-z0-9\-_]{24,}/g],
	["age_secret_key", /AGE-SECRET-KEY-1[A-Za-z0-9]{58}/g],
	["ssh_public_key", /ssh-(?:rsa|ed25519|dss)\s+[A-Za-z0-9+/]{60,}={0,2}/g],
	[
		"ssh_ecdsa_key",
		/ecdsa-sha2-nistp(?:256|384|521)\s+[A-Za-z0-9+/]{60,}={0,2}/g,
	],
	["email", /(?<![:/])[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/g],
	[
		"credit_card",
		/\b(?:4[0-9]{3}|5[1-5][0-9]{2}|3[47][0-9]{2}|6(?:011|5[0-9]{2}))[-\s]?[0-9]{4}[-\s]?[0-9]{4}[-\s]?[0-9]{3,4}\b/g,
	],
	["us_ssn", /\b\d{3}-\d{2}-\d{4}\b/g],
	["phone_us", /\+1[-.\s]?\(?[2-9]\d{2}\)?[-.\s]?[2-9]\d{2}[-.\s]?\d{4}/g],
	[
		"env_secret",
		/(?:PASSWORD|PASSWD|SECRET|API_KEY|PRIVATE_KEY|ACCESS_KEY|AUTH_TOKEN|ENCRYPTION_KEY|SIGNING_KEY|DB_PASSWORD|DATABASE_PASSWORD)\s*[=:]\s*["']?([^\s"']{8,})["']?/gi,
	],
];

const REDACT_OUTPUT_TOOLS = new Set(["bash", "read", "grep", "webfetch"]);
const UNREDACT_ARGS_TOOLS = new Set(["bash", "write", "edit"]);

interface Vault {
	tokenByValue: Map<string, string>;
	valueByToken: Map<string, string>;
	nextTokenID: number;
}

function replaceAll(
	text: string,
	replacements: ReadonlyMap<string, string>,
): string {
	let result = text;
	for (const [from, to] of replacements) result = result.split(from).join(to);
	return result;
}

function redactString(
	text: string,
	vault: Vault,
): { text: string; labels: string[] } {
	let result = replaceAll(text, vault.tokenByValue);
	const labels: string[] = [];
	const seen = new Set<string>();

	for (const [type, pattern] of PATTERNS) {
		const regex = new RegExp(pattern.source, pattern.flags);
		for (
			let match = regex.exec(result);
			match !== null;
			match = regex.exec(result)
		) {
			const value = match[1] ?? match[0];
			if (value.length < 8 || seen.has(value) || vault.tokenByValue.has(value))
				continue;

			seen.add(value);
			const label = `${type}_${vault.nextTokenID++}`;
			const token = `🔒${label}🔓`;
			vault.tokenByValue.set(value, token);
			vault.valueByToken.set(token, value);
			labels.push(label);
		}
	}

	result = replaceAll(result, vault.tokenByValue);
	return { text: result, labels };
}

function mapStrings(
	value: unknown,
	transform: (text: string) => string,
): unknown {
	if (typeof value === "string") return transform(value);
	if (Array.isArray(value))
		return value.map((item) => mapStrings(item, transform));
	if (typeof value !== "object" || value === null) return value;

	return Object.fromEntries(
		Object.entries(value).map(([key, item]) => [
			key,
			mapStrings(item, transform),
		]),
	);
}

function redactDeep(
	value: unknown,
	vault: Vault,
): { value: unknown; labels: string[] } {
	const labels: string[] = [];
	const redacted = mapStrings(value, (text) => {
		const result = redactString(text, vault);
		labels.push(...result.labels);
		return result.text;
	});
	return { value: redacted, labels };
}

function redactParts(
	parts: Array<{ type: string; text?: string }>,
	vault: Vault,
): string[] {
	const labels: string[] = [];
	for (const part of parts) {
		if (part.type !== "text" || typeof part.text !== "string") continue;
		const result = redactString(part.text, vault);
		part.text = result.text;
		labels.push(...result.labels);
	}
	return labels;
}

function secretTypes(labels: readonly string[]): string {
	return [...new Set(labels.map((label) => label.replace(/_\d+$/, "")))].join(
		", ",
	);
}

export const SecretRedactor: Plugin = async ({ client }) => {
	const vault: Vault = {
		tokenByValue: new Map(),
		valueByToken: new Map(),
		nextTokenID: 1,
	};
	const warn = (message: string) => {
		client.tui
			.showToast({ body: { message, variant: "warning" } })
			.catch(() => {});
	};

	return {
		"chat.message": async (_input, output) => {
			const labels = redactParts(output.parts, vault);
			if (labels.length)
				warn(
					`Redacted ${labels.length} secret(s) from chat: ${secretTypes(labels)}`,
				);
		},

		"experimental.chat.messages.transform": async (_input, output) => {
			const labels = output.messages.flatMap((message) =>
				redactParts(message.parts, vault),
			);
			if (labels.length)
				warn(`Redacted ${labels.length} secret(s) from LLM context`);
		},

		"tool.execute.before": async (input, output) => {
			if (!UNREDACT_ARGS_TOOLS.has(input.tool)) return;
			for (const key of Object.keys(output.args)) {
				output.args[key] = mapStrings(output.args[key], (text) =>
					replaceAll(text, vault.valueByToken),
				);
			}
		},

		"tool.execute.after": async (input, output) => {
			if (!REDACT_OUTPUT_TOOLS.has(input.tool) || output.output == null) return;
			const result = redactDeep(output.output, vault);
			output.output = result.value as string;
			if (result.labels.length) {
				warn(
					`Redacted ${result.labels.length} secret(s) from ${input.tool}: ${secretTypes(result.labels)}`,
				);
			}
		},
	};
};

export default SecretRedactor;
