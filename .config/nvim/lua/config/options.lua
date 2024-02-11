-- Options are automatically loaded before lazy.nvim startup
-- Default options that are always set: https://github.com/LazyVim/LazyVim/blob/main/lua/lazyvim/config/options.lua
-- Add any additional options here

local opt = vim.opt

opt.relativenumber = false

if os.getenv("SSH_CLIENT") then
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
end
