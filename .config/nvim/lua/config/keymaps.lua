-- Keymaps are automatically loaded on the VeryLazy event
-- Default keymaps that are always set: https://github.com/LazyVim/LazyVim/blob/main/lua/lazyvim/config/keymaps.lua
-- Add any additional keymaps here

-- LazyVim sets Ctrl-h/j/k/l to move Window, but Ctrl-L is also useful in terminal...
vim.api.nvim_del_keymap("t", "<C-l>")
