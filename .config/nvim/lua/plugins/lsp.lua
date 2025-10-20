return {
  {
    "neovim/nvim-lspconfig",
    opts = {
      inlay_hints = {
        enabled = true,
      },
    },
  },
  {
    "mason-org/mason.nvim",
    opts = function(_, opts)
      opts.PATH = "append"
      return opts
    end,
  },
}
