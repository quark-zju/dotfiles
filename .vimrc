" Vundle {{{
set nocompatible
filetype off

set rtp+=~/.vim/bundle/vundle/
call vundle#rc()

" as dependence
" github
Bundle 'kana/vim-textobj-user'
Bundle 'tpope/vim-repeat'
Bundle 'mirell/vim-matchit'
Bundle 'scrooloose/nerdtree'
" vim.org
Bundle 'taglist.vim'

" bundles
" github
Bundle 'ecomba/vim-ruby-refactoring'
Bundle 'gmarik/vundle'
Bundle 'godlygeek/tabular'
Bundle 'kchmck/vim-coffee-script'
Bundle 'kien/ctrlp.vim'
Bundle 'Lokaltog/vim-easymotion'
Bundle 'Lokaltog/vim-powerline'
Bundle 'lukerandall/haskellmode-vim'
Bundle 'nelstrom/vim-textobj-rubyblock'
Bundle 'scrooloose/syntastic'
Bundle 'SirVer/ultisnips'
Bundle 'tpope/vim-abolish'
Bundle 'tpope/vim-commentary'
Bundle 'tpope/vim-endwise'
Bundle 'tpope/vim-fugitive'
Bundle 'tpope/vim-haml'
Bundle 'tpope/vim-markdown'
Bundle 'tpope/vim-rails'
Bundle 'tpope/vim-surround'
Bundle 'tpope/vim-unimpaired'
Bundle 'Twinside/vim-syntax-haskell-cabal'

" vim.org
Bundle 'colorsupport.vim'
Bundle 'css_color.vim'
Bundle 'indentpython.vim'
Bundle 'iptables'
Bundle 'nginx.vim'
Bundle 'PKGBUILD'
Bundle 'python.vim'
Bundle 'renamer.vim'
Bundle 'Source-Explorer-srcexpl.vim'
Bundle 'trinity.vim'

" not used
" lucius author frequently changes design, not using its latest version
" Bundle 'Lucius'
" use meld GUI tool instead
" Bundle 'sjl/threesome.vim'

filetype plugin indent on
" }}}

" Base Configuration {{{
source $VIMRUNTIME/vimrc_example.vim
source $VIMRUNTIME/ftplugin/man.vim
" }}}

" Tab, Spaces, Indent, Number {{{
set expandtab
set smarttab
set autoindent 
set tabstop=4 
set shiftwidth=4 
set backspace=indent,eol,start
set nolinebreak
set nowrap
set textwidth=79
set formatoptions=tcqrnl
" per language settings
autocmd FileType ruby setlocal sw=2
" }}}

" Basic UI, Color Theme {{{
" enable syntax
syntax on
" for gvim, use lucius
if has("gui_running")
    set guioptions=egit
    set guifont=Terminus\ 9
    set nomousehide
    set lines=40
    set columns=83
    colorscheme mylucius
else
    colorscheme ron
endif
set showmode
set showcmd
set number
set cursorline
set cursorcolumn
" ttyfast significantly improve cursor moving speed with cursorcolumn
set ttyfast 
set lazyredraw
set ruler
set title
" highlight the column after textwidth column
set colorcolumn=+1
" wildmenu completion
set wildmenu
" }}}

" Status line (deprecated, use vim-powerline instead) {{{
" " always show status line
set laststatus=2
"
" " change statusline color when inserting
" augroup ft_statuslinecolor
"     au InsertEnter * hi StatusLine guifg=#2e3436 guibg=#8ae234
"     au InsertLeave * hi StatusLine guifg=#eee guibg=#444
" augroup END
" 
" " path, modified, readonly, preview, help, list
" set statusline=%f%m%r%w%h%q
" 
" " " show warning in red
" " set statusline+=%#redbar#
" " set statusline+=%*
" 
" " right align, show  file type, encoding, file format, line, col
" set statusline+=%=%{&ft}\ \ 
" set statusline+=%{strlen(&fenc)?&fenc:&enc},%{&ff}\ \ 
" set statusline+=%l\/%L\ \ %03c

" }}}

" Encodings {{{
set fileencodings=utf-8,ucs-bom,gb18030,default
" }}}

" Searching, Scrolling, Movement {{{
set ignorecase
set smartcase
set incsearch
set showmatch
set hlsearch
set gdefault
" preview at least next 4 lines
set scrolloff=4
set virtualedit=block
" }}}

" Swapping, Undos, Backups, Clipboard, Encrypt {{{
silent !mkdir /var/tmp/vim /tmp/vim > /dev/null 2>&1
set undofile
" set /tmp as swap dir and undodir
set dir=/var/tmp/vim,/tmp/vim,/tmp
set undodir=/var/tmp/vim,/tmp/vim,/tmp
" disable annoying backup file, thus no need to set backupdir
set nobackup
" Use X Window clipboard as default clipboard (VimTip21)
set clipboard=unnamedplus,autoselect
set cm=blowfish
" }}}

" Shortcut keys {{{
" <Leader>
let mapleader=","
" buffer switch using Alt+j,k
nmap <A-j> :bprev<CR>
nmap <A-k> :bnext<CR>
" clear matches
noremap <Leader><Space> :noh<CR>
" override D = d$
nnoremap D d$
" override H = ^, L = g_ (skip spaces)
noremap H ^
noremap L g_
" useful when a line is wrapped
nnoremap j gj
nnoremap k gk
" c-a, c-e style home, end
cnoremap <C-a> <Home>
cnoremap <C-e> <End>
" srcexpl, nerdtree, taglist toggle
nmap <F8> :TrinityToggleAll<CR>
nmap <F9> :NERDTree<CR>
" }}}

" Folding {{{
" <Space> toggles folds
nnoremap <Space> za
" fold level
set foldlevel=4
" zO recursively open all folds
nnoremap zO zCzO
set foldmethod=marker
" by filetype
autocmd FileType c,cpp,ruby setlocal foldmethod=syntax
autocmd FileType java,javascript setlocal foldmarker={,}
" }}}

" Custom commands {{{
" sudo write
cmap w!! w !sudo tee % >/dev/null
" }}}

" Plugin Settings {{{
" vim-srcexpl
let g:SrcExpl_pluginList=[
        \ "__Tag_List__",
        \ "NERD_tree",
        \ "NERD_tree_1",
        \ "NERD_tree_2",
        \ "Source_Explorer"
    \ ]
let g:SrcExpl_searchLocalDef=1
let g:SrcExpl_isUpdateTags=0
let g:SrcExpl_updateTagsCmd="ctags --sort=foldcase -R ."
let g:SrcExpl_updateTagsKey="<F12>" 

" vim-easymotion
let g:EasyMotion_leader_key=';' 

" UltiSnips
let g:UltiSnipsExpandTrigger="<tab>"
let g:UltiSnipsJumpForwardTrigger="<tab>"
let g:UltiSnipsJumpBackwardTrigger="<s-tab>"
let g:UltiSnipsListSnippets="<c-tab>"
let g:UltiSnipsSnippetDirectories=["UltiSnips", "snippets"]

" ctrlp
let g:ctrlp_map='<leader>t'
let g:ctrlp_match_window_reversed=0
let g:ctrlp_match_window_bottom=1
let g:ctrlp_working_path_mode=0
let g:ctrlp_dotfiles=0
let g:ctrlp_max_depth=5
let g:ctrlp_custom_ignore={
            \ 'dir':  '\.git$\|\.hg$\|\.svn$\|tmp$',
            \ 'file': '\.so$\|\.o$\|\.out$\|\.lock$',
            \ }
let g:ctrlp_max_files=400
nmap <unique> <silent> <Leader>b :CtrlPBuffer<CR>
nmap <unique> <silent> <Leader>m :CtrlPMRU<CR>

"" command-t (supressed by ctrlp)
" let g:CommandTMaxCachedDirectories=16
" let g:CommandTScanDotDirectories=0
" let g:CommandTMaxFiles=1024
" let g:CommandTMaxDepth=4

"" Molly (supressed by ctrlp)
" nmap <unique> <silent> <Leader>t :Molly<CR>


" }}}

