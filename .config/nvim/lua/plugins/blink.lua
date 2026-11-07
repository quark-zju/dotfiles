return {
  "saghen/blink.cmp",
  opts = {
    sources = {
      providers = {
        path = {
          transform_items = function(_, items)
            return vim.tbl_filter(function(item)
              -- Opening a FIFO for a preview can block Neovim on exit.
              return item.data.type ~= "fifo"
            end, items)
          end,
        },
      },
    },
  },
}
