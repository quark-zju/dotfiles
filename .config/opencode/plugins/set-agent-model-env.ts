import type { Plugin } from "@opencode-ai/plugin"

async function getModelName(client: ReturnType<typeof import("@opencode-ai/plugin")["createOpencodeClient"]>, sessionID: string): Promise<string | undefined> {
  try {
    const messages = await client.session.messages({
      path: { id: sessionID },
      query: { limit: 10 },
    })

    const latestUserMessage = messages.data.find(
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

export const SetAgentModelEnv: Plugin = async ({ client }) => {
  return {
    "shell.env": async (input, output) => {
      if (input.sessionID) {
        const modelName = await getModelName(client, input.sessionID)
        if (modelName) {
          output.env.AGENT_MODEL = modelName
        }
      }
    },
  }
}
