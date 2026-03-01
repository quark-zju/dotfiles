import type { Plugin } from "@opencode-ai/plugin"

async function getModelName(client: ReturnType<typeof import("@opencode-ai/plugin")["createOpencodeClient"]>, sessionID: string): Promise<string | undefined> {
  try {
    const messages = await client.session.messages({
      path: { id: sessionID },
      query: { limit: 100 },
    })

    // Messages are newest-first after reverse(), findLast gets the latest
    const latestUserMessage = messages.data.findLast(
      (m) => m.info.role === "user" && m.info.model,
    )

    if (latestUserMessage?.info.model) {
      const { providerID, modelID } = latestUserMessage.info.model
      return `${providerID}/${modelID}`
    }
  } catch (error) {
    console.error("Failed to get model:", error)
  }
  return undefined
}

function hasGitCommit(parts: any[]): boolean {
  return parts.some((p) => {
    if (p.type !== "tool") return false
    const toolParts = p.state?.content || []
    return toolParts.some((tp: any) => {
      if (tp.type !== "text") return false
      const text = tp.text?.toLowerCase() || ""
      return text.includes("git") && (text.includes("commit") || text.includes("push"))
    })
  })
}

async function getPromptsUntilGitCommit(client: ReturnType<typeof import("@opencode-ai/plugin")["createOpencodeClient"]>, sessionID: string): Promise<string | undefined> {
  try {
    const messages = await client.session.messages({
      path: { id: sessionID },
      query: { limit: 100 },
    })

    const prompts: string[] = []

    // Messages are newest-first, iterate from newest to oldest
    for (const msg of messages.data) {
      // Check if this assistant message contains a git commit bash call
      if (msg.info.role === "assistant" && msg.parts && hasGitCommit(msg.parts)) {
        break // Stop at git commit/push
      }

      // Collect user prompts
      if (msg.info.role === "user" && msg.parts) {
        const textParts = msg.parts.filter((p: any) => p.type === "text")
        if (textParts.length > 0) {
          prompts.push((textParts[0] as any).text)
        }
      }
    }

    return prompts.length > 0 ? prompts.join("\n----\n") : undefined
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
