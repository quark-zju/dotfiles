import type { Plugin } from "@opencode-ai/plugin"

async function getModelNameAndPrompts(client: ReturnType<typeof import("@opencode-ai/plugin")["createOpencodeClient"]>, sessionID: string): Promise<{ modelName: string | undefined; prompts: string | undefined }> {
  try {
    const messagesResponse = await client.session.messages({
      path: { id: sessionID },
      query: { limit: 100 },
    })

    const messagesAsc = messagesResponse.data
    const messagesDesc = messagesAsc.reverse()

    const lastMessage = messagesDesc.find((m) => m.info?.model)
    let modelName: string | undefined
    if (lastMessage?.info.model) {
      const { modelID } = lastMessage.info.model
      modelName = `${modelID}`
    }

    const prompts: string[] = []
    for (const msg of messagesDesc) {
      if (msg.info.role === "assistant" && msg.parts && hasGitCommit(msg.parts)) {
        break
      }

      if (msg.info.role === "user" && msg.parts) {
        const textParts = msg.parts.filter((p: any) => p.type === "text")
        if (textParts.length > 0) {
          prompts.push((textParts[0] as any).text)
        }
      }
    }

    const promptStr = prompts.length > 0 ? prompts.reverse().join("\n----\n") : undefined

    return { modelName, prompts: promptStr }
  } catch (error) {
    console.error("Failed to get messages:", error)
  }
  return { modelName: undefined, prompts: undefined }
}

function hasGitCommit(parts: any[]): boolean {
  return parts.some((p) => {
    if (p.type !== "tool" || p.tool !== "bash") return false
    const status = p.state?.status
    if (status === "running") {
      return false
    }
    const command = p.state?.input?.command?.toLowerCase() ?? ""
    return command.includes("git commit")
  })
}

export const SetAgentModelEnv: Plugin = async ({ client }) => {
  return {
    "shell.env": async (input, output) => {
      if (input.sessionID) {
        const { modelName, prompts } = await getModelNameAndPrompts(client, input.sessionID)
        if (modelName) {
          output.env.AGENT_MODEL = modelName
        }
        if (prompts) {
          output.env.AGENT_PROMPT = prompts
        }
      }
    },
  }
}
