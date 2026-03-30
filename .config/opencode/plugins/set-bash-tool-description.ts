import type { Plugin } from "@opencode-ai/plugin"


// Encourage more commits. Discourage "git diff" (waste context).
function patchOpencodeBashToolDescription(input: string): string {
  let text = input;

  // Replace the "Avoid using Bash with ..." block.
  // (sed can sometimes be handy)
  text = text.replace(
    /[ \t]*- Avoid using Bash with the (`find`, `grep`, `cat`, `head`, `tail`, `sed`, `awk`, or `echo` commands),.*always prefer using the dedicated tools for these commands:/,
    [
      "  - Prefer dedicated tools to raw bash $1. But still use bash if they are much simpler (e.g. `sed` simple replace for multiple files).",
    ].join("\n"),
  );

  // Change the example to not encourage "git diff".
  text = text.replace(
    /If the commands are independent and can run in parallel, make multiple Bash tool calls in a single message\. For example, if you need to run "git status" and "git diff", send a single message with two Bash tool calls in parallel\./,
    'If the commands are independent and can run in parallel, make multiple Bash tool calls in a single message. For example, if you need to run "cargo check", "cargo test -q", "git status", "git log", send a single message with multiple Bash tool calls in parallel.',
  );

  // Delete the long "Only create commits when requested..." intro block,
  // Creating commits is recommended.
  text = text.replace(
    /\nOnly create commits when requested by the user\..*/,
    "",
  );

  // Delete the standalone "NEVER commit changes unless ..." line
  // Creating commits is recommended.
  text = text.replace(
    /\n- NEVER commit changes unless the user explicitly asks you to\.[^\n]*/,
    "",
  );

  // Delete git sections that encourage "git diff".
  text = text.replace(
    /\n1\. You can call multiple tools in a single response\.(.|\n)*fails due to pre-commit.*/,
    "",
  );

  // 6) Delete section 2 completely.
  text = text.replace(
    /\n2\. Analyze all staged changes \(both previously staged and newly added\) and draft a commit message:[\s\S]*?(?=\n3\. You can call multiple tools in a single response\.)/,
    "\n",
  );

  // 7) Delete "# Creating pull requests" to the end of the document.
  text = text.replace(
    /\n# Creating pull requests[\s\S]*$/,
    "",
  );

  // Optional cleanup: collapse excessive blank lines.
  text = text.replace(/\n{3,}/g, "\n\n");

  return text.trim();
}


export const SetAgentModelEnv: Plugin = async ({ client }) => {
  return {
    "tool.definition": async ({ toolID }, output) => {
      if (toolID === "bash") {
        const newDesc = patchOpencodeBashToolDescription(output.description);
        output.description = newDesc;
      }
    },
  }
}
