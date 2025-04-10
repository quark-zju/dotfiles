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
    "williamboman/mason.nvim",
    opts = function(_, opts)
      opts.PATH = "append"
      return opts
    end,
  },
}
