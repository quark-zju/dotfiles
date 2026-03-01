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

async function getLastUserPrompt(client: ReturnType<typeof import("@opencode-ai/plugin")["createOpencodeClient"]>, sessionID: string): Promise<string | undefined> {
  try {
    const messages = await client.session.messages({
      path: { id: sessionID },
      query: { limit: 100 },
    })

    // Messages are newest-first, findLast gets the latest user message
    const latestUserMessage = messages.data.findLast((m) => m.info.role === "user")

    if (latestUserMessage?.parts) {
      const textParts = latestUserMessage.parts.filter((p: any) => p.type === "text")
      if (textParts.length > 0) {
        return (textParts[0] as any).text
      }
    }
  } catch (error) {
    console.error("Failed to get prompt:", error)
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

        const prompt = await getLastUserPrompt(client, input.sessionID)
        if (prompt) {
          output.env.AGENT_PROMPT = prompt
        }
      }
    },
  }
}
