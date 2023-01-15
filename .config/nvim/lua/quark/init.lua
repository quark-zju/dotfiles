-- Generic utilities

local api = vim.api
local cursor = require('quark/cursor')
local utils = require('quark/utils')

-- Non-generic setups

local setup_plugins = function()
  utils.load_plugins {
    'easymotion/vim-easymotion',
    'justinmk/vim-sneak',
    'mhinz/vim-janah',
    'racer-rust/vim-racer',
    'rust-lang/rust.vim',
    'vim-scripts/ctrlp.vim',
    'vim-scripts/indentpython.vim',
    'vim-scripts/python.vim',
    'roxma/nvim-yarp',
    'simnalamburt/vim-mundo',
    'neovim/nvim-lspconfig',
    'simrat39/rust-tools.nvim',
    'hrsh7th/nvim-cmp',
    'hrsh7th/cmp-nvim-lsp',
    'hrsh7th/cmp-nvim-lsp-signature-help',
    'hrsh7th/cmp-buffer',
    'dcampos/nvim-snippy',
  }
end

local setup_basic_options = function()
  utils.set_options('global', {
    clipboard = 'unnamedplus',
    completeopt = 'noinsert,menuone',
    fileencodings = 'utf-8,ucs-bom,gb18030,big5,shift-jis,default',
    gdefault = true,
    ignorecase = true,
    inccommand = 'nosplit',
    lazyredraw = true,
    scrolloff = 5,
    showmatch = true,
    smartcase = true,
    termguicolors = true, -- 24-bit colors
    title = true,
    titlelen = 4096,
    titlestring = '%t%( %M%)%( (%F)%)%( %a%)',
    virtualedit = 'block,insert',
    wildmenu = true,
  })
  utils.set_options('global win', {
    cursorline = true,
    foldlevel = 10,
    foldmethod = 'indent',
    number = true,
    wrap = false,
  })
  utils.set_options('global buf', {
    expandtab = true,
    fileencoding = 'utf-8',
    formatoptions = 'cqnlj', -- auto text wrap. comments but not text
    shiftwidth = 2,
    tabstop = 2,
    textwidth = 79,
    undofile = true,
  })
end

local setup_key_mappings = function()
  utils.set_globals { mapleader = ',' }

  utils.map_keys('nnore', {
    -- buffer switch
    ['<A-j>'] = ':bprev<CR>',
    ['<A-k>'] = ':bnext<CR>',

    -- clear match highlight
    ['<Leader><Space>'] = ':noh<CR>',

    -- movements
    D = 'd$',
    H = '^',
    L = 'g_',
    j = 'gj',
    k = 'gk',

    -- jump to non-space character vertically
    ['<C-k>'] = ":call search('\\%' . virtcol('.') . 'v\\S', 'bW')<CR>",
    ['<C-j>'] = ":call search('\\%' . virtcol('.') . 'v\\S', 'wW')<CR>",
  })

  utils.map_keys('tnore', {
    ['<Esc>'] = '<C-\\><C-n>',
  })

  utils.map_keys('cnore', {
    ['=json'] = '!python -m json.tool',
    ['w!!'] = 'w !sudo tee % >/dev/null',
  })
end

local setup_colors = function()
  local cmd = utils.cmd
  cmd('colorscheme mylucius')
  cmd('hi Search guibg=#ffaa33 guifg=#333333 gui=NONE')
  cmd('hi Pmenu  ctermfg=254 ctermbg=235 guifg=#e4e4e4 guibg=#383838')
end

local setup_ctrlp = function()
  utils.set_globals {
    ctrlp_map = '<leader>t',
    ctrlp_match_window_reversed = 0,
    ctrlp_match_window_bottom = 1,
    ctrlp_working_path_mode = 0,
    ctrlp_dotfiles = 0,
    ctrlp_max_depth = 5,
    ctrlp_max_files = 400,
    ctrlp_custom_ignore = {
      dir = '.git$|.hg$|.svn$|tmp|public|node_modules|.arc|.idea|vendor|.tmp$',
      file = '.so$|.o$|.out$|.lock$|.png$|.bmp$|.jpg|.log$',
    },
  }

  utils.map_keys('nnore', {
    ['<Leader>b'] = ':CtrlPBuffer<CR>', -- buffers
    ['<Leader>m'] = ':CtrlPMRU<CR>', -- recent
  })
end

-- rust-tools provides inlay hints and code actions
local setup_rust_tools = function()
  local rt = require('rust-tools')
  rt.setup {
    server = {
      on_attach = function(_, bufnr)
        -- Hover actions
        vim.keymap.set("n", "<C-space>", rt.hover_actions.hover_actions, { buffer = bufnr })
        -- Code action groups
        vim.keymap.set("n", "<Leader>a", rt.code_action_group.code_action_group, { buffer = bufnr })
      end,
      settings = {
        ['rust-analyzer'] = {
          imports = {
            granularity = {
              group = "item",
            },
            prefix = "plain",
          },
        },
      },
    },
  }
end

-- snippy provides code completion framework
local setup_snippy = function()
  local snippy = require('snippy')
  snippy.setup {
    mappings = {
      is = {
        ['<Tab>'] = 'expand_or_advance',
        ['<S-Tab>'] = 'previous',
      },
      nx = {
        ['<leader>x'] = 'cut_text',
      },
    }
  }
end

-- cmp provides LSP based code completion
local setup_cmp = function()
  local cmp = require('cmp')
  cmp.setup {
    snippet = {
      -- cmp requires a snippet engine
      expand = function(args)
        require('snippy').expand_snippet(args.body)
      end,
    },
    mapping = cmp.mapping.preset.insert({
      ['<C-b>'] = cmp.mapping.scroll_docs(-4),
      ['<C-f>'] = cmp.mapping.scroll_docs(4),
      ['<C-Space>'] = cmp.mapping.complete(),
      ['<C-e>'] = cmp.mapping.abort(),
      ['<CR>'] = cmp.mapping.confirm({ select = true }),
      ['<tab>'] = cmp.mapping.confirm({ select = true }),
    }),
    sources = {
      {
        name = 'nvim_lsp',
        group_index = 1,
        -- Drop noisy "Snippet" completions.
        entry_filter = function(entry, ctx)
          return require('cmp.types').lsp.CompletionItemKind[entry:get_kind()] ~= 'Snippet'
        end
      },
      { name = 'nvim_lsp_signature_help', group_index = 1, },
      { name = 'buffer', keyword_length = 4, group_index = 2, },
    }
  }
end

-- Callbacks. Still need VimL autocmd to trigger

local handle_filetype_change = function()
  local filetype = api.nvim_buf_get_option(api.nvim_get_current_buf(), 'filetype')
  local handler_map = {
    rust = function()
      utils.map_keys('n', {
        gD = '<Plug>(rust-def)',
        gs = '<Plug>(rust-def-split)',
        gx = '<Plug>(rust-def-vertical)',
        gh = '<Plug>(rust-doc)',
      })
    end,
  }
  utils.try_call(handler_map[filetype])
end

local handle_buf_read_post = function()
  -- disable highlight for large files
  local line_count = api.nvim_buf_line_count(api.nvim_get_current_buf())
  if line_count > 20000 then
    utils.set_options('buf', { syntax = false })
  end
end

local handle_event = function(name)
  local handler_map = {
    FileType = handle_filetype_change,
    BufReadPost = handle_buf_read_post,
  }
  utils.try_call(handler_map[name])
  cursor.handle_event(name)
end

-- Main entry

local init = function()
  setup_plugins()
  setup_basic_options()
  setup_key_mappings()
  setup_colors()
  setup_ctrlp()
  setup_snippy()
  setup_cmp()
  setup_rust_tools()
end

return {
  init = init,
  handle_event = handle_event,
}
