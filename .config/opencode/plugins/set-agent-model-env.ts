import type { Plugin } from "@opencode-ai/plugin"

async function getModelName(client: ReturnType<typeof import("@opencode-ai/plugin")["createOpencodeClient"]>, sessionID: string): Promise<string | undefined> {
  try {
    const messages = await client.session.messages({
      path: { id: sessionID },
      query: { limit: 50 },
    })

    // Messages are newest-first after reverse(), findLast gets the latest
    const lastMessage = messages.data.findLast(
      (m) => m.info?.model,
    )

    if (lastMessage?.info.model) {
      const { modelID } = lastMessage.info.model
      return `${modelID}`
    }
  } catch (error) {
    console.error("Failed to get model:", error)
  }
  return undefined
}

function hasGitCommit(parts: any[]): boolean {
  return parts.some((p) => {
    if (p.type !== "tool" || p.tool !== "bash") return false
    const status = p.state?.status;
    if (status === "running") {
      return false;
    }
    const command = p.state?.input?.command?.toLowerCase() ?? ""
    return command.includes("git commit")
  })
}

async function getPromptsUntilGitCommit(client: ReturnType<typeof import("@opencode-ai/plugin")["createOpencodeClient"]>, sessionID: string): Promise<string | undefined> {
  try {
    const messagesResponse = await client.session.messages({
      path: { id: sessionID },
      query: { limit: 100 },
    });

    const prompts: string[] = []

    const messagesAsc = messagesResponse.data; // in ASC order
    const messagesDesc = messagesAsc.reverse(); // in DESC order

    for (const msg of messagesDesc) {
      // Stop at completed 'git commit'.
      if (msg.info.role === "assistant" && msg.parts && hasGitCommit(msg.parts)) {
        break;
      }

      // Collect user prompts
      if (msg.info.role === "user" && msg.parts) {
        const textParts = msg.parts.filter((p: any) => p.type === "text")
        if (textParts.length > 0) {
          prompts.push((textParts[0] as any).text)
        }
      }
    }

    if (prompts.length === 0) {
      return undefined;
    }

    return prompts.reverse().join("\n----\n");
  } catch (error) {
    console.error("Failed to get prompts:", error)
  }
  return undefined
}

export const SetAgentModelEnv: Plugin = async ({ client }) => {
  return {
    "shell.env": async (input, output) => {
      if (input.sessionID) {
        const modelName = await getModelName(client, input.sessionID)
        if (modelName) {
          output.env.AGENT_MODEL = modelName
        }

        const prompts = await getPromptsUntilGitCommit(client, input.sessionID)
        if (prompts) {
          output.env.AGENT_PROMPT = prompts
        }
      }
    },
  }
}
