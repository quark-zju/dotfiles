-- Options are automatically loaded before lazy.nvim startup
-- Default options that are always set: https://github.com/LazyVim/LazyVim/blob/main/lua/lazyvim/config/options.lua
-- Add any additional options here

local opt = vim.opt

opt.relativenumber = false
opt.conceallevel = 0

if vim.env.SSH_TTY then
  vim.g.clipboard = {
    name = "FileClipboard",
    copy = {
      ["+"] = { "sh", "-c", "cat > ~/c" },
      ["*"] = { "sh", "-c", "cat > ~/c" },
    },
    paste = {
      ["+"] = { "sh", "-c", "cat ~/c" },
      ["*"] = { "sh", "-c", "cat ~/c" },
    },
    cache_enabled = 0,
  }
  opt.clipboard = "unnamedplus"
end

vim.g.snacks_animate = false
