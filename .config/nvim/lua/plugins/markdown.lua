local config = vim.fn.expand("~/.config/nvim/markdownlint.json")

return {
  {
    "mfussenegger/nvim-lint",
    opts = {
      linters = {
        ["markdownlint-cli2"] = {
          args = { "--config", config },
        },
      },
    },
  },
  {
    "stevearc/conform.nvim",
    opts = {
      formatters = {
        ["markdownlint-cli2"] = {
          args = { "--config", config, "--fix", "$FILENAME" },
        },
      },
    },
  },
}
