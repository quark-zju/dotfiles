lua require('quark/init').init()

" autocmd is still VimL only (as of nvim 0.3.1)
autocmd BufReadPost * lua require('quark/init').handle_event('BufReadPost')
autocmd FileType    * lua require('quark/init').handle_event('FileType')
autocmd InsertEnter * lua require('quark/init').handle_event('InsertEnter')
autocmd InsertLeave * lua require('quark/init').handle_event('InsertLeave')
autocmd WinEnter    * lua require('quark/init').handle_event('WinEnter')
autocmd WinLeave    * lua require('quark/init').handle_event('WinLeave')

set spell spelllang=en_us