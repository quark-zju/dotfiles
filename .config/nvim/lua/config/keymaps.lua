-- Keymaps are automatically loaded on the VeryLazy event
-- Default keymaps that are always set: https://github.com/LazyVim/LazyVim/blob/main/lua/lazyvim/config/keymaps.lua
-- Add any additional keymaps here

-- LazyVim sets Ctrl-h/j/k/l to move Window, but Ctrl-L is also useful in terminal...
-- vim.api.nvim_del_keymap("t", "<C-l>")

-- Ctrl+G: Search current word or selection
vim.keymap.set({ "n", "v" }, "<C-g>", function()
  local selection = vim.fn.visualmode() == "V" and vim.fn.getreg('"') or vim.fn.expand("<cword>")
  local fzf = require("fzf-lua")
  fzf.live_grep({
    query = selection,
    winopts = { split = "belowright new" },
    -- actions = {
    --   true,
    --   ["enter"] = fzf.actions.file_edit,
    -- },
  })
end)

-- Ctrl+K: Move up vertically to the first non-space character.
vim.keymap.set({ "n", "v" }, "<C-k>", function()
  local cursor = vim.api.nvim_win_get_cursor(0)
  local current_row = cursor[1]
  local current_col = cursor[2]
  for row = current_row - 1, 1, -1 do
    local line = vim.api.nvim_buf_get_lines(0, row - 1, row, false)[1] or ""
    local char_at_col = line:sub(current_col + 1, current_col + 1)
    if char_at_col ~= "" and char_at_col ~= " " and char_at_col ~= "\t" then
      vim.api.nvim_win_set_cursor(0, { row, current_col })
      return
    end
  end
end)

-- Ctrl+J: Move down vertically to the first non-space character.
vim.keymap.set({ "n", "v" }, "<C-j>", function()
  local cursor = vim.api.nvim_win_get_cursor(0)
  local current_row = cursor[1]
  local current_col = cursor[2]
  local total_lines = vim.api.nvim_buf_line_count(0)
  for row = current_row + 1, total_lines do
    local line = vim.api.nvim_buf_get_lines(0, row - 1, row, false)[1] or ""
    local char_at_col = line:sub(current_col + 1, current_col + 1)
    if char_at_col ~= "" and char_at_col ~= " " and char_at_col ~= "\t" then
      vim.api.nvim_win_set_cursor(0, { row, current_col })
      return
    end
  end
end)
