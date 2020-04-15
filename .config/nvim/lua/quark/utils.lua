local api = vim.api

local try_call = function(func)
  if func ~= nil then
    func()
  end
end

local set_globals = function(globals)
  local set = api.nvim_set_var
  for name, value in pairs(globals) do
    set(name, value)
  end
end

local set_options = function(scope, options)
  local set = function(name, value) end
  if scope and scope:match('global') then
    set = api.nvim_set_option
  end
  if scope and scope:match('buf') then
    (function(orig, buf_handle)
      set = function(name, value)
        orig(name, value)
        api.nvim_buf_set_option(buf_handle, name, value)
      end
    end)(set, api.nvim_get_current_buf())
  end
  if scope and scope:match('win') then
    (function(orig, win_handle)
      set = function(name, value)
        orig(name, value)
        api.nvim_win_set_option(win_handle, name, value)
      end
    end)(set, api.nvim_get_current_win())
  end
  for name, value in pairs(options) do
    set(name, value)
  end
end

local load_plugins = function(names)
  -- Require 'vim-plug'
  local call = api.nvim_call_function
  call('plug#begin', {})
  for _, name in ipairs(names) do
    call('plug#', {name})
  end
  call('plug#end', {})
end

local map_keys = function(mode, keymap)
  local cmd = api.nvim_command
  for lhs, rhs in pairs(keymap) do
    cmd(mode .. 'map ' .. lhs .. ' ' .. rhs)
  end
end

return {
  api = api,
  cmd = api.nvim_command,
  load_plugins = load_plugins,
  map_keys = map_keys,
  set_globals = set_globals,
  set_options = set_options,
  try_call = try_call,
}
