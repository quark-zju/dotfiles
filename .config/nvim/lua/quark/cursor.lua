-- change cursor color depending on active buffer and mode

local api = vim.api
local cmd = api.nvim_command
local utils = require('quark/utils')

local handle_event = function(name)
  if name == 'WinEnter' then
    -- only enable cursorline for the current window
    local wins = api.nvim_list_wins()
    local current_win = api.nvim_get_current_win()
    for _, win in ipairs(wins) do
      api.nvim_win_set_option(win, 'cursorline', win == current_win)
    end
  elseif name == 'InsertLeave' then
    cmd('hi CursorLine   ctermbg=234 guibg=#333333')
  elseif name == 'InsertEnter' then
    cmd('hi CursorLine   ctermbg=235 guibg=#223f44')
  end
end

return {
  handle_event = handle_event,
}
