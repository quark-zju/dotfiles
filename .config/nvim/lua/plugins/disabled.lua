return {
  { "markdown-preview.nvim", enabled = false },
  { "folke/flash.nvim", enabled = false }, -- break "/" search expectation
  -- disable (annoying) mini.indentscope animation
  {
    "echasnovski/mini.indentscope",
    opts = {
      draw = { animation = require("mini.indentscope").gen_animation.none() },
    },
  },
  -- disable (annoying) auto pairing {}, "", ''.
  {
    "echasnovski/mini.pairs",
    enabled = false,
  },
  -- plugins that seem over fancy...
  { "echasnovski/mini.ai", enabled = false },
  { "echasnovski/mini.comment", enabled = false },
  { "echasnovski/mini.ai", enabled = false },
  { "folke/noice.nvim", enabled = false },
  { "nvimdev/dashboard-nvim", enabled = false },
  { "rcarriga/nvim-notify", enabled = false },
  { "nvim-neo-tree/neo-tree.nvim", enabled = false },
  { "folke/persistence.nvim", enabled = false },
  { "stevearc/dressing.nvim", enabled = false },
  { "rafamadriz/friendly-snippets", enabled = false },
}
