-- Autocmds are automatically loaded on the VeryLazy event
-- Default autocmds that are always set: https://github.com/LazyVim/LazyVim/blob/main/lua/lazyvim/config/autocmds.lua
-- Add any additional autocmds here

-- Disable autoformat for markdown files
vim.api.nvim_create_autocmd({ "FileType" }, {
  pattern = { "markdown", "yaml", "sh", "toml" },
  callback = function()
    vim.b.autoformat = false
  end,
})

local cjk = vim.regex("[一-鿿]")

local function disable_spell_for_cjk()
  if vim.opt_local.spell:get() and vim.fn.search("[一-鿿]", "nw") > 0 then
    vim.opt_local.spell = false
  end
end

vim.api.nvim_create_autocmd("FileType", {
  pattern = { "markdown", "markdown.mdx" },
  callback = disable_spell_for_cjk,
})

vim.api.nvim_create_autocmd("InsertCharPre", {
  callback = function()
    if vim.bo.filetype:match("^markdown") and cjk:match_str(vim.v.char) then
      vim.opt_local.spell = false
    end
  end,
})

vim.api.nvim_create_autocmd("TextChanged", {
  callback = function()
    if vim.bo.filetype:match("^markdown") then
      disable_spell_for_cjk()
    end
  end,
})
