-- What <tab> key does in insert mode

local api = vim.api
local ctrl_f = api.nvim_eval('"\\<C-f>"')
local ctrl_o = api.nvim_eval('"\\<C-o>"')
local ctrl_p = api.nvim_eval('"\\<C-p>"')
local ctrl_x = api.nvim_eval('"\\<C-x>"')

local handle_insert_tab = function()
  local line = api.nvim_get_current_line()
  local pos = api.nvim_win_get_cursor(api.nvim_get_current_win())
  local col = pos[2]
  local keys = nil

  -- complete happens at the end of line, and when last non-space word has something
  if api.nvim_strwidth(line) == col and not line:match('^%s*$') then
    -- last word (split by space)
    local last_word = line:match('%S*$') or ''

    -- plugin complete ?
    if keys == nil and last_word:find('.') then
      local omnifunc = api.nvim_buf_get_option(api.nvim_get_current_buf(), 'omnifunc') or ''
      if #omnifunc > 0 then
        keys = ctrl_x .. ctrl_o
      end
    end

    -- path complete ?
    if keys == nil and last_word:find('/') then
      keys = ctrl_x .. ctrl_f
    end

    -- word complte ?
    if keys == nil and #last_word > 0 then
      keys = ctrl_x .. ctrl_p
    end
  end

  api.nvim_feedkeys(keys or '\t', 'nt', false)
  return ''
end

return {
  handle_insert_tab = handle_insert_tab,
}
